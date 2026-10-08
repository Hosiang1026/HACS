"""Sensor platform for ha_xiaomi_cloud."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfTime
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.icon import icon_for_battery_level
from homeassistant.util.dt import as_local

from .account import XiaomiAccount, XiaomiDevice, apply_suggested_entity_id
from .const import DOMAIN, INTEGRATION_HUB_SUFFIX
from .entity import XiaomiAccountEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    account: XiaomiAccount = entry.runtime_data
    tracked: set[str] = set()
    hub_id = f"{entry.unique_id or account.username}{INTEGRATION_HUB_SUFFIX}"

    @callback
    def update_account() -> None:
        add_entities(account, async_add_entities, tracked)

    account.listeners.append(
        async_dispatcher_connect(hass, account.signal_device_new, update_account)
    )
    async_add_entities(
        [
            XiaomiHubCreatedAtSensor(account, hub_id),
            XiaomiHubLocateCountSensor(account, hub_id),
            XiaomiHubAmapCountSensor(account, hub_id),
        ]
    )
    update_account()


@callback
def add_entities(
    account: XiaomiAccount,
    async_add_entities: AddEntitiesCallback,
    tracked: set[str],
) -> None:
    new_tracked = []
    for dev_id, device in account.devices.items():
        for suffix, cls, key in (
            ("battery", XiaomiDeviceBatterySensor, f"{dev_id}_battery"),
            ("phone_status", XiaomiDevicePhoneStatusSensor, f"{dev_id}_phone_status"),
            ("update_time", XiaomiDeviceUpdateTimeSensor, f"{dev_id}_update_time"),
            ("address", XiaomiDeviceAddressSensor, f"{dev_id}_address"),
            ("commute_distance", XiaomiDeviceCommuteDistanceSensor, f"{dev_id}_commute_distance"),
            ("commute_time", XiaomiDeviceCommuteTimeSensor, f"{dev_id}_commute_time"),
            ("commute_info", XiaomiDeviceCommuteInfoSensor, f"{dev_id}_commute_info"),
        ):
            if key in tracked:
                continue
            new_tracked.append(cls(account, device, tracked, key))
            tracked.add(key)
    if new_tracked:
        async_add_entities(new_tracked, True)


class XiaomiHubCreatedAtSensor(XiaomiAccountEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "created_at"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, account: XiaomiAccount, hub_id: str) -> None:
        self._account = account
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        entry = account._entry
        created = getattr(entry, "created_at", None)
        if created is None:
            created = datetime.now().astimezone()
        self._attr_native_value = as_local(created).strftime("%Y-%m-%d %H:%M:%S")
        self._attr_unique_id = f"{hub_id}_created_at"
        self._attr_suggested_object_id = "ha_xiaomi_cloud_created_at"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub_id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass,
            self._account.signal_device_update,
            self._handle_availability_update,
        )
        self.hass.loop.call_soon(
            apply_suggested_entity_id,
            self.hass,
            self.entity_id,
            self._attr_suggested_object_id,
        )

    @callback
    def _handle_availability_update(self) -> None:
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
        await super().async_will_remove_from_hass()


class _XiaomiHubUsageSensor(XiaomiAccountEntity, RestoreSensor, SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, account: XiaomiAccount, hub_id: str, suffix: str) -> None:
        self._account = account
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        self._attr_unique_id = f"{hub_id}_{suffix}"
        self._attr_suggested_object_id = f"ha_xiaomi_cloud_{suffix}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub_id)})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"usage_day": self._account.usage_day}

    @callback
    def _handle_device_update(self) -> None:
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            try:
                value = int(float(last.state))
            except (TypeError, ValueError):
                value = None
            day = last.attributes.get("usage_day")
            self._restore_count(value, str(day) if day else None)
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, self._account.signal_device_update, self._handle_device_update
        )
        self.hass.loop.call_soon(
            apply_suggested_entity_id,
            self.hass,
            self.entity_id,
            self._attr_suggested_object_id,
        )

    def _restore_count(self, value: int | None, day: str | None) -> None:
        raise NotImplementedError

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
        await super().async_will_remove_from_hass()


class XiaomiHubLocateCountSensor(_XiaomiHubUsageSensor):
    _attr_icon = "mdi:crosshairs-gps"
    _attr_translation_key = "locate_count"

    def __init__(self, account: XiaomiAccount, hub_id: str) -> None:
        super().__init__(account, hub_id, "locate_count")

    @property
    def native_value(self) -> int:
        return self._account.locate_count

    def _restore_count(self, value: int | None, day: str | None) -> None:
        self._account.restore_usage(locate=value, day=day)


class XiaomiHubAmapCountSensor(_XiaomiHubUsageSensor):
    _attr_icon = "mdi:map-search"
    _attr_translation_key = "amap_count"

    def __init__(self, account: XiaomiAccount, hub_id: str) -> None:
        super().__init__(account, hub_id, "amap_count")

    @property
    def native_value(self) -> int:
        return self._account.amap_count

    def _restore_count(self, value: int | None, day: str | None) -> None:
        self._account.restore_usage(amap=value, day=day)


class _XiaomiDeviceSensor(XiaomiAccountEntity, SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_force_update = True

    def __init__(
        self,
        account: XiaomiAccount,
        device: XiaomiDevice,
        tracked: set[str],
        track_key: str,
        object_suffix: str,
        translation_key: str,
    ) -> None:
        self._account = account
        self._device = device
        self._tracked = tracked
        self._track_key = track_key
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        self._attr_translation_key = translation_key
        self._attr_suggested_object_id = f"{device.object_slug}_xiaomi_{object_suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            configuration_url="https://i.mi.com/",
            identifiers={(DOMAIN, self._device.unique_id)},
            manufacturer="Xiaomi",
            model=self._device.model,
            name=self._device.name,
            sw_version=self._device.version,
        )

    @callback
    def _handle_device_update(self) -> None:
        if self._device.unique_id not in self._account.devices:
            self.hass.async_create_task(self.async_remove(force_remove=True))
            return
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, self._account.signal_device_update, self._handle_device_update
        )
        self.hass.loop.call_soon(
            apply_suggested_entity_id,
            self.hass,
            self.entity_id,
            self._attr_suggested_object_id,
        )

    async def async_will_remove_from_hass(self) -> None:
        self._tracked.discard(self._track_key)
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
        await super().async_will_remove_from_hass()


class XiaomiDeviceBatterySensor(_XiaomiDeviceSensor):
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, account, device, tracked, track_key) -> None:
        super().__init__(account, device, tracked, track_key, "battery", "battery")

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_battery"

    @property
    def native_value(self) -> int | None:
        return self._device.battery_level

    @property
    def icon(self) -> str:
        if self._device.battery_level is None:
            return "mdi:battery-unknown"
        return icon_for_battery_level(battery_level=self._device.battery_level)


class XiaomiDevicePhoneStatusSensor(_XiaomiDeviceSensor):
    _attr_icon = "mdi:cellphone"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["online", "offline", "unknown"]

    def __init__(self, account, device, tracked, track_key) -> None:
        super().__init__(account, device, tracked, track_key, "status", "phone_status")

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_phone_status"

    @property
    def native_value(self) -> str:
        return self._device.phone_status


class XiaomiDeviceUpdateTimeSensor(RestoreSensor, _XiaomiDeviceSensor):
    _attr_icon = "mdi:clock-outline"

    def __init__(self, account, device, tracked, track_key) -> None:
        super().__init__(account, device, tracked, track_key, "update_time", "update_time")

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_update_time"

    @property
    def native_value(self) -> str | None:
        return self._device.location_update_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._device.last_poll_time:
            attrs["last_poll"] = self._device.last_poll_time
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            if not self._device.location_update_time:
                self._device._data["device_location_update_time"] = last.state
        if last is not None and not self._device.last_poll_time:
            poll = last.attributes.get("last_poll")
            if poll:
                self._device._data["last_poll_time"] = poll


class XiaomiDeviceAddressSensor(RestoreSensor, _XiaomiDeviceSensor):
    _attr_icon = "mdi:map-marker"

    def __init__(self, account, device, tracked, track_key) -> None:
        super().__init__(account, device, tracked, track_key, "address", "address")

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_address"

    @property
    def native_value(self) -> str | None:
        return self._device.location_address

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "poi": self._device.location_poi,
            "city": self._device.location_city,
            "district": self._device.location_district,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._device.restore_location_address(last.state)
            self._device.restore_location_attrs(last.attributes)


class XiaomiDeviceCommuteDistanceSensor(RestoreSensor, _XiaomiDeviceSensor):
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, account, device, tracked, track_key) -> None:
        super().__init__(account, device, tracked, track_key, "commute_distance", "commute_distance")

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_commute_distance"

    @property
    def native_value(self) -> float | None:
        return self._device.commute_distance

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = await self.async_get_last_sensor_data()
        if data is not None and data.native_value is not None:
            self._device.restore_commute_distance(data.native_value)
            return
        last = await self.async_get_last_state()
        if last is not None:
            self._device.restore_commute_distance(last.state)


class XiaomiDeviceCommuteTimeSensor(RestoreSensor, _XiaomiDeviceSensor):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, account, device, tracked, track_key) -> None:
        super().__init__(account, device, tracked, track_key, "commute_time", "commute_time")

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_commute_time"

    @property
    def native_value(self) -> int | None:
        return self._device.commute_time

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = await self.async_get_last_sensor_data()
        if data is not None and data.native_value is not None:
            self._device.restore_commute_time(data.native_value)
            return
        last = await self.async_get_last_state()
        if last is not None:
            self._device.restore_commute_time(last.state)


class XiaomiDeviceCommuteInfoSensor(RestoreSensor, _XiaomiDeviceSensor):
    _attr_icon = "mdi:briefcase-clock"

    def __init__(self, account, device, tracked, track_key) -> None:
        super().__init__(account, device, tracked, track_key, "commute_info", "commute_info")

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_commute_info"

    @property
    def native_value(self) -> str | None:
        return self._device.commute_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._device.restore_commute_info(last.state)
