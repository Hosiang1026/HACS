from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import as_local

from .const import DOMAIN, ICON_BATTERY, CONF_AMAP_API_KEY, CONF_ENABLE_AMAP, LOW_BATTERY_PERCENT
from .coordinator import SyncCoordinator
from .device_tracker import _get_stable_device_id, generate_slug

_LOGGER = logging.getLogger(__name__)


def _hub_device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="荣耀云服务",
        manufacturer="荣耀",
        model="honor_cloud",
    )


def _create_sensor_entities(
    sync_coordinator: SyncCoordinator,
    entry: ConfigEntry,
    known_ids: set[str],
) -> list[SensorEntity]:
    if not sync_coordinator.data:
        return []

    reason = sync_coordinator.data.get("reason", "")
    code = sync_coordinator.data.get("code", 0)
    if reason in ["NO_SESSION", "LOGIN_IN_PROGRESS"] or code == 990:
        return []

    devices = sync_coordinator.data.get("devices", [])
    entities: list[SensorEntity] = []

    for device in devices:
        device_id = _get_stable_device_id(device)
        if not device_id or device_id in known_ids:
            continue

        device_alias = device.get("deviceAliasName", "")
        model = device.get("model", "")
        name = device.get("name", "")

        if not (device_alias or model or name):
            continue

        final_name = device_alias or model or name or f"honor_{device_id[:6]}"
        slug = generate_slug(final_name, device_id)
        phone = device.get("phone", "")

        _LOGGER.info(
            f"[Sensor Setup] 创建传感器实体: device_id={device_id[:20]}..., "
            f"final_name={final_name}, slug={slug}"
        )

        known_ids.add(device_id)
        entities.extend([
            HonorAddressSensor(
                sync_coordinator, entry, device_id,
                final_name, model or final_name, phone, slug,
            ),
            HonorUpdateTimeSensor(
                sync_coordinator, entry, device_id,
                final_name, model or final_name, phone, slug,
            ),
            HonorBatterySensor(
                sync_coordinator, entry, device_id,
                final_name, model or final_name, phone, slug,
            ),
            HonorPhoneStatusSensor(
                sync_coordinator, entry, device_id,
                final_name, model or final_name, phone, slug,
            ),
            HonorCommuteDistanceSensor(
                sync_coordinator, entry, device_id,
                final_name, model or final_name, phone, slug,
            ),
            HonorCommuteTimeSensor(
                sync_coordinator, entry, device_id,
                final_name, model or final_name, phone, slug,
            ),
            HonorCommuteInfoSensor(
                sync_coordinator, entry, device_id,
                final_name, model or final_name, phone, slug,
            ),
        ])

    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators = hass.data[DOMAIN][entry.entry_id]
    sync_coordinator: SyncCoordinator = coordinators["sync_coordinator"]
    known_ids: set[str] = set()

    async_add_entities(
        [
            HonorStatusSensor(sync_coordinator, entry),
            HonorHubCreatedAtSensor(entry),
            HonorHubLocateCountSensor(sync_coordinator, entry),
            HonorHubAmapCountSensor(sync_coordinator, entry),
        ]
    )

    entities = _create_sensor_entities(sync_coordinator, entry, known_ids)
    if entities:
        async_add_entities(entities, update_before_add=True)
        _LOGGER.info(f"[Sensor Setup] 成功创建 {len(entities)} 个传感器实体")

    if not entities:
        _LOGGER.info("[Sensor Setup] 数据未就绪，已注册监听器等待设备数据")

        def _on_coordinator_update() -> None:
            new_entities = _create_sensor_entities(sync_coordinator, entry, known_ids)
            if new_entities:
                async_add_entities(new_entities, update_before_add=True)
                _LOGGER.info(f"[Sensor Setup] 延迟创建 {len(new_entities)} 个传感器实体")

        entry.async_on_unload(sync_coordinator.async_add_listener(_on_coordinator_update))


class HonorHubCreatedAtSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "created_at"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry) -> None:
        created = getattr(entry, "created_at", None)
        if created is None:
            created = datetime.now().astimezone()
        self._attr_native_value = as_local(created).strftime("%Y-%m-%d %H:%M:%S")
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:created_at"
        self._attr_suggested_object_id = "honor_cloud_created_at"
        self._attr_device_info = _hub_device_info(entry)


class HonorHubLocateCountSensor(CoordinatorEntity, RestoreSensor, SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:crosshairs-gps"
    _attr_translation_key = "locate_count"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: SyncCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:locate_count"
        self._attr_suggested_object_id = "honor_cloud_locate_count"
        self._attr_device_info = _hub_device_info(entry)

    @property
    def native_value(self) -> int:
        return self.coordinator.locate_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"usage_day": self.coordinator.usage_day}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            try:
                value = int(float(last.state))
            except (TypeError, ValueError):
                value = None
            day = last.attributes.get("usage_day")
            self.coordinator.restore_usage(
                locate=value, day=str(day) if day else None
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class HonorHubAmapCountSensor(CoordinatorEntity, RestoreSensor, SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:map-search"
    _attr_translation_key = "amap_count"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: SyncCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:amap_count"
        self._attr_suggested_object_id = "honor_cloud_amap_count"
        self._attr_device_info = _hub_device_info(entry)

    @property
    def native_value(self) -> int:
        return self.coordinator.amap_count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "usage_day": self.coordinator.usage_day,
            "daily_limit": self.coordinator._get_amap_daily_limit(),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            try:
                value = int(float(last.state))
            except (TypeError, ValueError):
                value = None
            day = last.attributes.get("usage_day")
            self.coordinator.restore_usage(
                amap=value, day=str(day) if day else None
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class HonorAddressSensor(CoordinatorEntity, SensorEntity):

    _attr_has_entity_name = True
    _attr_icon = "mdi:map-marker"

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        model: str,
        phone: str,
        slug: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._phone = phone
        self._slug = slug

        self._attr_unique_id = f"{DOMAIN}:{device_id}:address"
        self._attr_suggested_object_id = f"{slug}_address"
        self._attr_name = "地址"
        self._last_address: str | None = None

    def _unusable(self) -> bool:
        data = self.coordinator.data
        if not data:
            return True
        code = data.get("code", -1)
        reason = data.get("reason", "")
        return (
            code == 990
            or reason in ("LOGIN_IN_PROGRESS", "NO_SESSION")
            or bool(data.get("need_reauth"))
        )

    def _fresh_address(self) -> str | None:
        device = self._get_device_data()
        if not device:
            return None
        address = device.get("address")
        if isinstance(address, str) and address.strip():
            self._last_address = address.strip()
            return self._last_address
        return None

    def _fallback_address(self) -> str | None:
        if self._last_address:
            return self._last_address
        known = getattr(self.coordinator, "_last_known_devices", {}).get(self._device_id)
        if isinstance(known, dict):
            address = known.get("address")
            if isinstance(address, str) and address.strip():
                self._last_address = address.strip()
                return self._last_address
        return None

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
        if not self._unusable() and self._get_device_data():
            return True
        return self._fresh_address() is not None or self._fallback_address() is not None

    @property
    def native_value(self) -> str | None:
        if self._unusable() or not self._get_device_data():
            saved = self._fallback_address() or self._fresh_address()
            if saved:
                return saved
            if self._unusable() or not self.coordinator.data:
                return "初始化中"
            return "设备离线"

        fresh = self._fresh_address()
        if fresh:
            return fresh

        saved = self._fallback_address()
        if saved:
            return saved

        device = self._get_device_data()
        lat = device.get("latitude") if device else None
        lng = device.get("longitude") if device else None
        if lat is None or lng is None:
            return "坐标不可用"

        return "暂无地址"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {}

        if not self.coordinator.data:
            attrs["status"] = "initializing"
            return attrs

        backend_code = self.coordinator.data.get("code", -1)
        backend_reason = self.coordinator.data.get("reason", "")

        if backend_code == 990 or backend_reason in ["LOGIN_IN_PROGRESS", "NO_SESSION"]:
            attrs["status"] = "initializing"
            attrs["message"] = "后台登录中"
            attrs["last_backend_code"] = backend_code
            attrs["last_backend_reason"] = backend_reason
            return attrs

        device = self._get_device_data()

        if device:
            attrs["status"] = "online"
            attrs["device_id"] = self._device_id
            attrs["model"] = self._model

            wgs_lat = device.get("latitude")
            wgs_lng = device.get("longitude")
            if wgs_lat is not None and wgs_lng is not None:
                attrs["wgs84_latitude"] = float(wgs_lat)
                attrs["wgs84_longitude"] = float(wgs_lng)

                from .device_tracker import wgs84_to_gcj02
                gcj_lng, gcj_lat = wgs84_to_gcj02(float(wgs_lng), float(wgs_lat))
                attrs["gcj02_latitude"] = gcj_lat
                attrs["gcj02_longitude"] = gcj_lng

            ts = device.get("ts")
            if ts:
                try:
                    attrs["location_time"] = int(ts)
                except (ValueError, TypeError):
                    pass

            address_time = device.get("address_time")
            if address_time:
                try:
                    attrs["address_time"] = int(address_time)
                except (ValueError, TypeError):
                    pass

            has_address = bool(device.get("address"))
            amap_on = bool(
                self._entry.options.get(
                    CONF_ENABLE_AMAP,
                    self._entry.data.get(CONF_ENABLE_AMAP, False),
                )
            )
            amap_key = (
                self._entry.options.get(CONF_AMAP_API_KEY, "")
                or self._entry.data.get(CONF_AMAP_API_KEY, "")
            )
            attrs["geocoding_enabled"] = bool(amap_on and amap_key)
            attrs["geocoding_source"] = (
                "amap" if has_address and amap_on and amap_key else ("cached" if has_address else "none")
            )
            if not amap_on:
                attrs["geocoding_note"] = "高德调用已关闭"
            elif not amap_key:
                attrs["geocoding_note"] = "未配置高德 Key"
            elif not has_address:
                attrs["geocoding_note"] = "等待坐标变化后解析"
        else:
            attrs["status"] = "offline"

        return attrs

    def _get_device_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None

        devices = self.coordinator.data.get("devices", [])
        for device in devices:
            device_id = _get_stable_device_id(device)
            if device_id == self._device_id:
                return device

        return None


class HonorUpdateTimeSensor(CoordinatorEntity, SensorEntity):

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        model: str,
        phone: str,
        slug: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._phone = phone
        self._slug = slug
        self._attr_unique_id = f"{DOMAIN}:{device_id}:update_time"
        self._attr_suggested_object_id = f"{slug}_update_time"
        self._attr_name = "更新时间"
        self._last_time: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="荣耀",
            model=self._model or "未知型号",
        )

    def _format_ts(self, ts: Any) -> str | None:
        try:
            value = float(ts)
        except (TypeError, ValueError):
            return None
        if value > 1e12:
            value = value / 1000
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    def _current_time(self) -> str | None:
        device = self._get_device_data()
        if not device:
            return None
        text = self._format_ts(device.get("ts"))
        if text:
            self._last_time = text
        return text

    @property
    def available(self) -> bool:
        return self._current_time() is not None or self._last_time is not None

    @property
    def native_value(self) -> str | None:
        return self._current_time() or self._last_time

    def _get_device_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        devices = self.coordinator.data.get("devices", [])
        for device in devices:
            device_id = _get_stable_device_id(device)
            if device_id == self._device_id:
                return device
        return None


def _phone_status(value: Any) -> str | None:
    if value in (True, "online", "on", 1, "1"):
        return "online"
    if value in (False, "offline", "off", 0, "0"):
        return "offline"
    text = str(value).strip().lower() if value not in (None, "") else ""
    if text in ("online", "on", "true"):
        return "online"
    if text in ("offline", "off", "false"):
        return "offline"
    return None


class HonorPhoneStatusSensor(CoordinatorEntity, SensorEntity):

    _attr_has_entity_name = True
    _attr_icon = "mdi:cellphone"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["online", "offline", "unknown"]
    _attr_translation_key = "phone_status"

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        model: str,
        phone: str,
        slug: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._phone = phone
        self._slug = slug
        self._attr_unique_id = f"{DOMAIN}:{device_id}:phone_status"
        self._attr_suggested_object_id = f"{slug}_phone_status"
        self._last_status: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="荣耀",
            model=self._model or "未知型号",
        )

    def _read_status(self) -> str | None:
        device = self._get_device_data()
        if not device:
            known = getattr(self.coordinator, "_last_known_devices", {}).get(self._device_id)
            device = known if isinstance(known, dict) else None
        if not device:
            return None
        status = _phone_status(device.get("device_status"))
        if status:
            self._last_status = status
            return status
        return None

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        if data.get("auth_pending") or data.get("reason") in (
            "LOGIN_IN_PROGRESS",
            "NO_SESSION",
            "AUTH_EXPIRED",
            "NOT_LOGGED_IN",
        ) or data.get("code") == 990:
            return "offline"
        return self._read_status() or self._last_status or "unknown"

    def _get_device_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        devices = self.coordinator.data.get("devices", [])
        for device in devices:
            device_id = _get_stable_device_id(device)
            if device_id == self._device_id:
                return device
        return None


class HonorBatterySensor(CoordinatorEntity, SensorEntity):

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = ICON_BATTERY

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        model: str,
        phone: str,
        slug: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._phone = phone
        self._slug = slug

        self._attr_unique_id = f"{DOMAIN}:{device_id}:battery"
        self._attr_suggested_object_id = f"{slug}_battery"
        self._attr_name = "电量"

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
        if not self.coordinator.data:
            return False

        backend_code = self.coordinator.data.get("code", -1)
        backend_reason = self.coordinator.data.get("reason", "")

        if backend_code == 990 or backend_reason in ["LOGIN_IN_PROGRESS", "NO_SESSION"]:
            return False

        if self.coordinator.data.get("need_reauth"):
            return False

        device = self._get_device_data()
        if not device:
            return False

        return True

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None

        backend_code = self.coordinator.data.get("code", -1)
        backend_reason = self.coordinator.data.get("reason", "")

        if backend_code == 990 or backend_reason in ["LOGIN_IN_PROGRESS", "NO_SESSION"]:
            return None

        device = self._get_device_data()
        if not device:
            return None

        battery = device.get("battery")
        if battery is not None:
            try:
                return int(battery)
            except (ValueError, TypeError):
                return None

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = {}

        if not self.coordinator.data:
            attrs["status"] = "initializing"
            return attrs

        backend_code = self.coordinator.data.get("code", -1)
        backend_reason = self.coordinator.data.get("reason", "")

        if backend_code == 990 or backend_reason in ["LOGIN_IN_PROGRESS", "NO_SESSION"]:
            attrs["status"] = "initializing"
            attrs["message"] = "后台登录中"
            attrs["last_backend_code"] = backend_code
            attrs["last_backend_reason"] = backend_reason
            return attrs

        device = self._get_device_data()

        if device:
            attrs["status"] = "online"
            attrs["device_id"] = self._device_id
            attrs["model"] = self._model

            battery = device.get("battery")
            if battery is not None:
                try:
                    battery_int = int(battery)
                    attrs["is_low_battery"] = battery_int <= LOW_BATTERY_PERCENT
                except (ValueError, TypeError):
                    pass
        else:
            attrs["status"] = "offline"

        return attrs

    def _get_device_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None

        devices = self.coordinator.data.get("devices", [])
        for device in devices:
            device_id = _get_stable_device_id(device)
            if device_id == self._device_id:
                return device

        return None


class _HonorCommuteSensor(CoordinatorEntity, RestoreSensor):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        model: str,
        phone: str,
        slug: str,
        suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._phone = phone
        self._slug = slug
        self._attr_unique_id = f"{DOMAIN}:{device_id}:{suffix}"
        self._attr_translation_key = suffix
        self._attr_suggested_object_id = f"{slug}_{suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="荣耀",
            model=self._model or "未知型号",
        )

    def _get_device_data(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        devices = self.coordinator.data.get("devices", [])
        for device in devices:
            device_id = _get_stable_device_id(device)
            if device_id == self._device_id:
                return device
        return None


class HonorCommuteDistanceSensor(_HonorCommuteSensor):
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, coordinator, entry, device_id, device_name, model, phone, slug) -> None:
        super().__init__(
            coordinator, entry, device_id, device_name, model, phone, slug, "commute_distance"
        )

    @property
    def available(self) -> bool:
        return self.native_value is not None or self._get_device_data() is not None

    @property
    def native_value(self) -> float | None:
        return self.coordinator.commute_distance(self._device_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = await self.async_get_last_sensor_data()
        if data is not None and data.native_value is not None:
            self.coordinator.restore_commute_distance(self._device_id, data.native_value)
        else:
            last = await self.async_get_last_state()
            if last is not None:
                self.coordinator.restore_commute_distance(self._device_id, last.state)
        self.async_write_ha_state()


class HonorCommuteTimeSensor(_HonorCommuteSensor):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator, entry, device_id, device_name, model, phone, slug) -> None:
        super().__init__(
            coordinator, entry, device_id, device_name, model, phone, slug, "commute_time"
        )

    @property
    def available(self) -> bool:
        return self.native_value is not None or self._get_device_data() is not None

    @property
    def native_value(self) -> int | None:
        return self.coordinator.commute_time(self._device_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = await self.async_get_last_sensor_data()
        if data is not None and data.native_value is not None:
            self.coordinator.restore_commute_time(self._device_id, data.native_value)
        else:
            last = await self.async_get_last_state()
            if last is not None:
                self.coordinator.restore_commute_time(self._device_id, last.state)
        self.async_write_ha_state()


class HonorCommuteInfoSensor(_HonorCommuteSensor):
    _attr_icon = "mdi:briefcase-clock"

    def __init__(self, coordinator, entry, device_id, device_name, model, phone, slug) -> None:
        super().__init__(
            coordinator, entry, device_id, device_name, model, phone, slug, "commute_info"
        )

    @property
    def available(self) -> bool:
        return self.native_value is not None or self._get_device_data() is not None

    @property
    def native_value(self) -> str | None:
        return self.coordinator.commute_info(self._device_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self.coordinator.restore_commute_info(self._device_id, last.state)
        self.async_write_ha_state()


class HonorStatusSensor(CoordinatorEntity, SensorEntity):

    _attr_has_entity_name = True
    _attr_icon = "mdi:cloud-sync"

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}:{entry.entry_id}:status"
        self._attr_suggested_object_id = "honor_cloud_status"
        self._attr_name = "服务状态"

    @property
    def available(self) -> bool:
        return True

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="荣耀云服务",
            manufacturer="荣耀",
            model="honor_cloud",
        )

    @property
    def native_value(self) -> str:
        if not self.coordinator.data:
            return "初始化中"

        code = self.coordinator.data.get("code", -1)
        reason = self.coordinator.data.get("reason", "")

        if reason == "NO_SESSION":
            return "等待登录"
        if reason == "LOGIN_IN_PROGRESS":
            return "登录中"
        if code == 990:
            return "需要认证"
        if self.coordinator.data.get("need_reauth"):
            return "认证过期"

        devices = self.coordinator.data.get("devices", [])
        if code == 0 and devices:
            return f"正常（{len(devices)}台设备）"
        if code == 0:
            return "正常"

        return f"异常（code={code}）"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {"hint": "后台正在登录荣耀账号，请耐心等待30-60秒"}

        code = self.coordinator.data.get("code", -1)
        reason = self.coordinator.data.get("reason", "")
        devices = self.coordinator.data.get("devices", [])

        attrs: dict[str, Any] = {
            "code": code,
            "device_count": len(devices),
        }

        if reason:
            attrs["reason"] = reason

        if reason in ["NO_SESSION", "LOGIN_IN_PROGRESS"] or code == 990:
            attrs["hint"] = "后台正在登录荣耀账号，请耐心等待30-60秒"

        return attrs
