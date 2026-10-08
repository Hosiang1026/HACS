from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_URL, CONF_SESSION_KEY, CONF_API_KEY, DOMAIN, PARALLEL_UPDATES
from .coordinator import SyncCoordinator
from .runtime_data import get_runtime
from .device_tracker import _get_stable_device_id
from .text import get_lost_fields

_LOGGER = logging.getLogger(__name__)
_RING_COOLDOWN_SEC = 30
_LOST_COOLDOWN_SEC = 30


def _create_device_buttons(
    sync_coordinator: SyncCoordinator,
    entry: ConfigEntry,
    known_ids: set[str],
) -> list[ButtonEntity]:
    if not sync_coordinator.data:
        return []

    reason = sync_coordinator.data.get("reason", "")
    code = sync_coordinator.data.get("code", 0)
    if reason in ["NO_SESSION", "LOGIN_IN_PROGRESS"] or code == 990:
        return []

    devices = sync_coordinator.data.get("devices", [])
    entities: list[ButtonEntity] = []

    for device in devices:
        if device.get("is_shared"):
            continue

        device_id = _get_stable_device_id(device)
        if not device_id:
            continue

        device_alias = device.get("deviceAliasName", "")
        model = device.get("model", "")
        name = device.get("name", "")
        if not (device_alias or model or name):
            continue

        final_name = device_alias or model or name or f"honor_{device_id[:6]}"
        model_name = model or final_name

        ring_key = f"{device_id}:ring"
        if ring_key not in known_ids:
            known_ids.add(ring_key)
            entities.append(
                HonorRingButton(sync_coordinator, entry, device_id, final_name, model_name)
            )

        lost_key = f"{device_id}:lost"
        if lost_key not in known_ids:
            known_ids.add(lost_key)
            entities.append(
                HonorLostButton(sync_coordinator, entry, device_id, final_name, model_name)
            )

    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    sync_coordinator: SyncCoordinator = get_runtime(entry).sync_coordinator
    known_ids: set[str] = set()

    async_add_entities([HonorHubUpdateButton(sync_coordinator, entry)])

    entities = _create_device_buttons(sync_coordinator, entry, known_ids)
    if entities:
        async_add_entities(entities)
        _LOGGER.info(f"[Button Setup] 成功创建 {len(entities)} 个控制按钮")

    if not entities:
        _LOGGER.info("[Button Setup] 数据未就绪，已注册监听器等待设备数据")

        def _on_coordinator_update() -> None:
            new_entities = _create_device_buttons(sync_coordinator, entry, known_ids)
            if new_entities:
                async_add_entities(new_entities)
                _LOGGER.info(f"[Button Setup] 延迟创建 {len(new_entities)} 个控制按钮")

        entry.async_on_unload(sync_coordinator.async_add_listener(_on_coordinator_update))
    else:
        def _on_coordinator_update() -> None:
            new_entities = _create_device_buttons(sync_coordinator, entry, known_ids)
            if new_entities:
                async_add_entities(new_entities)

        entry.async_on_unload(sync_coordinator.async_add_listener(_on_coordinator_update))


class HonorHubUpdateButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_parallel_updates = PARALLEL_UPDATES
    _attr_translation_key = "update"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, coordinator: SyncCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:update"
        self._attr_suggested_object_id = "honor_cloud_update"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="荣耀云服务",
            manufacturer="荣耀",
            model="honor_cloud",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_request_active_locate(force=True)


