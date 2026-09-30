from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .city_resolve import async_search_cities, build_weather_instance, pick_label
from .const import (
    CONF_API_HOST,
    CONF_API_KEY,
    CONF_ENABLED,
    CONF_FORECAST_DAYS,
    CONF_INDICES_ENABLED,
    CONF_INSTANCES,
    CONF_INTERVAL,
    CONF_LOCATION,
    CONF_NOTIFY_ALARM,
    CONF_NOTIFY_ALARM_ANNOUNCE,
    CONF_NOTIFY_ALARM_NOTIFY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_END,
    CONF_NOTIFY_RAIN,
    CONF_NOTIFY_RAIN_ANNOUNCE,
    CONF_NOTIFY_RAIN_NOTIFY,
    CONF_NOTIFY_START,
    CONF_PROVIDER,
    CONF_SLUG,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_NAME,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_END,
    DEFAULT_NOTIFY_START,
    DEFAULT_WEATHER_INTERVAL,
    DOMAIN,
    PROVIDER_CAIYUN,
    PROVIDER_QWEATHER,
    PROVIDER_TIANQI,
)
from .defaults import default_options, default_weather_instance, merge_options


def _notify_values(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        action = raw.get("action") or raw.get("service")
        return [action] if action else []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            out.append(item)
        elif isinstance(item, dict):
            action = item.get("action") or item.get("service")
            if action:
                out.append(action)
    return out


def _notify_options(hass: HomeAssistant | None, current: Any = None) -> list[str]:
    names: set[str] = set(_notify_values(current))
    if hass:
        for name in hass.services.async_services().get("notify", {}):
            if name != "send_message":
                names.add(f"notify.{name}")
        names.update(hass.states.async_entity_ids("notify"))
    return sorted(names)


def _notify_selector(hass: HomeAssistant | None, current: Any) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=_notify_options(hass, current),
            multiple=True,
            custom_value=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _announce_selector() -> EntitySelector:
    return EntitySelector(
        EntitySelectorConfig(domain=["media_player", "tts", "text", "input_text"])
    )


def _channel_fields(
    hass: HomeAssistant | None,
    notify_key: str,
    notify_current: Any,
    announce_key: str,
    announce_current: Any,
) -> dict[Any, Any]:
    notify = _notify_values(notify_current)
    announce = announce_current if isinstance(announce_current, str) and announce_current else None
    notify_field = (
        vol.Optional(notify_key, default=notify) if notify else vol.Optional(notify_key)
    )
    announce_field = (
        vol.Optional(announce_key, default=announce)
        if announce
        else vol.Optional(announce_key)
    )
    return {
        notify_field: _notify_selector(hass, notify),
        announce_field: _announce_selector(),
    }


def _city_options(instances: list[dict[str, Any]]) -> list[dict[str, str]]:
    opts: list[dict[str, str]] = []
    for idx, inst in enumerate(instances):
        name = inst.get(CONF_NAME) or inst.get(CONF_LOCATION) or str(idx)
        loc = inst.get(CONF_LOCATION) or ""
        opts.append({"value": str(idx), "label": f"{name} ({loc})"})
    return opts


def _unique_slug(desired: str, instances: list[dict[str, Any]], skip: int | None = None) -> str:
    base = desired or "city"
    used = {
        str(inst.get(CONF_SLUG) or "")
        for i, inst in enumerate(instances)
        if skip is None or i != skip
    }
    if base not in used:
        return base
    n = 2
    while f"{base}_{n}" in used:
        n += 1
    return f"{base}_{n}"


class WeatherForecastConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = default_options()
        self._pending: dict[str, Any] = {}
        self._city_candidates: list[dict[str, str]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            self._data = {
                CONF_NAME: user_input.get(CONF_NAME) or DEFAULT_NAME,
                CONF_NOTIFY_ENABLED: user_input.get(
                    CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED
                ),
            }
            return await self.async_step_city()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=DEFAULT_NOTIFY_ENABLED
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_city(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            query = (user_input.get("city") or "").strip()
            provider = user_input.get(CONF_PROVIDER) or PROVIDER_TIANQI
            api_key = user_input.get(CONF_API_KEY) or ""
            api_host = user_input.get(CONF_API_HOST) or ""
            if provider in (PROVIDER_QWEATHER, PROVIDER_CAIYUN) and not api_key:
                errors["api_key"] = "api_key_required"
            else:
                candidates = await async_search_cities(
                    self.hass,
                    query,
                    provider=provider,
                    api_key=api_key,
                    api_host=api_host,
                )
                if not candidates:
                    errors["city"] = "city_not_found"
                else:
                    self._pending = {
                        CONF_INTERVAL: int(
                            user_input.get(CONF_INTERVAL) or DEFAULT_WEATHER_INTERVAL
                        ),
                        "add_another": bool(user_input.get("add_another")),
                        CONF_PROVIDER: provider,
                        CONF_API_KEY: api_key,
                        CONF_API_HOST: api_host,
                    }
                    self._city_candidates = candidates
                    if len(candidates) == 1:
                        return await self._async_commit_city(candidates[0])
                    return await self.async_step_pick()

        schema = vol.Schema(
            {
                vol.Required("city", default="杭州"): TextSelector(),
                vol.Required(CONF_PROVIDER, default=PROVIDER_TIANQI): SelectSelector(
                    SelectSelectorConfig(
                        options=[PROVIDER_TIANQI, PROVIDER_QWEATHER, PROVIDER_CAIYUN],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="weather_provider",
                    )
                ),
                vol.Required(
                    CONF_INTERVAL, default=DEFAULT_WEATHER_INTERVAL
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=180, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_API_KEY, default=""): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_API_HOST, default=""): TextSelector(),
                vol.Required("add_another", default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="city", data_schema=schema, errors=errors)

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if not self._city_candidates:
            return await self.async_step_city()
        options = [
            {"value": c["area_id"], "label": pick_label(c)}
            for c in self._city_candidates
        ]
        if user_input is not None:
            area_id = user_input.get("area_id")
            chosen = next(
                (c for c in self._city_candidates if c.get("area_id") == area_id),
                None,
            )
            if not chosen:
                errors["area_id"] = "city_not_found"
            else:
                return await self._async_commit_city(chosen)

        schema = vol.Schema(
            {
                vol.Required("area_id", default=options[0]["value"]): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="pick", data_schema=schema, errors=errors)

    async def _async_commit_city(self, city: dict[str, str]) -> ConfigFlowResult:
        pending = self._pending
        instances = self._options.setdefault(CONF_INSTANCES, [])
        inst = build_weather_instance(
            area_id=city["area_id"],
            display_name=city.get("name") or city["area_id"],
            interval=pending.get(CONF_INTERVAL),
            extra={
                CONF_PROVIDER: pending.get(CONF_PROVIDER) or PROVIDER_TIANQI,
                CONF_API_KEY: pending.get(CONF_API_KEY) or "",
                CONF_API_HOST: pending.get(CONF_API_HOST) or "",
                CONF_LOCATION: city.get("location") or city["area_id"],
                "lon": city.get("lon") or "",
                "lat": city.get("lat") or "",
            },
        )
        inst[CONF_SLUG] = _unique_slug(inst.get(CONF_SLUG) or "city", instances)
        instances.append(inst)
        self._pending = {}
        self._city_candidates = []
        if pending.get("add_another"):
            return await self.async_step_city()
        return self._create()

    def _create(self) -> ConfigFlowResult:
        options = deepcopy(self._options)
        options[CONF_NOTIFY_ENABLED] = True
        return self.async_create_entry(
            title=self._data.get(CONF_NAME) or DEFAULT_NAME,
            data={
                CONF_NAME: self._data.get(CONF_NAME) or DEFAULT_NAME,
                CONF_NOTIFY_ENABLED: self._data.get(
                    CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED
                ),
            },
            options=options,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WeatherForecastOptionsFlow()


class WeatherForecastOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._candidates: list[dict[str, str]] = []
        self._draft: dict[str, Any] = {}
        self._edit_index: int | None = None
        self._mode: str = "add"

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._options = merge_options(dict(self.config_entry.options))
        return await self.async_step_menu(user_input)

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(title="", data=self._options)

    def _instances(self) -> list[dict[str, Any]]:
        return list(self._options.get(CONF_INSTANCES) or [])

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            next_step = user_input.get("next")
            if next_step == "global":
                return await self.async_step_global()
            if next_step == "cities":
                return await self.async_step_cities()
        schema = vol.Schema(
            {
                vol.Required("next", default="cities"): SelectSelector(
                    SelectSelectorConfig(
                        options=["global", "cities"],
                        mode=SelectSelectorMode.LIST,
                        translation_key="menu_next",
                    )
                )
            }
        )
        return self.async_show_form(step_id="menu", data_schema=schema)

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options[CONF_ENABLED] = user_input.get(CONF_ENABLED, True)
            new_data = {
                **dict(self.config_entry.data),
                CONF_NOTIFY_ENABLED: user_input.get(CONF_NOTIFY_ENABLED, True),
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self._save()
        global_enabled = self.config_entry.data.get(
            CONF_NOTIFY_ENABLED,
            self._options.get(CONF_NOTIFY_ENABLED, True),
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENABLED, default=self._options.get(CONF_ENABLED, True)
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_ENABLED,
                    default=global_enabled,
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="global", data_schema=schema)

    async def async_step_cities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        instances = self._instances()
        names = [inst.get(CONF_NAME) or inst.get(CONF_LOCATION) or "?" for inst in instances]
        desc = "、".join(names) if names else ""
        if user_input is not None:
            action = user_input.get("action")
            if action == "add":
                self._mode = "add"
                self._edit_index = None
                return await self.async_step_city_form()
            if action == "edit" and instances:
                return await self.async_step_select_city({"purpose": "edit"})
            if action == "delete" and instances:
                return await self.async_step_select_city({"purpose": "delete"})
            if action == "back" or action in ("edit", "delete"):
                return await self.async_step_menu()
            return await self.async_step_menu()
        actions = ["add", "back"]
        if instances:
            actions = ["add", "edit", "delete", "back"]
        schema = vol.Schema(
            {
                vol.Required("action", default="add"): SelectSelector(
                    SelectSelectorConfig(
                        options=actions,
                        mode=SelectSelectorMode.LIST,
                        translation_key="cities_action",
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="cities",
            data_schema=schema,
            description_placeholders={"cities": desc or "-"},
        )

    async def async_step_select_city(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        instances = self._instances()
        if not instances:
            return await self.async_step_cities()
        purpose = (user_input or {}).get("purpose") or self._draft.get("purpose") or "edit"
        options = _city_options(instances)
        if user_input is not None and "city_index" in user_input:
            try:
                idx = int(user_input["city_index"])
            except (TypeError, ValueError):
                idx = -1
            if idx < 0 or idx >= len(instances):
                return await self.async_step_cities()
            if purpose == "delete":
                self._edit_index = idx
                return await self.async_step_delete_city()
            self._mode = "edit"
            self._edit_index = idx
            return await self.async_step_city_form()
        self._draft = {"purpose": purpose}
        schema = vol.Schema(
            {
                vol.Required("city_index", default=options[0]["value"]): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="select_city", data_schema=schema)

    async def async_step_delete_city(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        instances = self._instances()
        idx = self._edit_index
        if idx is None or idx < 0 or idx >= len(instances):
            return await self.async_step_cities()
        inst = instances[idx]
        name = inst.get(CONF_NAME) or inst.get(CONF_LOCATION) or str(idx)
        if user_input is not None:
            if user_input.get("confirm"):
                instances.pop(idx)
                self._options[CONF_INSTANCES] = instances
                self._edit_index = None
                return self._save()
            return await self.async_step_cities()
        schema = vol.Schema(
            {vol.Required("confirm", default=False): BooleanSelector()}
        )
        return self.async_show_form(
            step_id="delete_city",
            data_schema=schema,
            description_placeholders={"city": name},
        )

    async def async_step_city_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        instances = self._instances()
        editing = self._mode == "edit" and self._edit_index is not None
        base = (
            instances[self._edit_index]
            if editing and 0 <= self._edit_index < len(instances)
            else default_weather_instance()
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            city_query = (user_input.get("city") or "").strip()
            provider = user_input.get(CONF_PROVIDER) or PROVIDER_TIANQI
            api_key = user_input.get(CONF_API_KEY) or ""
            api_host = user_input.get(CONF_API_HOST) or ""
            interval = int(
                user_input.get(CONF_INTERVAL)
                or base.get(CONF_INTERVAL)
                or DEFAULT_WEATHER_INTERVAL
            )
            forecast_days = int(
                user_input.get(CONF_FORECAST_DAYS) or DEFAULT_FORECAST_DAYS
            )
            indices_enabled = user_input.get(CONF_INDICES_ENABLED, True)
            notify_on = bool(user_input.get(CONF_NOTIFY_ENABLED, False))
            alarm_on = bool(user_input.get(CONF_NOTIFY_ALARM, True))
            alarm_notify_in = _notify_values(user_input.get(CONF_NOTIFY_ALARM_NOTIFY))
            alarm_announce_in = user_input.get(CONF_NOTIFY_ALARM_ANNOUNCE)
            rain_on = bool(user_input.get(CONF_NOTIFY_RAIN, True))
            rain_notify_in = _notify_values(user_input.get(CONF_NOTIFY_RAIN_NOTIFY))
            rain_announce_in = user_input.get(CONF_NOTIFY_RAIN_ANNOUNCE)
            if notify_on and alarm_on and not alarm_notify_in and not alarm_announce_in:
                errors[CONF_NOTIFY_ALARM_NOTIFY] = "notify_or_announce"
                errors[CONF_NOTIFY_ALARM_ANNOUNCE] = "notify_or_announce"
            if notify_on and rain_on and not rain_notify_in and not rain_announce_in:
                errors[CONF_NOTIFY_RAIN_NOTIFY] = "notify_or_announce"
                errors[CONF_NOTIFY_RAIN_ANNOUNCE] = "notify_or_announce"
            if provider in (PROVIDER_QWEATHER, PROVIDER_CAIYUN) and not api_key:
                errors["api_key"] = "api_key_required"
                candidates: list[dict[str, str]] = []
            else:
                same_name = city_query == (base.get(CONF_NAME) or "")
                same_provider = provider == (base.get(CONF_PROVIDER) or PROVIDER_TIANQI)
                if editing and same_name and same_provider and not user_input.get("_picked"):
                    candidates = [
                        {
                            "area_id": str(base.get(CONF_LOCATION) or ""),
                            "name": str(base.get(CONF_NAME) or city_query),
                            "location": str(base.get(CONF_LOCATION) or ""),
                            "lon": str(base.get("lon") or ""),
                            "lat": str(base.get("lat") or ""),
                        }
                    ]
                else:
                    candidates = await async_search_cities(
                        self.hass,
                        city_query,
                        provider=provider,
                        api_key=api_key,
                        api_host=api_host,
                    )
            if not errors and not candidates:
                errors["city"] = "city_not_found"
            elif not errors:
                chosen = candidates[0]
                area_id = user_input.get("area_id")
                if area_id:
                    match = next(
                        (c for c in candidates if c.get("area_id") == area_id),
                        None,
                    )
                    if match:
                        chosen = match
                elif len(candidates) > 1 and not user_input.get("_picked"):
                    self._candidates = candidates
                    self._draft = dict(user_input)
                    return await self.async_step_pick_options()

                chosen_loc = chosen.get("location") or chosen["area_id"]
                keep_slug = None
                if editing:
                    if (
                        chosen_loc == base.get(CONF_LOCATION)
                        or chosen["area_id"] == base.get(CONF_LOCATION)
                    ):
                        keep_slug = base.get(CONF_SLUG)
                inst = build_weather_instance(
                    area_id=chosen["area_id"],
                    display_name=chosen.get("name") or city_query,
                    slug=keep_slug,
                    interval=interval,
                    extra={
                        CONF_PROVIDER: provider,
                        CONF_FORECAST_DAYS: forecast_days,
                        CONF_INDICES_ENABLED: indices_enabled,
                        CONF_API_KEY: api_key,
                        CONF_API_HOST: api_host,
                        CONF_LOCATION: chosen_loc,
                        "lon": chosen.get("lon") or "",
                        "lat": chosen.get("lat") or "",
                        CONF_NOTIFY_ENABLED: notify_on,
                        CONF_NOTIFY_START: user_input.get(
                            CONF_NOTIFY_START, DEFAULT_NOTIFY_START
                        ),
                        CONF_NOTIFY_END: user_input.get(
                            CONF_NOTIFY_END, DEFAULT_NOTIFY_END
                        ),
                        CONF_NOTIFY_ALARM: alarm_on,
                        CONF_NOTIFY_ALARM_NOTIFY: alarm_notify_in,
                        CONF_NOTIFY_ALARM_ANNOUNCE: alarm_announce_in,
                        CONF_NOTIFY_RAIN: rain_on,
                        CONF_NOTIFY_RAIN_NOTIFY: rain_notify_in,
                        CONF_NOTIFY_RAIN_ANNOUNCE: rain_announce_in,
                    },
                )
                skip = self._edit_index if editing else None
                inst[CONF_SLUG] = _unique_slug(
                    inst.get(CONF_SLUG) or "city", instances, skip=skip
                )
                if editing and self._edit_index is not None:
                    instances[self._edit_index] = inst
                else:
                    instances.append(inst)
                self._options[CONF_INSTANCES] = instances
                self._edit_index = None
                self._mode = "add"
                self._candidates = []
                self._draft = {}
                return self._save()

        def _shown(key: str, default: Any) -> Any:
            if user_input is not None and key in user_input:
                return user_input[key]
            return base.get(key, default)

        schema = vol.Schema(
            {
                vol.Required(
                    "city", default=_shown(CONF_NAME, "杭州") if user_input is None else _shown("city", "杭州")
                ): TextSelector(),
                vol.Required(
                    CONF_PROVIDER, default=_shown(CONF_PROVIDER, PROVIDER_TIANQI)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[PROVIDER_TIANQI, PROVIDER_QWEATHER, PROVIDER_CAIYUN],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="weather_provider",
                    )
                ),
                vol.Required(
                    CONF_INTERVAL,
                    default=_shown(CONF_INTERVAL, DEFAULT_WEATHER_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=180, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_FORECAST_DAYS,
                    default=_shown(CONF_FORECAST_DAYS, DEFAULT_FORECAST_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=15, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_INDICES_ENABLED,
                    default=_shown(CONF_INDICES_ENABLED, True),
                ): BooleanSelector(),
                vol.Optional(
                    CONF_API_KEY, default=_shown(CONF_API_KEY, "") or ""
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                vol.Optional(
                    CONF_API_HOST, default=_shown(CONF_API_HOST, "") or ""
                ): TextSelector(),
                vol.Required(
                    CONF_NOTIFY_ENABLED, default=_shown(CONF_NOTIFY_ENABLED, False)
                ): BooleanSelector(),
                vol.Required(
                    CONF_NOTIFY_START,
                    default=_shown(CONF_NOTIFY_START, DEFAULT_NOTIFY_START),
                ): TimeSelector(),
                vol.Required(
                    CONF_NOTIFY_END,
                    default=_shown(CONF_NOTIFY_END, DEFAULT_NOTIFY_END),
                ): TimeSelector(),
                vol.Required(
                    CONF_NOTIFY_ALARM, default=_shown(CONF_NOTIFY_ALARM, True)
                ): BooleanSelector(),
                **_channel_fields(
                    self.hass,
                    CONF_NOTIFY_ALARM_NOTIFY,
                    _shown(CONF_NOTIFY_ALARM_NOTIFY, []),
                    CONF_NOTIFY_ALARM_ANNOUNCE,
                    _shown(CONF_NOTIFY_ALARM_ANNOUNCE, None),
                ),
                vol.Required(
                    CONF_NOTIFY_RAIN, default=_shown(CONF_NOTIFY_RAIN, True)
                ): BooleanSelector(),
                **_channel_fields(
                    self.hass,
                    CONF_NOTIFY_RAIN_NOTIFY,
                    _shown(CONF_NOTIFY_RAIN_NOTIFY, []),
                    CONF_NOTIFY_RAIN_ANNOUNCE,
                    _shown(CONF_NOTIFY_RAIN_ANNOUNCE, None),
                ),
            }
        )
        return self.async_show_form(
            step_id="city_form", data_schema=schema, errors=errors
        )

    async def async_step_pick_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        candidates = self._candidates or []
        draft = self._draft or {}
        if not candidates:
            return await self.async_step_city_form()
        options = [
            {"value": c["area_id"], "label": pick_label(c)} for c in candidates
        ]
        if user_input is not None:
            draft["area_id"] = user_input.get("area_id")
            draft["_picked"] = True
            return await self.async_step_city_form(draft)
        schema = vol.Schema(
            {
                vol.Required("area_id", default=options[0]["value"]): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                )
            }
        )
        return self.async_show_form(step_id="pick_options", data_schema=schema)
