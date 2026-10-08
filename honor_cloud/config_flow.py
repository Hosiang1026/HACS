from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers import selector

from .backend_check import verify_backend_credentials
from .config_validation import validate_credentials
from .commute import _id_list
from .const import (
    CONF_ACTIVITY_ENTITY,
    CONF_API_KEY,
    CONF_AMAP_API_KEY,
    CONF_AMAP_DAILY_LIMIT,
    CONF_BASE_URL,
    CONF_COMMUTE_ENABLED,
    CONF_COMMUTE_ZONES,
    CONF_COMPANY_ZONES,
    CONF_ENABLE_AMAP,
    CONF_INTERVAL,
    CONF_MAX_INTERVAL,
    CONF_OFFPEAK_ENABLED,
    CONF_OFFPEAK_INTERVAL,
    CONF_OFFPEAK_WINDOWS,
    CONF_PEAK_ENABLED,
    CONF_PEAK_INTERVAL,
    CONF_PEAK_WINDOWS,
    CONF_PERIOD_WEEKDAYS,
    CONF_SESSION_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ACTIVITY_ENTITY,
    DEFAULT_AMAP_DAILY_LIMIT,
    DEFAULT_COMMUTE_ENABLED,
    DEFAULT_COMMUTE_ZONES,
    DEFAULT_COMPANY_ZONES,
    DEFAULT_ENABLE_AMAP,
    DEFAULT_MAX_INTERVAL,
    DEFAULT_OFFPEAK_ENABLED,
    DEFAULT_OFFPEAK_INTERVAL,
    DEFAULT_OFFPEAK_WINDOWS,
    DEFAULT_PEAK_ENABLED,
    DEFAULT_PEAK_INTERVAL,
    DEFAULT_PEAK_WINDOWS,
    DEFAULT_PERIOD_WEEKDAYS,
    DOMAIN,
    OFFPEAK_RANGE_COUNT,
    OPTION_KEYS,
    PEAK_RANGE_COUNT,
    TIME_CHOICES,
    TIME_NONE,
    default_locate_options,
    opt_windows_text,
    pairs_to_windows_text,
    resolve_max_interval_minutes,
    windows_text_to_pairs,
)

_LOGGER = logging.getLogger(__name__)


def _mask_username(username: str) -> str:
    if not username or len(username) <= 3:
        return "***"
    return username[:3] + "*" * (len(username) - 3)


def _select_field(name: str, current: str) -> dict[str, Any]:
    current = current or TIME_NONE
    values = list(TIME_CHOICES)
    if current not in values and current != TIME_NONE:
        values = [current] + values
    return {
        "name": name,
        "required": True,
        "default": current,
        "selector": {
            "select": {
                "options": [{"value": TIME_NONE, "label": "—"}]
                + [{"value": value, "label": value} for value in values],
                "mode": "dropdown",
                "multiple": False,
            }
        },
    }


class _TimeRangeGrid(selector.Selector):
    selector_type = "text"
    CONFIG_SCHEMA = vol.Schema({})

    def __init__(self, start_name: str, end_name: str, start: str, end: str) -> None:
        self.config: dict[str, Any] = {}
        self._start_name = start_name
        self._end_name = end_name
        self._start = start or TIME_NONE
        self._end = end or TIME_NONE

    def __call__(self, data: Any) -> Any:
        return data

    def serialize(self) -> dict[str, Any]:
        return {
            "type": "grid",
            "flatten": True,
            "column_min_width": "130px",
            "schema": [
                _select_field(self._start_name, self._start),
                _select_field(self._end_name, self._end),
            ],
        }


class _ValueHold(selector.Selector):
    selector_type = "text"
    CONFIG_SCHEMA = vol.Schema({})

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}

    def __call__(self, data: Any) -> Any:
        return data

    def serialize(self) -> dict[str, Any]:
        return {"type": "grid", "flatten": True, "schema": []}


