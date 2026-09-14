from __future__ import annotations

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
    TimeSelector,
)

from .const import (
    CONF_BILLING_MODE,
    CONF_DAILY_COST_THRESHOLD,
    CONF_DAILY_EXTRA_MAX,
    CONF_DAILY_EXTRA_MIN,
    CONF_DAILY_RESET,
    CONF_ENERGY_NOTIFY,
    CONF_ENERGY_SENSOR,
    CONF_FLAT_RATE_1,
    CONF_FLAT_RATE_2,
    CONF_FLAT_RATE_3,
    CONF_INIT_MONTHLY_PEAK,
    CONF_INIT_MONTHLY_PEAK_COST,
    CONF_INIT_MONTHLY_VALLEY,
    CONF_INIT_MONTHLY_VALLEY_COST,
    CONF_INIT_YEARLY_PEAK,
    CONF_INIT_YEARLY_PEAK_COST,
    CONF_INIT_YEARLY_VALLEY,
    CONF_INIT_YEARLY_VALLEY_COST,
    CONF_MONTHLY_RESET_DAY,
    CONF_NOTIFY,
    CONF_PEAK_END,
    CONF_PEAK_RATE_1,
    CONF_PEAK_RATE_2,
    CONF_PEAK_RATE_3,
    CONF_PEAK_START,
    CONF_TIER1,
    CONF_TIER2,
    CONF_VALLEY_RATE_1,
    CONF_VALLEY_RATE_2,
    CONF_VALLEY_RATE_3,
    DEFAULT_BILLING_MODE,
    DEFAULT_DAILY_COST_THRESHOLD,
    DEFAULT_DAILY_EXTRA_MAX,
    DEFAULT_DAILY_EXTRA_MIN,
    DEFAULT_DAILY_RESET,
    DEFAULT_ENERGY_NOTIFY,
    DEFAULT_FLAT_RATE_1,
    DEFAULT_FLAT_RATE_2,
    DEFAULT_FLAT_RATE_3,
    DEFAULT_MONTHLY_RESET_DAY,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_RATE_1,
    DEFAULT_PEAK_RATE_2,
    DEFAULT_PEAK_RATE_3,
    DEFAULT_PEAK_START,
    DEFAULT_TIER1,
    DEFAULT_TIER2,
    DEFAULT_VALLEY_RATE_1,
    DEFAULT_VALLEY_RATE_2,
    DEFAULT_VALLEY_RATE_3,
    DOMAIN,
    MODE_FLAT,
    MODE_TOU,
)


def _get(src: dict, key: str, default: Any) -> Any:
    if key in src and src[key] not in (None, ""):
        return src[key]
    return default


def _kwh() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=100000,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="kWh",
        )
    )


def _rate() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=10,
            step="any",
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="¥/kWh",
        )
    )


def _cost() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=100000,
            step=0.01,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="¥",
        )
    )


def _extra_kwh() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=100,
            step=0.01,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="kWh",
        )
    )


_USER_DEFAULTS = {
    CONF_PEAK_START: DEFAULT_PEAK_START,
    CONF_PEAK_END: DEFAULT_PEAK_END,
    CONF_DAILY_RESET: DEFAULT_DAILY_RESET,
    CONF_DAILY_EXTRA_MIN: DEFAULT_DAILY_EXTRA_MIN,
    CONF_DAILY_EXTRA_MAX: DEFAULT_DAILY_EXTRA_MAX,
    CONF_MONTHLY_RESET_DAY: DEFAULT_MONTHLY_RESET_DAY,
}

_RATE_DEFAULTS = {
    CONF_BILLING_MODE: DEFAULT_BILLING_MODE,
    CONF_TIER1: DEFAULT_TIER1,
    CONF_TIER2: DEFAULT_TIER2,
    CONF_PEAK_RATE_1: DEFAULT_PEAK_RATE_1,
    CONF_PEAK_RATE_2: DEFAULT_PEAK_RATE_2,
    CONF_PEAK_RATE_3: DEFAULT_PEAK_RATE_3,
    CONF_VALLEY_RATE_1: DEFAULT_VALLEY_RATE_1,
    CONF_VALLEY_RATE_2: DEFAULT_VALLEY_RATE_2,
    CONF_VALLEY_RATE_3: DEFAULT_VALLEY_RATE_3,
    CONF_FLAT_RATE_1: DEFAULT_FLAT_RATE_1,
    CONF_FLAT_RATE_2: DEFAULT_FLAT_RATE_2,
    CONF_FLAT_RATE_3: DEFAULT_FLAT_RATE_3,
}

_NOTIFY_DEFAULTS = {
    CONF_ENERGY_NOTIFY: DEFAULT_ENERGY_NOTIFY,
    CONF_DAILY_COST_THRESHOLD: DEFAULT_DAILY_COST_THRESHOLD,
}

_INIT_KEYS = (
    CONF_INIT_MONTHLY_PEAK,
    CONF_INIT_MONTHLY_VALLEY,
    CONF_INIT_MONTHLY_PEAK_COST,
    CONF_INIT_MONTHLY_VALLEY_COST,
    CONF_INIT_YEARLY_PEAK,
    CONF_INIT_YEARLY_VALLEY,
    CONF_INIT_YEARLY_PEAK_COST,
    CONF_INIT_YEARLY_VALLEY_COST,
)


def _user_schema() -> dict[Any, Any]:
    return {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_ENERGY_SENSOR): EntitySelector(
            EntitySelectorConfig(domain="sensor", device_class=["energy"])
        ),
        vol.Required(CONF_PEAK_START): TimeSelector(),
        vol.Required(CONF_PEAK_END): TimeSelector(),
        vol.Required(CONF_DAILY_RESET): TimeSelector(),
        vol.Required(CONF_DAILY_EXTRA_MIN, default=DEFAULT_DAILY_EXTRA_MIN): _extra_kwh(),
        vol.Required(CONF_DAILY_EXTRA_MAX, default=DEFAULT_DAILY_EXTRA_MAX): _extra_kwh(),
        vol.Required(CONF_MONTHLY_RESET_DAY): NumberSelector(
            NumberSelectorConfig(min=1, max=28, step=1, mode=NumberSelectorMode.BOX)
        ),
    }


def _billing_mode_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[MODE_TOU, MODE_FLAT],
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="billing_mode",
        )
    )


def _mode_schema() -> dict[Any, Any]:
    return {
        vol.Required(CONF_BILLING_MODE, default=DEFAULT_BILLING_MODE): _billing_mode_selector()
    }


def _tou_rate_fields() -> dict[Any, Any]:
    return {
        vol.Required(CONF_PEAK_RATE_1): _rate(),
        vol.Required(CONF_PEAK_RATE_2): _rate(),
        vol.Required(CONF_PEAK_RATE_3): _rate(),
        vol.Required(CONF_VALLEY_RATE_1): _rate(),
        vol.Required(CONF_VALLEY_RATE_2): _rate(),
        vol.Required(CONF_VALLEY_RATE_3): _rate(),
    }


def _flat_rate_fields() -> dict[Any, Any]:
    return {
        vol.Required(CONF_FLAT_RATE_1): _rate(),
        vol.Required(CONF_FLAT_RATE_2): _rate(),
        vol.Required(CONF_FLAT_RATE_3): _rate(),
    }


def _rates_schema(mode: str) -> dict[Any, Any]:
    schema: dict[Any, Any] = {
        vol.Required(CONF_TIER1): _kwh(),
        vol.Required(CONF_TIER2): _kwh(),
    }
    if mode == MODE_FLAT:
        schema.update(_flat_rate_fields())
    else:
        schema.update(_tou_rate_fields())
    return schema


def _all_rates_schema() -> dict[Any, Any]:
    schema: dict[Any, Any] = {
        vol.Required(CONF_BILLING_MODE, default=DEFAULT_BILLING_MODE): _billing_mode_selector(),
        vol.Required(CONF_TIER1): _kwh(),
        vol.Required(CONF_TIER2): _kwh(),
    }
    schema.update(_tou_rate_fields())
    schema.update(_flat_rate_fields())
    return schema


def _init_schema() -> dict[Any, Any]:
    energy = NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=100000,
            step=0.001,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="kWh",
        )
    )
    return {
        vol.Required(CONF_INIT_MONTHLY_PEAK, default=0): energy,
        vol.Required(CONF_INIT_MONTHLY_VALLEY, default=0): energy,
        vol.Required(CONF_INIT_MONTHLY_PEAK_COST, default=0): _cost(),
        vol.Required(CONF_INIT_MONTHLY_VALLEY_COST, default=0): _cost(),
        vol.Required(CONF_INIT_YEARLY_PEAK, default=0): energy,
        vol.Required(CONF_INIT_YEARLY_VALLEY, default=0): energy,
        vol.Required(CONF_INIT_YEARLY_PEAK_COST, default=0): _cost(),
        vol.Required(CONF_INIT_YEARLY_VALLEY_COST, default=0): _cost(),
    }


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


def _notify_schema(
    defaults: dict[str, Any], hass: HomeAssistant | None = None
) -> dict[Any, Any]:
    current_notify = _get(defaults, CONF_NOTIFY, None)
    schema: dict[Any, Any] = {
        vol.Required(
            CONF_ENERGY_NOTIFY,
            default=_get(defaults, CONF_ENERGY_NOTIFY, DEFAULT_ENERGY_NOTIFY),
        ): BooleanSelector(),
        vol.Required(
            CONF_DAILY_COST_THRESHOLD,
            default=_get(
                defaults, CONF_DAILY_COST_THRESHOLD, DEFAULT_DAILY_COST_THRESHOLD
            ),
        ): _cost(),
    }
    opts = _notify_options(hass, current_notify)
    if current_notify:
        schema[vol.Optional(CONF_NOTIFY, default=_notify_values(current_notify))] = (
            SelectSelector(
                SelectSelectorConfig(
                    options=opts,
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
        )
    else:
        schema[vol.Optional(CONF_NOTIFY)] = SelectSelector(
            SelectSelectorConfig(
                options=opts,
                multiple=True,
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    return schema


class EnergyStatsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] = {}
        self._mode: dict[str, Any] = {}
        self._rates: dict[str, Any] = {}
        self._notify: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_user_schema()), _USER_DEFAULTS
                ),
            )
        await self.async_set_unique_id(user_input[CONF_ENERGY_SENSOR])
        self._abort_if_unique_id_configured()
        self._user_input = user_input
        return await self.async_step_mode()

    async def async_step_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="mode",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_mode_schema()),
                    {CONF_BILLING_MODE: DEFAULT_BILLING_MODE},
                ),
            )
        self._mode = user_input
        return await self.async_step_rates()

    async def async_step_rates(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        mode = self._mode.get(CONF_BILLING_MODE, DEFAULT_BILLING_MODE)
        if user_input is None:
            return self.async_show_form(
                step_id="rates",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_rates_schema(mode)), _RATE_DEFAULTS
                ),
            )
        self._rates = user_input
        return await self.async_step_notify()

    async def async_step_notify(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="notify",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_notify_schema({}, self.hass)), _NOTIFY_DEFAULTS
                ),
            )
        self._notify = user_input
        return await self.async_step_init_values()

    async def async_step_init_values(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="init_values",
                data_schema=vol.Schema(_init_schema()),
            )
        data = {
            CONF_NAME: self._user_input[CONF_NAME],
            CONF_ENERGY_SENSOR: self._user_input[CONF_ENERGY_SENSOR],
            **{k: float(user_input.get(k, 0) or 0) for k in _INIT_KEYS},
        }
        options = {
            CONF_PEAK_START: self._user_input[CONF_PEAK_START],
            CONF_PEAK_END: self._user_input[CONF_PEAK_END],
            CONF_DAILY_RESET: self._user_input[CONF_DAILY_RESET],
            CONF_DAILY_EXTRA_MIN: self._user_input[CONF_DAILY_EXTRA_MIN],
            CONF_DAILY_EXTRA_MAX: self._user_input[CONF_DAILY_EXTRA_MAX],
            CONF_MONTHLY_RESET_DAY: self._user_input[CONF_MONTHLY_RESET_DAY],
            **_RATE_DEFAULTS,
            **self._mode,
            **self._rates,
            **self._notify,
        }
        return self.async_create_entry(
            title=self._user_input[CONF_NAME],
            data=data,
            options=options,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EnergyStatsOptionsFlow()


class EnergyStatsOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )
        entry = self.config_entry
        current = {**entry.data, **entry.options}
        suggested = {
            CONF_ENERGY_SENSOR: _get(current, CONF_ENERGY_SENSOR, None),
            **{k: _get(current, k, d) for k, d in _USER_DEFAULTS.items()},
            **{k: _get(current, k, d) for k, d in _RATE_DEFAULTS.items()},
            CONF_ENERGY_NOTIFY: _get(
                current, CONF_ENERGY_NOTIFY, DEFAULT_ENERGY_NOTIFY
            ),
            CONF_DAILY_COST_THRESHOLD: _get(
                current, CONF_DAILY_COST_THRESHOLD, DEFAULT_DAILY_COST_THRESHOLD
            ),
        }
        notify = _get(current, CONF_NOTIFY, None)
        if notify:
            suggested[CONF_NOTIFY] = _notify_values(notify)
        schema = {
            vol.Required(CONF_ENERGY_SENSOR): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class=["energy"])
            ),
            vol.Required(CONF_PEAK_START): TimeSelector(),
            vol.Required(CONF_PEAK_END): TimeSelector(),
            vol.Required(CONF_DAILY_RESET): TimeSelector(),
            vol.Required(CONF_DAILY_EXTRA_MIN, default=DEFAULT_DAILY_EXTRA_MIN): _extra_kwh(),
            vol.Required(CONF_DAILY_EXTRA_MAX, default=DEFAULT_DAILY_EXTRA_MAX): _extra_kwh(),
            vol.Required(CONF_MONTHLY_RESET_DAY): NumberSelector(
                NumberSelectorConfig(min=1, max=28, step=1, mode=NumberSelectorMode.BOX)
            ),
        }
        schema.update(_all_rates_schema())
        schema.update(_notify_schema(current, self.hass))
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(schema), suggested),
        )