class HonorRingButton(CoordinatorEntity, ButtonEntity):

    _attr_has_entity_name = True
    _attr_parallel_updates = PARALLEL_UPDATES
    _attr_icon = "mdi:bell-ring"
    _attr_translation_key = "ring"

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        model: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._last_pressed: float = 0.0

        self._attr_unique_id = f"{DOMAIN}:{device_id}:ring"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="荣耀",
            model=self._model or "未知型号",
        )

    @property
    def available(self) -> bool:
        if time.time() - self._last_pressed < _RING_COOLDOWN_SEC:
            return False
        return self.coordinator.data is not None or bool(
            getattr(self.coordinator, "_last_known_devices", None)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        elapsed = time.time() - self._last_pressed
        if elapsed < _RING_COOLDOWN_SEC:
            return {"cooldown_remaining": int(_RING_COOLDOWN_SEC - elapsed)}
        return {}

    async def async_press(self) -> None:
        base_url = self._entry.data[CONF_BASE_URL].rstrip("/")
        session_key = self._entry.data[CONF_SESSION_KEY]
        api_key = (
            self._entry.options.get(CONF_API_KEY, "")
            or self._entry.data.get(CONF_API_KEY, "")
        )

        url = f"{base_url}/ring"
        body: dict[str, Any] = {
            "session_key": session_key,
            "device": self._device_id,
            "action": "start",
        }
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key

        _LOGGER.info(f"[Ring] 触发响铃 device=...{self._device_id[-4:]}")
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.post(
                url, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
        except Exception as e:
            _LOGGER.error(f"[Ring] 请求后端失败: {e}")
            return

        triggered = data.get("triggered", False)
        cooldown_left = data.get("cooldown_left")
        code = data.get("code", -1)

        if triggered:
            _LOGGER.info(f"[Ring] ✅ 响铃成功 device=...{self._device_id[-4:]}")
            self._last_pressed = time.time()
            self.async_write_ha_state()
        elif cooldown_left is not None:
            _LOGGER.info(f"[Ring] 后端限流，cooldown_left={cooldown_left}s，视为成功")
            self._last_pressed = time.time()
            self.async_write_ha_state()
        else:
            _LOGGER.warning(f"[Ring] ❌ 响铃失败: {data.get('msg')} (code={code})")
            return

        async def _do_locate() -> None:
            try:
                await self.coordinator.async_request_active_locate(force=True)
                _LOGGER.info(f"[Ring] ✅ 定位完成 device=...{self._device_id[-4:]}")
            except Exception as e:
                _LOGGER.warning(f"[Ring] 定位失败（不影响响铃）: {e}")

        self.hass.async_create_task(_do_locate())


class HonorLostButton(CoordinatorEntity, ButtonEntity):

    _attr_has_entity_name = True
    _attr_parallel_updates = PARALLEL_UPDATES
    _attr_icon = "mdi:cellphone-lock"
    _attr_translation_key = "lost_device"

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        model: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._last_pressed: float = 0.0
        self._attr_unique_id = f"{DOMAIN}:{device_id}:lost"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="荣耀",
            model=self._model or "未知型号",
        )

    @property
    def available(self) -> bool:
        if time.time() - self._last_pressed < _LOST_COOLDOWN_SEC:
            return False
        return self.coordinator.data is not None or bool(
            getattr(self.coordinator, "_last_known_devices", None)
        )

    async def async_press(self) -> None:
        fields = get_lost_fields(self.hass, self._entry.entry_id, self._device_id)
        password = (fields.get("lost_password") or "").strip()
        message = (fields.get("lost_message") or "").strip()
        phone = (fields.get("lost_number") or "").strip()

        if not message:
            _LOGGER.warning("[Lost] 请先填写「丢失留言」")
            return
        if not phone:
            _LOGGER.warning("[Lost] 请先填写「联系电话」")
            return
        if password and (not password.isdigit() or not (4 <= len(password) <= 16)):
            _LOGGER.warning("[Lost] 锁屏密码须为 4-16 位数字")
            return

        base_url = self._entry.data[CONF_BASE_URL].rstrip("/")
        session_key = self._entry.data[CONF_SESSION_KEY]
        api_key = (
            self._entry.options.get(CONF_API_KEY, "")
            or self._entry.data.get(CONF_API_KEY, "")
        )

        url = f"{base_url}/lost"
        body: dict[str, Any] = {
            "session_key": session_key,
            "device": self._device_id,
            "action": "start",
            "password": password,
            "message": message,
            "phone": phone,
        }
        headers: dict[str, str] = {}
        if api_key:
            headers["X-API-Key"] = api_key

        _LOGGER.info(f"[Lost] 开启丢失模式 device=...{self._device_id[-4:]}")
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.post(
                url, json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
        except Exception as e:
            _LOGGER.error(f"[Lost] 请求后端失败: {e}")
            return

        triggered = data.get("triggered", False)
        cooldown_left = data.get("cooldown_left")
        code = data.get("code", -1)

        if triggered:
            _LOGGER.info(f"[Lost] ✅ 丢失模式已开启 device=...{self._device_id[-4:]}")
            self._last_pressed = time.time()
            self.async_write_ha_state()
        elif cooldown_left is not None:
            _LOGGER.info(f"[Lost] 后端限流，cooldown_left={cooldown_left}s")
            self._last_pressed = time.time()
            self.async_write_ha_state()
        else:
            _LOGGER.warning(f"[Lost] ❌ 失败: {data.get('msg')} (code={code})")
