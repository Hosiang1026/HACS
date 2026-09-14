from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util

from .const import (
    CODE_TO_NAME,
    CONF_FILL_LITERS,
    CONF_NOTIFY,
    CONF_NOTIFY_DAILY,
    CONF_NOTIFY_ENABLE,
    CONF_NOTIFY_LOW,
    CONF_NOTIFY_WEEKEND,
    CONF_PROVINCE_CODE,
    CONF_PROVINCE_NAME,
    CONF_PROVINCES,
    DEFAULT_FILL_LITERS,
    DEFAULT_NAME,
    DEFAULT_NOTIFY_DAILY,
    DEFAULT_NOTIFY_ENABLE,
    DEFAULT_NOTIFY_LOW,
    DEFAULT_NOTIFY_WEEKEND,
    DOMAIN,
    PROVINCE_OPTIONS,
    normalize_fill_liters,
)
from .localize import tr


def _province_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=PROVINCE_OPTIONS,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


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


def _notify_selector(hass: HomeAssistant | None, current: Any = None) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=_notify_options(hass, current),
            multiple=True,
            custom_value=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _normalize_province(
    code: str,
    notify_low: bool = DEFAULT_NOTIFY_LOW,
    notify: Any = None,
) -> dict[str, Any]:
    return {
        CONF_PROVINCE_CODE: code,
        CONF_PROVINCE_NAME: CODE_TO_NAME.get(code, code),
        CONF_NOTIFY_LOW: bool(notify_low),
        CONF_NOTIFY: _notify_values(notify),
    }


def _province_form(
    hass: HomeAssistant | None = None,
    *,
    code_default: str | None = None,
    notify_low_default: bool = DEFAULT_NOTIFY_LOW,
    notify_default: Any = None,
) -> vol.Schema:
    code_field = (
        vol.Required(CONF_PROVINCE_CODE, default=code_default)
        if code_default
        else vol.Required(CONF_PROVINCE_CODE)
    )
    notify_default = _notify_values(notify_default)
    return vol.Schema(
        {
            code_field: _province_selector(),
            vol.Required(
                CONF_NOTIFY_LOW, default=bool(notify_low_default)
            ): BooleanSelector(),
            vol.Optional(
                CONF_NOTIFY, default=notify_default
            ): _notify_selector(hass, notify_default),
        }
    )


def _edit_province_form(
    hass: HomeAssistant | None = None,
    *,
    code: str,
    notify_low_default: bool = DEFAULT_NOTIFY_LOW,
    notify_default: Any = None,
) -> vol.Schema:
    notify_default = _notify_values(notify_default)
    return vol.Schema(
        {
            vol.Required(CONF_PROVINCE_CODE, default=code): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {
                            "value": code,
                            "label": CODE_TO_NAME.get(code, code),
                        }
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_NOTIFY_LOW, default=bool(notify_low_default)
            ): BooleanSelector(),
            vol.Optional(
                CONF_NOTIFY, default=notify_default
            ): _notify_selector(hass, notify_default),
        }
    )


def _province_menu_options(provinces: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "value": p[CONF_PROVINCE_CODE],
            "label": p.get(CONF_PROVINCE_NAME)
            or CODE_TO_NAME.get(p[CONF_PROVINCE_CODE], p[CONF_PROVINCE_CODE]),
        }
        for p in provinces
        if p.get(CONF_PROVINCE_CODE)
    ]


def _fill_liters_field() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=0, max=200, step=0.1, mode=NumberSelectorMode.BOX)
    )


def _default_notify_options(options: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_FILL_LITERS: normalize_fill_liters(
            options.get(CONF_FILL_LITERS, DEFAULT_FILL_LITERS)
        ),
        CONF_NOTIFY_ENABLE: bool(
            options.get(CONF_NOTIFY_ENABLE, DEFAULT_NOTIFY_ENABLE)
        ),
        CONF_NOTIFY_DAILY: bool(options.get(CONF_NOTIFY_DAILY, DEFAULT_NOTIFY_DAILY)),
        CONF_NOTIFY_WEEKEND: bool(
            options.get(CONF_NOTIFY_WEEKEND, DEFAULT_NOTIFY_WEEKEND)
        ),
        CONF_NOTIFY: _notify_values(options.get(CONF_NOTIFY)),
    }


class FuelPriceConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._name: str = DEFAULT_NAME
        self._provinces: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        default_name = tr(self.hass, "default_name") if self.hass else DEFAULT_NAME
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_NAME, default=default_name): str,
                    }
                ),
            )
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._name = user_input[CONF_NAME]
        return await self.async_step_province()

    async def async_step_province(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="province",
                data_schema=_province_form(self.hass),
            )
        code = user_input[CONF_PROVINCE_CODE]
        notify_low = bool(user_input.get(CONF_NOTIFY_LOW, DEFAULT_NOTIFY_LOW))
        notify = _notify_values(user_input.get(CONF_NOTIFY))
        if any(p.get(CONF_PROVINCE_CODE) == code for p in self._provinces):
            errors["base"] = "already_province"
            return self.async_show_form(
                step_id="province",
                data_schema=_province_form(
                    self.hass,
                    notify_low_default=notify_low,
                    notify_default=notify,
                ),
                errors=errors,
            )
        self._provinces.append(_normalize_province(code, notify_low, notify))
        return self.async_create_entry(
            title=self._name,
            data={
                CONF_NAME: self._name,
                "created_at": dt_util.utcnow().isoformat(),
            },
            options={
                CONF_FILL_LITERS: DEFAULT_FILL_LITERS,
                CONF_NOTIFY_ENABLE: DEFAULT_NOTIFY_ENABLE,
                CONF_NOTIFY_DAILY: DEFAULT_NOTIFY_DAILY,
                CONF_NOTIFY_WEEKEND: DEFAULT_NOTIFY_WEEKEND,
                CONF_NOTIFY: [],
                CONF_PROVINCES: self._provinces,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FuelPriceOptionsFlow()


class FuelPriceOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._edit_id: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "global",
                "add_province",
                "edit_province",
                "remove_province",
            ],
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = _default_notify_options(dict(self.config_entry.options))
        if user_input is not None:
            options = {**self.config_entry.options}
            options.pop("scan_interval", None)
            options[CONF_FILL_LITERS] = normalize_fill_liters(
                user_input.get(CONF_FILL_LITERS, DEFAULT_FILL_LITERS)
            )
            options[CONF_NOTIFY_ENABLE] = bool(user_input.get(CONF_NOTIFY_ENABLE))
            options[CONF_NOTIFY_DAILY] = bool(user_input.get(CONF_NOTIFY_DAILY))
            options[CONF_NOTIFY_WEEKEND] = bool(user_input.get(CONF_NOTIFY_WEEKEND))
            options[CONF_NOTIFY] = _notify_values(user_input.get(CONF_NOTIFY))
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="global",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FILL_LITERS, default=current[CONF_FILL_LITERS]
                    ): _fill_liters_field(),
                    vol.Required(
                        CONF_NOTIFY_ENABLE, default=current[CONF_NOTIFY_ENABLE]
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_NOTIFY_DAILY, default=current[CONF_NOTIFY_DAILY]
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_NOTIFY_WEEKEND, default=current[CONF_NOTIFY_WEEKEND]
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_NOTIFY, default=current[CONF_NOTIFY]
                    ): _notify_selector(self.hass, current[CONF_NOTIFY]),
                }
            ),
        )

    async def async_step_add_province(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="add_province",
                data_schema=_province_form(self.hass),
            )
        code = user_input[CONF_PROVINCE_CODE]
        notify_low = bool(user_input.get(CONF_NOTIFY_LOW, DEFAULT_NOTIFY_LOW))
        notify = _notify_values(user_input.get(CONF_NOTIFY))
        provinces = list(self.config_entry.options.get(CONF_PROVINCES) or [])
        if any(p.get(CONF_PROVINCE_CODE) == code for p in provinces):
            errors["base"] = "already_province"
            return self.async_show_form(
                step_id="add_province",
                data_schema=_province_form(
                    self.hass,
                    notify_low_default=notify_low,
                    notify_default=notify,
                ),
                errors=errors,
            )
        provinces.append(_normalize_province(code, notify_low, notify))
        options = {**self.config_entry.options, CONF_PROVINCES: provinces}
        return self.async_create_entry(title="", data=options)

    async def async_step_edit_province(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        provinces = list(self.config_entry.options.get(CONF_PROVINCES) or [])
        if not provinces:
            return self.async_abort(reason="no_provinces")
        if user_input is None:
            return self.async_show_form(
                step_id="edit_province",
                data_schema=vol.Schema(
                    {
                        vol.Required("province"): SelectSelector(
                            SelectSelectorConfig(
                                options=_province_menu_options(provinces),
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        )
                    }
                ),
            )
        if CONF_PROVINCE_CODE in user_input or CONF_NOTIFY_LOW in user_input:
            notify_low = bool(user_input.get(CONF_NOTIFY_LOW, DEFAULT_NOTIFY_LOW))
            notify = _notify_values(user_input.get(CONF_NOTIFY))
            edit_id = self._edit_id
            provinces = [
                _normalize_province(edit_id, notify_low, notify)
                if p.get(CONF_PROVINCE_CODE) == edit_id
                else p
                for p in provinces
            ]
            options = {**self.config_entry.options, CONF_PROVINCES: provinces}
            return self.async_create_entry(title="", data=options)
        self._edit_id = user_input["province"]
        current = next(
            (p for p in provinces if p.get(CONF_PROVINCE_CODE) == self._edit_id),
            {},
        )
        return self.async_show_form(
            step_id="edit_form",
            data_schema=_edit_province_form(
                self.hass,
                code=self._edit_id,
                notify_low_default=bool(
                    current.get(CONF_NOTIFY_LOW, DEFAULT_NOTIFY_LOW)
                ),
                notify_default=current.get(CONF_NOTIFY),
            ),
        )

    async def async_step_edit_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        provinces = list(self.config_entry.options.get(CONF_PROVINCES) or [])
        current = next(
            (p for p in provinces if p.get(CONF_PROVINCE_CODE) == self._edit_id),
            {},
        )
        if user_input is None:
            return self.async_show_form(
                step_id="edit_form",
                data_schema=_edit_province_form(
                    self.hass,
                    code=self._edit_id or "",
                    notify_low_default=bool(
                        current.get(CONF_NOTIFY_LOW, DEFAULT_NOTIFY_LOW)
                    ),
                    notify_default=current.get(CONF_NOTIFY),
                ),
            )
        return await self.async_step_edit_province(user_input)

    async def async_step_remove_province(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        provinces = list(self.config_entry.options.get(CONF_PROVINCES) or [])
        if not provinces:
            return self.async_abort(reason="no_provinces")
        if user_input is not None:
            code = user_input["province"]
            provinces = [p for p in provinces if p.get(CONF_PROVINCE_CODE) != code]
            options = deepcopy(dict(self.config_entry.options))
            options[CONF_PROVINCES] = provinces
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="remove_province",
            data_schema=vol.Schema(
                {
                    vol.Required("province"): SelectSelector(
                        SelectSelectorConfig(
                            options=_province_menu_options(provinces),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )
