"""Config flow for ha_xiaomi_cloud."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .DataUpdateCoordinator import (
    LOGIN_FAIL,
    LOGIN_INVALID,
    LOGIN_NEED_VERIFY,
    LOGIN_OK,
    XiaomiCloudDataUpdateCoordinator,
)
from .const import (
    CONF_ACTIVITY_ENTITY,
    CONF_AMAP_ENABLED,
    CONF_AMAP_KEY,
    CONF_COMMUTE_ENABLED,
    CONF_COMMUTE_ZONES,
    CONF_COMPANY_ZONES,
    CONF_MAX_INTERVAL,
    CONF_OFFPEAK_ENABLED,
    CONF_OFFPEAK_INTERVAL,
    CONF_OFFPEAK_WINDOWS,
    CONF_PASS_TOKEN,
    CONF_PEAK_ENABLED,
    CONF_PEAK_INTERVAL,
    CONF_PEAK_WINDOWS,
    CONF_PERIOD_WEEKDAYS,
    CONF_UPDATE_INTERVAL,
    CONF_USER_ID,
    CONF_DEVICE_ID,
    CONF_VERIFY_CODE,
    DEFAULT_ACTIVITY_ENTITY,
    DEFAULT_AMAP_ENABLED,
    DEFAULT_COMMUTE_ENABLED,
    DEFAULT_COMMUTE_ZONES,
    DEFAULT_COMPANY_ZONES,
    DEFAULT_MAX_INTERVAL,
    DEFAULT_OFFPEAK_ENABLED,
    DEFAULT_OFFPEAK_INTERVAL,
    DEFAULT_OFFPEAK_WINDOWS,
    DEFAULT_PEAK_ENABLED,
    DEFAULT_PEAK_INTERVAL,
    DEFAULT_PEAK_WINDOWS,
    DEFAULT_PERIOD_WEEKDAYS,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    OFFPEAK_RANGE_COUNT,
    OPTION_KEYS,
    PEAK_RANGE_COUNT,
    TIME_CHOICES,
    TIME_NONE,
    activity_entities,
    default_options,
    opt_windows_text,
    pairs_to_windows_text,
    windows_text_to_pairs,
)

_LOGGER = logging.getLogger(__name__)

_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


class XiaomiCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._username: str | None = None
        self._password: str | None = None
        self._coordinator: XiaomiCloudDataUpdateCoordinator | None = None
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _close_session(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    def _entry_data(self) -> dict[str, Any]:
        tokens = self._coordinator.export_tokens() if self._coordinator else {}
        return {
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
            CONF_PASS_TOKEN: tokens.get("pass_token"),
            CONF_USER_ID: tokens.get("user_id"),
            CONF_DEVICE_ID: tokens.get("device_id"),
            **default_options(),
        }

    async def _finish_login(self) -> ConfigFlowResult:
        if not self._coordinator or not self._coordinator._device_info:
            await self._close_session()
            if self.source == SOURCE_REAUTH:
                return self.async_show_form(
                    step_id="reauth_confirm",
                    data_schema=vol.Schema(
                        {vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR}
                    ),
                    description_placeholders={"username": self._username or ""},
                    errors={"base": "no_device"},
                )
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_USERNAME, default=self._username or ""): str,
                        vol.Required(
                            CONF_PASSWORD, default=self._password or ""
                        ): _PASSWORD_SELECTOR,
                    }
                ),
                errors={"base": "no_device"},
            )
        await self._close_session()
        tokens = self._coordinator.export_tokens()
        if self.source == SOURCE_REAUTH:
            await self.async_set_unique_id(self._username)
            self._abort_if_unique_id_mismatch()
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates={
                    CONF_PASSWORD: self._password,
                    CONF_PASS_TOKEN: tokens.get("pass_token"),
                    CONF_USER_ID: tokens.get("user_id"),
                    CONF_DEVICE_ID: tokens.get("device_id"),
                },
            )
        return self.async_create_entry(
            title=self._username,
            data=self._entry_data(),
        )

    async def _attempt_login(self) -> tuple[str, dict[str, str]]:
        errors: dict[str, str] = {}
        self._coordinator = XiaomiCloudDataUpdateCoordinator(
            self.hass,
            self._username,
            self._password,
            DEFAULT_UPDATE_INTERVAL,
            schedule_refresh=False,
        )
        session = await self._ensure_session()
        try:
            result = await self._coordinator.async_setup_login(session)
        except Exception as err:
            _LOGGER.error("Login validation failed: %s", err)
            result = LOGIN_FAIL
        if result == LOGIN_NEED_VERIFY:
            return "verify", errors
        if result == LOGIN_OK:
            return "ok", errors
        if result == LOGIN_INVALID:
            errors[CONF_PASSWORD] = "invalid_auth"
        else:
            errors["base"] = "login_failed"
        await self._close_session()
        return "fail", errors

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._username = entry_data[CONF_USERNAME]
        self._password = entry_data.get(CONF_PASSWORD)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._password = user_input[CONF_PASSWORD]
            outcome, errors = await self._attempt_login()
            if outcome == "verify":
                return await self.async_step_verify()
            if outcome == "ok":
                return await self._finish_login()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR}),
            description_placeholders={"username": self._username or ""},
            errors=errors,
        )

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(self._username)
            self._abort_if_unique_id_configured()
            outcome, errors = await self._attempt_login()
            if outcome == "verify":
                return await self.async_step_verify()
            if outcome == "ok":
                return await self._finish_login()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        default=(user_input or {}).get(
                            CONF_USERNAME, self._username or ""
                        ),
                    ): str,
                    vol.Required(
                        CONF_PASSWORD,
                        default=(user_input or {}).get(CONF_PASSWORD, ""),
                    ): _PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
        )

    async def async_step_verify(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and self._coordinator is not None:
            session = await self._ensure_session()
            result = await self._coordinator.async_verify_ticket(
                session, user_input[CONF_VERIFY_CODE]
            )
            if result == LOGIN_OK:
                return await self._finish_login()
            if result == LOGIN_INVALID:
                errors[CONF_VERIFY_CODE] = "invalid_code"
            else:
                errors["base"] = "login_failed"
        step_id = "verify"
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_VERIFY_CODE): str}),
            description_placeholders={
                "target": (
                    self._coordinator.verify_target if self._coordinator else ""
                )
                or "手机/邮箱",
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return XiaomiCloudOptionsFlowHandler()


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


def _sanitize_option_updates(updates: dict[str, Any]) -> dict[str, Any]:
    return {key: updates[key] for key in OPTION_KEYS if key in updates}


class XiaomiCloudOptionsFlowHandler(config_entries.OptionsFlow):
    def _opt(self, key, default, user_input: dict[str, Any] | None = None):
        entry = self.config_entry
        if user_input is not None and key in user_input:
            return user_input[key]
        defaults = default_options()
        return entry.options.get(
            key, entry.data.get(key, defaults.get(key, default))
        )

    def _saved_list(self, key: str, default: list[str]) -> list[str]:
        defaults = default_options()
        raw = self.config_entry.options.get(
            key,
            self.config_entry.data.get(key, defaults.get(key, default)),
        )
        if isinstance(raw, str):
            return [raw] if raw else list(default)
        if isinstance(raw, list):
            return [str(item) for item in raw if str(item or "").strip()]
        return list(default)

    def _merge_options(self, updates: dict[str, Any]) -> dict[str, Any]:
        return {
            **default_options(),
            **{
                key: value
                for key, value in {**self.config_entry.data, **self.config_entry.options}.items()
                if key in OPTION_KEYS
            },
            **_sanitize_option_updates(updates),
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["locate", "amap"],
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
                user_input[CONF_PEAK_WINDOWS] = peak_text or ""
                user_input[CONF_OFFPEAK_WINDOWS] = offpeak_text or ""
                user_input[CONF_UPDATE_INTERVAL] = user_input[CONF_MAX_INTERVAL]
                return self.async_create_entry(
                    title="", data=self._merge_options(user_input)
                )
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

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_MAX_INTERVAL,
                default=self._opt(CONF_MAX_INTERVAL, DEFAULT_MAX_INTERVAL, user_input),
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

        suggested = {**entry.data, **entry.options}
        if user_input is not None:
            suggested.update(user_input)
        suggested.pop(CONF_PASSWORD, None)
        suggested.pop(CONF_AMAP_KEY, None)
        return self.async_show_form(
            step_id="locate",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), suggested
            ),
            errors=errors,
        )

    async def async_step_amap(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.config_entry

        if user_input is not None:
            user_input[CONF_AMAP_ENABLED] = bool(
                user_input.get(CONF_AMAP_ENABLED, False)
            )
            user_input[CONF_COMMUTE_ENABLED] = bool(
                user_input.get(CONF_COMMUTE_ENABLED, False)
            )
            saved_zones = self._saved_list(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES)
            zones = user_input.get(CONF_COMMUTE_ZONES) or []
            if isinstance(zones, str):
                zones = [zones]
            elif not isinstance(zones, list):
                zones = []
            validated_zones = [
                zone
                for zone in zones
                if str(zone or "").strip() and self.hass.states.get(zone) is not None
            ]
            if validated_zones:
                user_input[CONF_COMMUTE_ZONES] = validated_zones
            elif not zones:
                user_input[CONF_COMMUTE_ZONES] = []
            else:
                user_input[CONF_COMMUTE_ZONES] = saved_zones
            saved_company = self._saved_list(
                CONF_COMPANY_ZONES, DEFAULT_COMPANY_ZONES
            )
            company_zones = user_input.get(CONF_COMPANY_ZONES) or []
            if isinstance(company_zones, str):
                company_zones = [company_zones]
            elif not isinstance(company_zones, list):
                company_zones = []
            validated_company = [
                zone
                for zone in company_zones
                if str(zone or "").strip() and self.hass.states.get(zone) is not None
            ]
            if validated_company:
                user_input[CONF_COMPANY_ZONES] = validated_company
            elif not company_zones:
                user_input[CONF_COMPANY_ZONES] = []
            else:
                user_input[CONF_COMPANY_ZONES] = saved_company
            submitted_key = str(user_input.get(CONF_AMAP_KEY) or "").strip()
            saved_key = str(self._opt(CONF_AMAP_KEY, "", None) or "").strip()
            user_input[CONF_AMAP_KEY] = submitted_key or saved_key
            saved_activity = activity_entities(
                self._opt(CONF_ACTIVITY_ENTITY, DEFAULT_ACTIVITY_ENTITY, None)
            )
            submitted_activity = activity_entities(
                user_input.get(CONF_ACTIVITY_ENTITY)
            )
            validated_activity = [
                entity_id
                for entity_id in submitted_activity
                if self.hass.states.get(entity_id) is not None
            ]
            user_input[CONF_ACTIVITY_ENTITY] = (
                validated_activity if validated_activity else saved_activity
            )
            if user_input[CONF_AMAP_ENABLED] and not user_input[CONF_AMAP_KEY]:
                errors[CONF_AMAP_KEY] = "commute_key"
            if user_input[CONF_COMMUTE_ENABLED]:
                if not user_input[CONF_AMAP_ENABLED]:
                    errors[CONF_AMAP_ENABLED] = "amap_required"
                if not user_input[CONF_AMAP_KEY]:
                    errors[CONF_AMAP_KEY] = "commute_key"
                if not user_input[CONF_COMMUTE_ZONES]:
                    errors[CONF_COMMUTE_ZONES] = "commute_zones"
            if not errors:
                return self.async_create_entry(
                    title="", data=self._merge_options(user_input)
                )

        commute_zones = self._opt(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES, user_input)
        if isinstance(commute_zones, str):
            commute_zones = [commute_zones] if commute_zones else []
        elif not isinstance(commute_zones, list):
            commute_zones = []
        company_zones = self._opt(CONF_COMPANY_ZONES, DEFAULT_COMPANY_ZONES, user_input)
        if isinstance(company_zones, str):
            company_zones = [company_zones] if company_zones else []
        elif not isinstance(company_zones, list):
            company_zones = []
        commute_on = bool(
            self._opt(CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED, user_input)
        )
        zone_field = vol.Required if commute_on else vol.Optional
        activity_entity = activity_entities(
            self._opt(CONF_ACTIVITY_ENTITY, DEFAULT_ACTIVITY_ENTITY, user_input)
        )
        activity_field = (
            vol.Optional(CONF_ACTIVITY_ENTITY, default=activity_entity)
            if activity_entity
            else vol.Optional(CONF_ACTIVITY_ENTITY)
        )

        schema: dict[Any, Any] = {
            vol.Required(
                CONF_AMAP_ENABLED,
                default=self._opt(CONF_AMAP_ENABLED, DEFAULT_AMAP_ENABLED, user_input),
            ): bool,
            vol.Required(
                CONF_COMMUTE_ENABLED,
                default=self._opt(
                    CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED, user_input
                ),
            ): bool,
            zone_field(
                CONF_COMMUTE_ZONES, default=commute_zones
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="zone", multiple=True)
            ),
            vol.Optional(
                CONF_COMPANY_ZONES, default=company_zones
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="zone", multiple=True)
            ),
            activity_field: selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            vol.Optional(
                CONF_AMAP_KEY,
                default=self._opt(CONF_AMAP_KEY, "", user_input),
            ): _PASSWORD_SELECTOR,
        }

        suggested = {**entry.data, **entry.options}
        if user_input is not None:
            suggested.update(user_input)
        suggested.pop(CONF_PASSWORD, None)
        if not isinstance(suggested.get(CONF_ACTIVITY_ENTITY), list):
            suggested[CONF_ACTIVITY_ENTITY] = []
        return self.async_show_form(
            step_id="amap",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(schema), suggested
            ),
            errors=errors,
        )
