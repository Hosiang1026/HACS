from __future__ import annotations

import os
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import selector

from .const import (
    CONF_ENABLE_XIAOAI,
    CONF_MEDIA_PLAYERS,
    CONF_MUSIC_PATH,
    CONF_XIAOMI_HOME,
    CONF_XIAOMI_MIOT,
    DOMAIN,
)

TITLE = "Music Player"


async def _path_ok(hass: HomeAssistant, path: str) -> bool:
    return bool(path) and await hass.async_add_executor_job(os.path.isdir, path)


class HaMusicPlayerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            path = user_input[CONF_MUSIC_PATH].strip()
            if not await _path_ok(self.hass, path):
                errors["base"] = "invalid_path"
            else:
                user_input[CONF_MUSIC_PATH] = path
                self._data = user_input
                if user_input.get(CONF_ENABLE_XIAOAI):
                    return await self.async_step_xiaoai()
                return self.async_create_entry(title=TITLE, data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MUSIC_PATH, default=(user_input or {}).get(CONF_MUSIC_PATH, "/media/music")): str,
                    vol.Optional(CONF_ENABLE_XIAOAI, default=(user_input or {}).get(CONF_ENABLE_XIAOAI, False)): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_xiaoai(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=TITLE, data=self._data)
        return self.async_show_form(
            step_id="xiaoai",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_XIAOMI_HOME): selector({"entity": {"domain": "media_player"}}),
                    vol.Optional(CONF_XIAOMI_MIOT): selector({"entity": {"domain": "media_player"}}),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        entry = self.config_entry
        merged = {**entry.data, **entry.options}
        if user_input is not None:
            path = user_input[CONF_MUSIC_PATH].strip()
            if not await _path_ok(self.hass, path):
                errors["base"] = "invalid_path"
            else:
                user_input[CONF_MUSIC_PATH] = path
                return self.async_create_entry(title="", data=user_input)
        schema = {
            vol.Required(CONF_MUSIC_PATH, default=merged.get(CONF_MUSIC_PATH, "/media/music")): str,
            vol.Optional(CONF_ENABLE_XIAOAI, default=bool(merged.get(CONF_ENABLE_XIAOAI, False))): bool,
        }
        home = merged.get(CONF_XIAOMI_HOME) or None
        miot = merged.get(CONF_XIAOMI_MIOT) or None
        if home:
            schema[vol.Optional(CONF_XIAOMI_HOME, default=home)] = selector({"entity": {"domain": "media_player"}})
        else:
            schema[vol.Optional(CONF_XIAOMI_HOME)] = selector({"entity": {"domain": "media_player"}})
        if miot:
            schema[vol.Optional(CONF_XIAOMI_MIOT, default=miot)] = selector({"entity": {"domain": "media_player"}})
        else:
            schema[vol.Optional(CONF_XIAOMI_MIOT)] = selector({"entity": {"domain": "media_player"}})
        schema[vol.Optional(CONF_MEDIA_PLAYERS, default=merged.get(CONF_MEDIA_PLAYERS) or [])] = selector(
            {"entity": {"domain": "media_player", "multiple": True}}
        )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)
