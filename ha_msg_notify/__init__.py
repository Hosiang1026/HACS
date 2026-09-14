from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CHANNELS,
    CONF_CHANNEL_ID,
    DOMAIN,
    PLATFORMS,
    SERVICE_CAROUSEL,
    SERVICE_CLEAR,
    SERVICE_REMOVE,
    SERVICE_SEND,
)
from .coordinator import MsgNotifyCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    return True


def _expected_unique_ids(entry: ConfigEntry) -> set[str]:
    eid = entry.entry_id
    expected = {
        f"{eid}_sensor_current_message",
        f"{eid}_sensor_current_source",
        f"{eid}_sensor_message_time",
        f"{eid}_sensor_message_count",
        f"{eid}_sensor_message_queue",
        f"{eid}_sensor_enabled_channels",
        f"{eid}_sensor_disabled_channels",
        f"{eid}_number_carousel_interval",
        f"{eid}_switch_carousel_enabled",
    }
    for channel in entry.options.get(CONF_CHANNELS) or []:
        cid = channel.get(CONF_CHANNEL_ID)
        if cid:
            expected.add(f"{eid}_switch_channel_{cid}")
            expected.add(f"{eid}_button_channel_{cid}_test")
    return expected


def _async_cleanup_orphans(hass: HomeAssistant, entry: ConfigEntry) -> None:
    keep_devices = {entry.entry_id}
    for channel in entry.options.get(CONF_CHANNELS) or []:
        cid = channel.get(CONF_CHANNEL_ID)
        if cid:
            keep_devices.add(f"{entry.entry_id}_{cid}")

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


def _get_coordinator(
    hass: HomeAssistant, entry_id: str | None
) -> MsgNotifyCoordinator | None:
    domain_data = hass.data.get(DOMAIN) or {}
    if entry_id:
        data = domain_data.get(entry_id)
        return data.get("coordinator") if data else None
    if len(domain_data) == 1:
        data = next(iter(domain_data.values()))
        return data.get("coordinator")
    return None


async def _async_handle_send(call: ServiceCall) -> None:
    coordinator = _get_coordinator(call.hass, call.data.get("entry_id"))
    if not coordinator:
        _LOGGER.warning("ha_msg_notify.send: 未找到通知管理实例")
        return
    await coordinator.async_send(
        title=call.data.get("title"),
        message=call.data.get("message"),
        channels=call.data.get("channels"),
        carousel=bool(call.data.get("carousel")),
        source=call.data.get("source"),
        content=call.data.get("content"),
    )


async def _async_handle_carousel(call: ServiceCall) -> None:
    coordinator = _get_coordinator(call.hass, call.data.get("entry_id"))
    if not coordinator:
        _LOGGER.warning("ha_msg_notify.carousel: 未找到通知管理实例")
        return
    content = call.data.get("content") or call.data.get("message") or ""
    if not content:
        return
    await coordinator.async_carousel(content, call.data.get("source"))


async def _async_handle_clear(call: ServiceCall) -> None:
    coordinator = _get_coordinator(call.hass, call.data.get("entry_id"))
    if not coordinator:
        _LOGGER.warning("ha_msg_notify.clear: 未找到通知管理实例")
        return
    await coordinator.async_clear_messages()


async def _async_handle_remove(call: ServiceCall) -> None:
    coordinator = _get_coordinator(call.hass, call.data.get("entry_id"))
    if not coordinator:
        _LOGGER.warning("ha_msg_notify.remove: 未找到通知管理实例")
        return
    await coordinator.async_remove_message(int(call.data["index"]))


def _register_services(hass: HomeAssistant) -> None:
    send_schema = vol.Schema(
        {
            vol.Optional("entry_id"): cv.string,
            vol.Optional("title"): cv.string,
            vol.Optional("message"): cv.string,
            vol.Optional("content"): cv.string,
            vol.Optional("source"): cv.string,
            vol.Optional("channels"): [cv.string],
            vol.Optional("carousel"): cv.boolean,
        }
    )
    carousel_schema = vol.Schema(
        {
            vol.Optional("entry_id"): cv.string,
            vol.Optional("content"): cv.string,
            vol.Optional("message"): cv.string,
            vol.Optional("source"): cv.string,
        }
    )
    clear_schema = vol.Schema({vol.Optional("entry_id"): cv.string})
    remove_schema = vol.Schema(
        {
            vol.Required("index"): vol.Coerce(int),
            vol.Optional("entry_id"): cv.string,
        }
    )

    services = (
        (SERVICE_SEND, _async_handle_send, send_schema),
        (SERVICE_CAROUSEL, _async_handle_carousel, carousel_schema),
        (SERVICE_CLEAR, _async_handle_clear, clear_schema),
        (SERVICE_REMOVE, _async_handle_remove, remove_schema),
    )
    for service, handler, schema in services:
        if not hass.services.has_service(DOMAIN, service):
            hass.services.async_register(DOMAIN, service, handler, schema=schema)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    coordinator = MsgNotifyCoordinator(hass, entry)
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_cleanup_orphans(hass, entry)
    _register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data and "coordinator" in data:
        coordinator: MsgNotifyCoordinator = data["coordinator"]
        if coordinator._suppress_reload > 0:
            coordinator._suppress_reload -= 1
            coordinator._sync_entry()
            coordinator.async_sync_channel_services()
            return
        coordinator._sync_entry()
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator: MsgNotifyCoordinator = data["coordinator"]
        await coordinator.async_shutdown()
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            for service in (SERVICE_SEND, SERVICE_CAROUSEL, SERVICE_CLEAR, SERVICE_REMOVE):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
    return unload_ok