def _flat_pairs(user_input: dict[str, Any], prefix: str, count: int, fallback):
    pairs = []
    for index in range(1, count + 1):
        start_key = f"{prefix}_start_{index}"
        end_key = f"{prefix}_end_{index}"
        pairs.append(
            (
                user_input.pop(start_key, fallback[index - 1][0]),
                user_input.pop(end_key, fallback[index - 1][1]),
            )
        )
    return pairs


def _store_flat_pairs(user_input: dict[str, Any], prefix: str, pairs) -> None:
    for index, (start, end) in enumerate(pairs, start=1):
        user_input[f"{prefix}_start_{index}"] = start
        user_input[f"{prefix}_end_{index}"] = end


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class HonorCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _test_credentials(
        self, base_url: str, username: str, password: str
    ) -> dict[str, str]:
        probe_key = str(uuid.uuid4())
        error = await verify_backend_credentials(
            base_url, username, password, probe_key
        )
        if error:
            return {"base": error}
        return {}

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        self._reauth_entry = entry
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._reauth_entry
        options = entry.options or {}
        base_url = entry.data.get(CONF_BASE_URL, "")
        username = options.get(CONF_USERNAME, "")
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input.get(CONF_BASE_URL, "").strip().rstrip("/")
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "").strip()
            errors = validate_credentials(base_url, username, password)
            if not errors:
                errors.update(
                    await self._test_credentials(base_url, username, password)
                )

            if errors:
                schema = self.add_suggested_values_to_schema(
                    STEP_USER_DATA_SCHEMA,
                    {
                        CONF_BASE_URL: base_url,
                        CONF_USERNAME: username,
                    },
                )
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=schema,
                    description_placeholders={"username": _mask_username(username)},
                    errors=errors,
                )

            session_key = str(uuid.uuid4())
            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    CONF_BASE_URL: base_url,
                    CONF_SESSION_KEY: session_key,
                },
                options={
                    **options,
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                },
                title=f"荣耀云服务 ({_mask_username(username)})",
                reason="reauth_successful",
            )

        schema = self.add_suggested_values_to_schema(
            STEP_USER_DATA_SCHEMA,
            {
                CONF_BASE_URL: base_url,
                CONF_USERNAME: username,
            },
        )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            description_placeholders={"username": _mask_username(username)},
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input.get(CONF_BASE_URL, "").strip().rstrip("/")
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "").strip()

            errors = validate_credentials(base_url, username, password)

            if errors:
                return self.async_show_form(
                    step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors,
                )

            unique_id = f"{base_url}|{username}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                errors.update(
                    await self._test_credentials(base_url, username, password)
                )
                if errors:
                    return self.async_show_form(
                        step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors,
                    )

                session_key = str(uuid.uuid4())

                data = {
                    CONF_BASE_URL: base_url,
                    CONF_SESSION_KEY: session_key,
                }

                options = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    **default_locate_options(),
                }

                return self.async_create_entry(
                    title=f"荣耀云服务 ({_mask_username(username)})",
                    data=data,
                    options=options,
                )
            except Exception as e:
                _LOGGER.exception(f"配置失败: {e}")
                errors["base"] = "cannot_connect"
                return self.async_show_form(
                    step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors,
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    def _opt(self, key, default, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None and key in user_input:
            return user_input[key]
        return entry.options.get(key, entry.data.get(key, default))

    def _merge_options(self, updates: dict[str, Any]) -> dict[str, Any]:
        base = {
            key: value
            for key, value in {**self.config_entry.data, **(self.config_entry.options or {})}.items()
            if key in OPTION_KEYS
        }
        for key, value in updates.items():
            if key in OPTION_KEYS:
                base[key] = value
        return base

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["locate", "amap", "account"],
        )

    async def async_step_locate(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        saved_peak = windows_text_to_pairs(
            opt_windows_text(
                entry.options.get(
                    CONF_PEAK_WINDOWS,
                    entry.data.get(CONF_PEAK_WINDOWS, DEFAULT_PEAK_WINDOWS),
                ),
                DEFAULT_PEAK_WINDOWS,
            ),
            PEAK_RANGE_COUNT,
        )
        saved_offpeak = windows_text_to_pairs(
            opt_windows_text(
                entry.options.get(
                    CONF_OFFPEAK_WINDOWS,
                    entry.data.get(CONF_OFFPEAK_WINDOWS, DEFAULT_OFFPEAK_WINDOWS),
                ),
                DEFAULT_OFFPEAK_WINDOWS,
            ),
            OFFPEAK_RANGE_COUNT,
        )

        if user_input is not None:
            user_input[CONF_PEAK_ENABLED] = bool(
                user_input.get(CONF_PEAK_ENABLED, False)
            )
            user_input[CONF_OFFPEAK_ENABLED] = bool(
                user_input.get(CONF_OFFPEAK_ENABLED, False)
            )
            user_input[CONF_PERIOD_WEEKDAYS] = bool(
                user_input.get(CONF_PERIOD_WEEKDAYS, False)
            )
            peak_pairs = _flat_pairs(user_input, "peak", PEAK_RANGE_COUNT, saved_peak)
            offpeak_pairs = _flat_pairs(
                user_input, "offpeak", OFFPEAK_RANGE_COUNT, saved_offpeak
            )
            peak_text = pairs_to_windows_text(peak_pairs)
            offpeak_text = pairs_to_windows_text(offpeak_pairs)
            if peak_text is None or (user_input[CONF_PEAK_ENABLED] and not peak_text):
                errors["peak_start_1"] = "invalid_windows"
            if offpeak_text is None or (
                user_input[CONF_OFFPEAK_ENABLED] and not offpeak_text
            ):
                errors["offpeak_start_1"] = "invalid_windows"
            if not errors:
                max_interval = int(
                    user_input.get(CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL)
                )
                user_input[CONF_PEAK_WINDOWS] = peak_text or ""
                user_input[CONF_OFFPEAK_WINDOWS] = offpeak_text or ""
                user_input[CONF_MAX_INTERVAL] = max_interval
                user_input[CONF_UPDATE_INTERVAL] = max_interval
                user_input[CONF_INTERVAL] = max_interval * 60
                user_input[CONF_PEAK_INTERVAL] = int(
                    user_input.get(CONF_PEAK_INTERVAL, DEFAULT_PEAK_INTERVAL)
                )
                user_input[CONF_OFFPEAK_INTERVAL] = int(
                    user_input.get(CONF_OFFPEAK_INTERVAL, DEFAULT_OFFPEAK_INTERVAL)
                )
                updated = self._merge_options(user_input)
                updated.pop("low_battery_threshold", None)
                updated.pop("enable_low_battery_update", None)
                updated.pop("low_battery_interval", None)
                return self.async_create_entry(title="", data=updated)
            _store_flat_pairs(user_input, "peak", peak_pairs)
            _store_flat_pairs(user_input, "offpeak", offpeak_pairs)

        peak_pairs = (
            [
                (
                    self._opt(f"peak_start_{index}", TIME_NONE, user_input),
                    self._opt(f"peak_end_{index}", TIME_NONE, user_input),
                )
                for index in range(1, PEAK_RANGE_COUNT + 1)
            ]
            if user_input is not None and "peak_start_1" in user_input
            else saved_peak
        )
        offpeak_pairs = (
            [
                (
                    self._opt(f"offpeak_start_{index}", TIME_NONE, user_input),
                    self._opt(f"offpeak_end_{index}", TIME_NONE, user_input),
                )
                for index in range(1, OFFPEAK_RANGE_COUNT + 1)
            ]
            if user_input is not None and "offpeak_start_1" in user_input
            else saved_offpeak
        )

        current_max = resolve_max_interval_minutes(entry.options or {}, entry.data)
        schema: dict[Any, Any] = {
            vol.Required(
                CONF_MAX_INTERVAL,
                default=self._opt(CONF_MAX_INTERVAL, current_max, user_input),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=180)),
            vol.Required(
                CONF_PERIOD_WEEKDAYS,
                default=self._opt(
                    CONF_PERIOD_WEEKDAYS, DEFAULT_PERIOD_WEEKDAYS, user_input
                ),
            ): bool,
            vol.Required(
                CONF_PEAK_ENABLED,
                default=self._opt(CONF_PEAK_ENABLED, DEFAULT_PEAK_ENABLED, user_input),
            ): bool,
        }
        for index, (start, end) in enumerate(peak_pairs, start=1):
            schema[
                vol.Required(f"peak_start_{index}", default=start or TIME_NONE)
            ] = _TimeRangeGrid(
                f"peak_start_{index}", f"peak_end_{index}", start, end
            )
            schema[
                vol.Required(f"peak_end_{index}", default=end or TIME_NONE)
            ] = _ValueHold()
        schema[
            vol.Required(
                CONF_PEAK_INTERVAL,
                default=self._opt(CONF_PEAK_INTERVAL, DEFAULT_PEAK_INTERVAL, user_input),
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=180))
        schema[
            vol.Required(
                CONF_OFFPEAK_ENABLED,
                default=self._opt(
                    CONF_OFFPEAK_ENABLED, DEFAULT_OFFPEAK_ENABLED, user_input
                ),
            )
        ] = bool
        for index, (start, end) in enumerate(offpeak_pairs, start=1):
            schema[
                vol.Required(f"offpeak_start_{index}", default=start or TIME_NONE)
            ] = _TimeRangeGrid(
                f"offpeak_start_{index}", f"offpeak_end_{index}", start, end
            )
            schema[
                vol.Required(f"offpeak_end_{index}", default=end or TIME_NONE)
            ] = _ValueHold()
        schema[
            vol.Required(
                CONF_OFFPEAK_INTERVAL,
                default=self._opt(
                    CONF_OFFPEAK_INTERVAL, DEFAULT_OFFPEAK_INTERVAL, user_input
                ),
            )
        ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=180))

        return self.async_show_form(
            step_id="locate",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

    async def async_step_amap(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = self.config_entry.options or {}
        errors: dict[str, str] = {}
        if user_input is not None:
            submitted = str(user_input.get(CONF_AMAP_API_KEY) or "").strip()
            saved = str(options.get(CONF_AMAP_API_KEY) or "").strip()
            user_input[CONF_ENABLE_AMAP] = bool(user_input.get(CONF_ENABLE_AMAP, False))
            user_input[CONF_COMMUTE_ENABLED] = bool(user_input.get(CONF_COMMUTE_ENABLED, False))
            if CONF_COMMUTE_ZONES in user_input:
                zones = [
                    zone
                    for zone in _id_list(user_input.get(CONF_COMMUTE_ZONES))
                    if self.hass.states.get(zone) is not None
                ]
            else:
                zones = _id_list(options.get(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES))
            user_input[CONF_COMMUTE_ZONES] = zones
            if CONF_COMPANY_ZONES in user_input:
                company = [
                    zone
                    for zone in _id_list(user_input.get(CONF_COMPANY_ZONES))
                    if self.hass.states.get(zone) is not None
                ]
            else:
                company = _id_list(options.get(CONF_COMPANY_ZONES, DEFAULT_COMPANY_ZONES))
            user_input[CONF_COMPANY_ZONES] = company
            if CONF_ACTIVITY_ENTITY in user_input:
                activity = [
                    entity_id
                    for entity_id in _id_list(user_input.get(CONF_ACTIVITY_ENTITY))
                    if self.hass.states.get(entity_id) is not None
                ]
            else:
                activity = _id_list(options.get(CONF_ACTIVITY_ENTITY, DEFAULT_ACTIVITY_ENTITY))
            user_input[CONF_ACTIVITY_ENTITY] = activity
            api_key = submitted or saved
            if user_input[CONF_COMMUTE_ENABLED]:
                if not user_input[CONF_ENABLE_AMAP]:
                    errors[CONF_ENABLE_AMAP] = "amap_required"
                if not api_key:
                    errors[CONF_AMAP_API_KEY] = "commute_key"
                if not user_input[CONF_COMMUTE_ZONES]:
                    errors[CONF_COMMUTE_ZONES] = "commute_zones"
            if not errors:
                updated = self._merge_options(user_input)
                updated[CONF_AMAP_API_KEY] = api_key
                updated[CONF_AMAP_DAILY_LIMIT] = int(
                    user_input.get(CONF_AMAP_DAILY_LIMIT, DEFAULT_AMAP_DAILY_LIMIT)
                )
                updated[CONF_ENABLE_AMAP] = user_input[CONF_ENABLE_AMAP]
                updated[CONF_COMMUTE_ENABLED] = user_input[CONF_COMMUTE_ENABLED]
                updated[CONF_COMMUTE_ZONES] = user_input[CONF_COMMUTE_ZONES]
                updated[CONF_COMPANY_ZONES] = user_input[CONF_COMPANY_ZONES]
                updated[CONF_ACTIVITY_ENTITY] = user_input[CONF_ACTIVITY_ENTITY]
                return self.async_create_entry(title="", data=updated)

        source = user_input if user_input is not None else options
        zones = _id_list(source.get(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES))
        company = _id_list(source.get(CONF_COMPANY_ZONES, DEFAULT_COMPANY_ZONES))
        activity = _id_list(source.get(CONF_ACTIVITY_ENTITY, DEFAULT_ACTIVITY_ENTITY))
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_AMAP_API_KEY,
                    default=source.get(CONF_AMAP_API_KEY, options.get(CONF_AMAP_API_KEY, "")),
                ): str,
                vol.Optional(
                    CONF_AMAP_DAILY_LIMIT,
                    default=source.get(
                        CONF_AMAP_DAILY_LIMIT,
                        options.get(CONF_AMAP_DAILY_LIMIT, DEFAULT_AMAP_DAILY_LIMIT),
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=100000)),
                vol.Optional(
                    CONF_ENABLE_AMAP,
                    default=source.get(CONF_ENABLE_AMAP, options.get(CONF_ENABLE_AMAP, DEFAULT_ENABLE_AMAP)),
                ): bool,
                vol.Optional(
                    CONF_COMMUTE_ENABLED,
                    default=source.get(
                        CONF_COMMUTE_ENABLED,
                        options.get(CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED),
                    ),
                ): bool,
                vol.Optional(CONF_COMMUTE_ZONES, default=zones): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="zone", multiple=True)
                ),
                vol.Optional(CONF_COMPANY_ZONES, default=company): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="zone", multiple=True)
                ),
                vol.Optional(CONF_ACTIVITY_ENTITY, default=activity): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="amap", data_schema=schema, errors=errors)

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = self.config_entry.options or {}
        current_base = self.config_entry.data.get(CONF_BASE_URL, "")
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input.pop(CONF_BASE_URL, "").strip().rstrip("/")
            user_input[CONF_API_KEY] = str(user_input.get(CONF_API_KEY) or "").strip()
            if not base_url:
                errors["base"] = "base_url_required"
            elif not base_url.startswith(("http://", "https://")):
                errors["base"] = "invalid_url"

            if errors:
                user_input[CONF_BASE_URL] = base_url
            else:
                if base_url != current_base:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, CONF_BASE_URL: base_url},
                    )
                return self.async_create_entry(title="", data=self._merge_options(user_input))

        defaults = user_input or {}
        schema = self.add_suggested_values_to_schema(
            vol.Schema(
                {
                    vol.Required(
                        CONF_BASE_URL,
                        default=defaults.get(CONF_BASE_URL, current_base),
                    ): str,
                    vol.Required(
                        CONF_USERNAME,
                        default=defaults.get(CONF_USERNAME, options.get(CONF_USERNAME, "")),
                    ): str,
                    vol.Required(
                        CONF_PASSWORD,
                        default=defaults.get(CONF_PASSWORD, options.get(CONF_PASSWORD, "")),
                    ): str,
                    vol.Optional(CONF_API_KEY): str,
                }
            ),
            {
                CONF_API_KEY: defaults.get(CONF_API_KEY, options.get(CONF_API_KEY, ""))
                if user_input is not None
                else options.get(CONF_API_KEY, ""),
            },
        )
        return self.async_show_form(step_id="account", data_schema=schema, errors=errors)
