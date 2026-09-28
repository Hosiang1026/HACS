from __future__ import annotations

import logging
import uuid
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .commute import _id_list
from .const import (
    CONF_ACTIVITY_ENTITY,
    CONF_API_KEY,
    CONF_AMAP_API_KEY,
    CONF_AMAP_DAILY_LIMIT,
    CONF_BASE_URL,
    CONF_COMMUTE_ENABLED,
    CONF_COMMUTE_ZONES,
    CONF_ENABLE_AMAP,
    CONF_INTERVAL,
    CONF_SESSION_KEY,
    CONF_USE_PAGE_LOCATION,
    DEFAULT_ACTIVITY_ENTITY,
    DEFAULT_AMAP_DAILY_LIMIT,
    DEFAULT_COMMUTE_ENABLED,
    DEFAULT_COMMUTE_ZONES,
    DEFAULT_ENABLE_AMAP,
    DEFAULT_INTERVAL,
    DEFAULT_USE_PAGE_LOCATION,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_OPTION_KEYS = [
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_INTERVAL,
    CONF_USE_PAGE_LOCATION,
    CONF_API_KEY,
    CONF_AMAP_API_KEY,
    CONF_AMAP_DAILY_LIMIT,
    CONF_ENABLE_AMAP,
    CONF_COMMUTE_ENABLED,
    CONF_COMMUTE_ZONES,
    CONF_ACTIVITY_ENTITY,
]


def _mask_username(username: str) -> str:
    if not username or len(username) <= 3:
        return "***"
    return username[:3] + "*" * (len(username) - 3)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class HonorCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input.get(CONF_BASE_URL, "").strip().rstrip("/")
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "").strip()

            if not base_url:
                errors["base"] = "base_url_required"
            elif not base_url.startswith(("http://", "https://")):
                errors["base"] = "invalid_url"
            elif not username:
                errors["base"] = "username_required"
            elif not password:
                errors["base"] = "password_required"

            if errors:
                return self.async_show_form(
                    step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors,
                )

            unique_id = f"{base_url}|{username}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get(
                            f"{base_url}/status",
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            if resp.status not in (200, 401, 403):
                                _LOGGER.warning(f"后端返回 {resp.status}")
                    except Exception as e:
                        _LOGGER.warning(f"连接测试失败: {e}")

                session_key = str(uuid.uuid4())

                data = {
                    CONF_BASE_URL: base_url,
                    CONF_SESSION_KEY: session_key,
                }

                options = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                    CONF_INTERVAL: DEFAULT_INTERVAL,
                    CONF_USE_PAGE_LOCATION: DEFAULT_USE_PAGE_LOCATION,
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
    def _merge_options(self, updates: dict[str, Any]) -> dict[str, Any]:
        base = dict(self.config_entry.options or {})
        for key in _OPTION_KEYS:
            if key in updates:
                base[key] = updates[key]
            elif key not in base and key in self.config_entry.data:
                base[key] = self.config_entry.data[key]
        return base

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["locate", "amap", "account"],
        )

    async def async_step_locate(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        options = self.config_entry.options or {}
        if user_input is not None:
            updated = self._merge_options(user_input)
            updated[CONF_INTERVAL] = int(user_input.get(CONF_INTERVAL, DEFAULT_INTERVAL // 60)) * 60
            updated[CONF_USE_PAGE_LOCATION] = bool(
                user_input.get(CONF_USE_PAGE_LOCATION, DEFAULT_USE_PAGE_LOCATION)
            )
            updated.pop("low_battery_threshold", None)
            updated.pop("enable_low_battery_update", None)
            updated.pop("low_battery_interval", None)
            return self.async_create_entry(title="", data=updated)

        current_interval_min = options.get(CONF_INTERVAL, DEFAULT_INTERVAL) // 60
        schema = vol.Schema(
            {
                vol.Optional(CONF_INTERVAL, default=current_interval_min): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=180)
                ),
                vol.Optional(
                    CONF_USE_PAGE_LOCATION,
                    default=options.get(CONF_USE_PAGE_LOCATION, DEFAULT_USE_PAGE_LOCATION),
                ): bool,
            }
        )
        return self.async_show_form(step_id="locate", data_schema=schema)

    async def async_step_amap(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
                updated[CONF_ACTIVITY_ENTITY] = user_input[CONF_ACTIVITY_ENTITY]
                return self.async_create_entry(title="", data=updated)

        source = user_input if user_input is not None else options
        zones = _id_list(source.get(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES))
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
                vol.Optional(CONF_ACTIVITY_ENTITY, default=activity): selector.EntitySelector(
                    selector.EntitySelectorConfig(multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="amap", data_schema=schema, errors=errors)

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
