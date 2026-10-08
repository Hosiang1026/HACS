from __future__ import annotations

import logging

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import aiohttp_client

from .const import CONF_API_KEY, DOMAIN
from .coordinator import SyncCoordinator
_LOGGER = logging.getLogger(__name__)


async def async_force_sync(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: SyncCoordinator,
    call: ServiceCall,
) -> None:
    mode = call.data.get("mode", "normal")
    _LOGGER.info("[Service] 手动触发同步 (mode=%s)", mode)

    if coordinator._refresh_lock.locked():
        raise HomeAssistantError("已有同步任务在执行中，请稍后再试")

    if mode == "active":
        await coordinator.async_request_active_locate(force=False)
    else:
        await coordinator.async_refresh()

    devices_count = len(coordinator.data.get("devices", [])) if coordinator.data else 0
    _LOGGER.info("[Service] 手动同步完成，设备数=%s", devices_count)


async def async_force_locate(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: SyncCoordinator,
    call: ServiceCall,
) -> None:
    _LOGGER.info("[Service] force_locate: 触发主动定位 + 立即刷新")
    await coordinator.async_request_active_locate(force=True)
    devices_count = len(coordinator.data.get("devices", [])) if coordinator.data else 0
    fresh_count = sum(
        1
        for d in (coordinator.data or {}).get("devices", [])
        if d.get("is_fresh")
    )
    _LOGGER.info(
        "[Service] force_locate 完成，设备=%s，新坐标=%s", devices_count, fresh_count
    )


async def async_ring(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: SyncCoordinator,
    call: ServiceCall,
) -> None:
    device_id = (call.data.get("device_id") or "").strip()
    action = (call.data.get("action") or "start").lower()

    if not device_id:
        raise ServiceValidationError("缺少 device_id")

    base_url = coordinator._base_url
    session_key = coordinator._session_key
    api_key = entry.options.get(CONF_API_KEY, "") or entry.data.get(CONF_API_KEY, "")

    url = f"{base_url}/ring"
    body = {"session_key": session_key, "device": device_id, "action": action}
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    _LOGGER.info("[Service] ring: action=%s device=...%s", action, device_id[-4:])
    session = aiohttp_client.async_get_clientsession(hass)
    try:
        async with session.post(
            url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise HomeAssistantError(f"响铃请求失败: {err}") from err

    if data.get("triggered"):
        return
    if data.get("cooldown_left") is not None:
        raise HomeAssistantError(
            f"响铃限频，请 {int(data['cooldown_left'])} 秒后再试"
        )
    msg = data.get("msg") or str(data.get("code"))
    raise HomeAssistantError(f"响铃失败: {msg}")


async def async_lost(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: SyncCoordinator,
    call: ServiceCall,
) -> None:
    device_id = (call.data.get("device_id") or "").strip()
    action = (call.data.get("action") or "start").lower()

    if not device_id:
        raise ServiceValidationError("缺少 device_id")

    from .text import get_lost_fields

    fields = get_lost_fields(hass, entry.entry_id, device_id)
    password = (call.data.get("password") or fields.get("lost_password") or "").strip()
    message = (call.data.get("message") or fields.get("lost_message") or "").strip()
    phone = (call.data.get("phone") or fields.get("lost_number") or "").strip()

    base_url = coordinator._base_url
    session_key = coordinator._session_key
    api_key = entry.options.get(CONF_API_KEY, "") or entry.data.get(CONF_API_KEY, "")

    url = f"{base_url}/lost"
    body = {
        "session_key": session_key,
        "device": device_id,
        "action": action,
        "password": password,
        "message": message,
        "phone": phone,
    }
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key

    _LOGGER.info("[Service] lost: action=%s device=...%s", action, device_id[-4:])
    session = aiohttp_client.async_get_clientsession(hass)
    try:
        async with session.post(
            url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            data = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise HomeAssistantError(f"丢失模式请求失败: {err}") from err

    if data.get("triggered"):
        return
    msg = data.get("msg") or str(data.get("code"))
    raise HomeAssistantError(f"丢失模式失败: {msg}")


def _bind(handler, hass: HomeAssistant, entry: ConfigEntry, coordinator: SyncCoordinator):
    async def _service(call: ServiceCall) -> None:
        await handler(hass, entry, coordinator, call)

    return _service


async def async_setup_services(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: SyncCoordinator
) -> None:
    if hass.services.has_service(DOMAIN, "force_sync"):
        return

    hass.services.async_register(
        DOMAIN,
        "force_sync",
        _bind(async_force_sync, hass, entry, coordinator),
    )
    hass.services.async_register(
        DOMAIN,
        "force_locate",
        _bind(async_force_locate, hass, entry, coordinator),
    )
    hass.services.async_register(
        DOMAIN,
        "ring",
        _bind(async_ring, hass, entry, coordinator),
    )
    hass.services.async_register(
        DOMAIN,
        "lost",
        _bind(async_lost, hass, entry, coordinator),
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    for name in ("force_sync", "force_locate", "ring", "lost"):
        if hass.services.has_service(DOMAIN, name):
            hass.services.async_remove(DOMAIN, name)
