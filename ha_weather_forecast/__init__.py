from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ANNOUNCE,
    CONF_ENABLED,
    CONF_INSTANCES,
    CONF_NOTIFY,
    CONF_NOTIFY_ENABLED,
    DEFAULT_NAME,
    DOMAIN,
    FRONTEND_URL_BASE,
    PLATFORMS,
    VERSION,
)
from .coordinators.weather import WeatherCoordinator
from .defaults import merge_options

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_FRONTEND_KEY = f"{DOMAIN}_frontend"


async def _async_register_frontend(hass: HomeAssistant) -> None:
    if hass.data.get(_FRONTEND_KEY):
        return
    www = Path(__file__).parent / "www"
    if not www.is_dir():
        _LOGGER.error("frontend missing: %s", www)
        return
    path = str(www.resolve())
    if hasattr(hass.http, "async_register_static_paths"):
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_BASE, path, False)]
        )
    else:
        hass.http.register_static_path(FRONTEND_URL_BASE, path, False)
    frontend.add_extra_js_url(
        hass, f"{FRONTEND_URL_BASE}/weather-forecast-card.js?v={VERSION}"
    )
    hass.data[_FRONTEND_KEY] = True


async def async_setup(hass: HomeAssistant, _config: dict[str, Any]) -> bool:
    await _async_register_frontend(hass)
    return True


def _expected_unique_ids(entry: ConfigEntry, data: dict[str, Any]) -> set[str]:
    expected: set[str] = {f"{entry.entry_id}_created", f"{entry.entry_id}_refresh"}
    for coord in data.get("cities") or []:
        did = coord.device_id
        for key in (
            "updated_at",
            "condition",
            "temp",
            "feels",
            "humidity",
            "aqi",
            "wind",
            "indices",
            "forecast",
            "alarm",
        ):
            expected.add(f"{did}_{key}")
    return expected


def _async_cleanup_orphans(hass: HomeAssistant, entry: ConfigEntry, data: dict[str, Any]) -> None:
    keep_devices = {entry.entry_id}
    for coord in data.get("cities") or []:
        keep_devices.add(coord.device_id)

    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        idents = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if idents and not idents.intersection(keep_devices):
            device_reg.async_remove_device(device.id)

    expected = _expected_unique_ids(entry, data)
    entity_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        if ent.unique_id not in expected:
            entity_reg.async_remove(ent.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_register_frontend(hass)
    hass.data.setdefault(DOMAIN, {})
    opts = merge_options(dict(entry.options))
    entry_opts = {
        CONF_NOTIFY: opts.get(CONF_NOTIFY) or entry.data.get(CONF_NOTIFY),
        CONF_ANNOUNCE: opts.get(CONF_ANNOUNCE) or entry.data.get(CONF_ANNOUNCE),
        CONF_NOTIFY_ENABLED: (
            entry.data[CONF_NOTIFY_ENABLED]
            if CONF_NOTIFY_ENABLED in entry.data
            else True
        ),
        CONF_NAME: entry.data.get(CONF_NAME) or DEFAULT_NAME,
    }

    runtime: dict[str, Any] = {
        "cities": [],
        "options": opts,
        "entry_opts": entry_opts,
    }

    if opts.get(CONF_ENABLED, True):
        for inst in opts.get(CONF_INSTANCES) or []:
            if not inst.get("location"):
                continue
            coord = WeatherCoordinator(hass, entry, inst, entry_opts)
            try:
                await coord.async_config_entry_first_refresh()
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "weather first refresh failed: %s", inst.get("name")
                )
            runtime["cities"].append(coord)

    hass.data[DOMAIN][entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_cleanup_orphans(hass, entry, runtime)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    if not hass.services.has_service(DOMAIN, "refresh"):
        async def _refresh(_call: ServiceCall) -> None:
            for runtime in list(hass.data.get(DOMAIN, {}).values()):
                if not isinstance(runtime, dict):
                    continue
                for c in runtime.get("cities") or []:
                    await c.async_request_refresh()

        hass.services.async_register(DOMAIN, "refresh", _refresh, schema=vol.Schema({}))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            if hass.services.has_service(DOMAIN, "refresh"):
                hass.services.async_remove(DOMAIN, "refresh")
            hass.data.pop(DOMAIN, None)
    return unload_ok
