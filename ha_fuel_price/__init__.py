from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_FILL_LITERS,
    CONF_PROVINCE_CODE,
    CONF_PROVINCES,
    DEFAULT_FILL_LITERS,
    DOMAIN,
    FUEL_TYPES,
    PLATFORMS,
    normalize_fill_liters,
)
from .coordinator import FuelPriceCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _expected_unique_ids(entry: ConfigEntry) -> set[str]:
    eid = entry.entry_id
    expected = {
        f"{eid}_sensor_created_at",
        f"{eid}_sensor_update_time",
        f"{eid}_sensor_trend",
        f"{eid}_button_manual_update",
    }
    fill_liters = normalize_fill_liters(
        entry.options.get(CONF_FILL_LITERS, DEFAULT_FILL_LITERS)
    )
    for province in entry.options.get(CONF_PROVINCES) or []:
        code = province.get(CONF_PROVINCE_CODE)
        if not code:
            continue
        for fuel in FUEL_TYPES:
            expected.add(f"{eid}_sensor_{code}_{fuel}")
        expected.add(f"{eid}_sensor_{code}_low_date")
        for fuel in FUEL_TYPES:
            expected.add(f"{eid}_sensor_{code}_{fuel}_low")
        if fill_liters > 0:
            for fuel in FUEL_TYPES:
                expected.add(f"{eid}_sensor_{code}_{fuel}_cost")
    return expected


def _async_cleanup_orphans(hass: HomeAssistant, entry: ConfigEntry) -> None:
    keep_devices = {entry.entry_id}
    for province in entry.options.get(CONF_PROVINCES) or []:
        code = province.get(CONF_PROVINCE_CODE)
        if code:
            keep_devices.add(f"{entry.entry_id}_{code}")

    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        idents = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if idents and not idents.intersection(keep_devices):
            device_reg.async_remove_device(device.id)

    expected = _expected_unique_ids(entry)
    entity_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        if ent.unique_id not in expected:
            entity_reg.async_remove(ent.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    coordinator = FuelPriceCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_cleanup_orphans(hass, entry)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
    return unload_ok
