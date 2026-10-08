"""Support for iCloud sensors."""
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
from homeassistant.const import PERCENTAGE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.icon import icon_for_battery_level

from homeassistant.util.dt import as_local

from .account import IcloudAccount, IcloudDevice, apply_suggested_entity_id
from .const import DOMAIN, INTEGRATION_HUB_SUFFIX

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up battery sensor for iCloud component."""
    account: IcloudAccount = entry.runtime_data
    tracked = set[str]()
    hub_id = f"{entry.unique_id or account.username}{INTEGRATION_HUB_SUFFIX}"

    @callback
    def update_account():
        """Update the values of the account."""
        add_entities(account, async_add_entities, tracked)

    account.listeners.append(
        async_dispatcher_connect(hass, account.signal_device_new, update_account)
    )

    async_add_entities(
        [
            IcloudHubCreatedAtSensor(entry, hub_id),
            IcloudHubQueryTimeSensor(account, hub_id),
            IcloudHubLocateCountSensor(account, hub_id),
            IcloudHubAmapCountSensor(account, hub_id),
        ]
    )
    update_account()


@callback
def add_entities(account, async_add_entities, tracked):
    """Add new battery sensor entities from the account."""
    if account._shutdown:
        return
    try:
        devices = list(account.devices.items())
    except RuntimeError:
        if not account._shutdown:
            account.hass.loop.call_later(
                1, add_entities, account, async_add_entities, tracked
            )
        return

    new_tracked = []
    for dev_id, device in devices:
        if f"{dev_id}_battery" not in tracked:
            new_tracked.append(
                IcloudDeviceBatterySensor(account, device, tracked, f"{dev_id}_battery")
            )
            tracked.add(f"{dev_id}_battery")
        if f"{dev_id}_steps" not in tracked:
            new_tracked.append(
                IcloudDeviceStepsSensor(account, device, tracked, f"{dev_id}_steps")
            )
            tracked.add(f"{dev_id}_steps")
        if f"{dev_id}_phone_status" not in tracked:
            new_tracked.append(
                IcloudDevicePhoneStatusSensor(
                    account, device, tracked, f"{dev_id}_phone_status"
                )
            )
            tracked.add(f"{dev_id}_phone_status")
        if f"{dev_id}_update_time" not in tracked:
            new_tracked.append(
                IcloudDeviceLocationTimeSensor(
                    account, device, tracked, f"{dev_id}_update_time"
                )
            )
            tracked.add(f"{dev_id}_update_time")
        if f"{dev_id}_address" not in tracked:
            new_tracked.append(
                IcloudDeviceAddressSensor(
                    account, device, tracked, f"{dev_id}_address"
                )
            )
            tracked.add(f"{dev_id}_address")
        if f"{dev_id}_commute_distance" not in tracked:
            new_tracked.append(
                IcloudDeviceCommuteDistanceSensor(
                    account, device, tracked, f"{dev_id}_commute_distance"
                )
            )
            tracked.add(f"{dev_id}_commute_distance")
        if f"{dev_id}_commute_time" not in tracked:
            new_tracked.append(
                IcloudDeviceCommuteTimeSensor(
                    account, device, tracked, f"{dev_id}_commute_time"
                )
            )
            tracked.add(f"{dev_id}_commute_time")
        if f"{dev_id}_commute_info" not in tracked:
            new_tracked.append(
                IcloudDeviceCommuteInfoSensor(
                    account, device, tracked, f"{dev_id}_commute_info"
                )
            )
            tracked.add(f"{dev_id}_commute_info")

    if new_tracked:
        async_add_entities(new_tracked, True)


class IcloudHubCreatedAtSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "created_at"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry, hub_id: str) -> None:
        created = getattr(entry, "created_at", None)
        if created is None:
            created = datetime.now().astimezone()
        self._attr_native_value = as_local(created).strftime("%Y-%m-%d %H:%M:%S")
        self._attr_unique_id = f"{hub_id}_created_at"
        self._attr_suggested_object_id = "ha_icloud_cn_created_at"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub_id)})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.hass.loop.call_soon(
            apply_suggested_entity_id,
            self.hass,
            self.entity_id,
            self._attr_suggested_object_id,
        )


class IcloudHubQueryTimeSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "query_time"

    def __init__(self, account: IcloudAccount, hub_id: str) -> None:
        self._account = account
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        self._attr_unique_id = f"{hub_id}_query_time"
        self._attr_suggested_object_id = "ha_icloud_cn_query_time"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub_id)})

    @property
    def available(self) -> bool:
        return self._account.online

    @property
    def native_value(self) -> datetime | None:
        return self._account.query_timestamp

    @callback
    def _handle_device_update(self) -> None:
        if self._account._shutdown:
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
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
        await super().async_will_remove_from_hass()


class _IcloudHubUsageSensor(RestoreSensor, SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, account: IcloudAccount, hub_id: str, suffix: str) -> None:
        self._account = account
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        self._attr_unique_id = f"{hub_id}_{suffix}"
        self._attr_suggested_object_id = f"ha_icloud_cn_{suffix}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub_id)})
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def available(self) -> bool:
        return self._account.online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"usage_day": self._account.usage_day}

    @callback
    def _handle_device_update(self) -> None:
        if self._account._shutdown:
            return
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
            if day is None and "usage_month" in last.attributes:
                value = None
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


class IcloudHubLocateCountSensor(_IcloudHubUsageSensor):
    _attr_icon = "mdi:crosshairs-gps"
    _attr_translation_key = "locate_count"

    def __init__(self, account: IcloudAccount, hub_id: str) -> None:
        super().__init__(account, hub_id, "locate_count")

    @property
    def native_value(self) -> int:
        return self._account.locate_count

    def _restore_count(self, value: int | None, day: str | None) -> None:
        self._account.restore_usage(locate=value, day=day)


class IcloudHubAmapCountSensor(_IcloudHubUsageSensor):
    _attr_icon = "mdi:map-search"
    _attr_translation_key = "amap_count"

    def __init__(self, account: IcloudAccount, hub_id: str) -> None:
        super().__init__(account, hub_id, "amap_count")

    @property
    def native_value(self) -> int:
        return self._account.amap_count

    def _restore_count(self, value: int | None, day: str | None) -> None:
        self._account.restore_usage(amap=value, day=day)


class _IcloudDeviceSensor(SensorEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        account: IcloudAccount,
        device: IcloudDevice,
        tracked: set[str],
        track_key: str,
    ) -> None:
        self._account = account
        self._device = device
        self._tracked = tracked
        self._track_key = track_key
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        if track_key.endswith("_phone_status"):
            object_suffix = "status"
        elif track_key.endswith("_update_time"):
            object_suffix = "update_time"
        elif track_key.endswith("_battery"):
            object_suffix = "battery"
        elif track_key.endswith("_address"):
            object_suffix = "address"
        elif track_key.endswith("_commute_distance"):
            object_suffix = "commute_distance"
        elif track_key.endswith("_commute_time"):
            object_suffix = "commute_time"
        elif track_key.endswith("_commute_info"):
            object_suffix = "commute_info"
        else:
            object_suffix = "steps"
        self._attr_suggested_object_id = f"{device.object_slug}_icloud_{object_suffix}"

    @property
    def available(self) -> bool:
        return (
            self._account.online
            and self._device.unique_id in self._account.devices
        )

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            configuration_url="https://www.icloud.com.cn/",
            identifiers={(DOMAIN, self._device.unique_id)},
            manufacturer="Apple",
            model=self._device.device_model,
            name=self._device.name,
        )

    @callback
    def _handle_device_update(self) -> None:
        if self._account._shutdown or self._device.unique_id not in self._account.devices:
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


class IcloudDeviceBatterySensor(_IcloudDeviceSensor):
    """Representation of a iCloud device battery sensor."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = "battery"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._device.unique_id}_battery"

    @property
    def native_value(self) -> int | None:
        """Battery state percentage."""
        return self._device.battery_level

    @property
    def icon(self) -> str:
        """Battery state icon handling."""
        if self._device.battery_level is None:
            return "mdi:battery-unknown"
        return icon_for_battery_level(
            battery_level=self._device.battery_level,
            charging=self._device.battery_status == "Charging",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return default attributes for the iCloud device entity."""
        return self._device.extra_state_attributes


class IcloudDeviceStepsSensor(RestoreSensor, _IcloudDeviceSensor):
    _attr_icon = "mdi:walk"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_translation_key = "steps"

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_steps"

    @property
    def native_value(self) -> int:
        return self._device.daily_steps

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        steps_date = self._device.steps_date
        return {
            "daily_distance": self._device.daily_distance,
            "last_latitude": self._device.last_latitude,
            "last_longitude": self._device.last_longitude,
            "last_timestamp": self._device.last_timestamp,
            "steps_date": steps_date.isoformat() if steps_date else None,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            self._device.restore_step_state(last.state, last.attributes)


class IcloudDevicePhoneStatusSensor(_IcloudDeviceSensor):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["online", "offline"]
    _attr_translation_key = "phone_status"

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_phone_status"

    @property
    def native_value(self) -> str:
        return self._device.phone_status

    @property
    def icon(self) -> str:
        if self._device.phone_status == "online":
            return "mdi:cellphone-check"
        return "mdi:cellphone-off"


class IcloudDeviceLocationTimeSensor(_IcloudDeviceSensor):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "update_time"

    @property
    def unique_id(self) -> str:
        return f"{self._device.object_slug}_icloud_update_time"

    @property
    def native_value(self) -> datetime | None:
        return self._device.location_timestamp


class IcloudDeviceAddressSensor(RestoreSensor, _IcloudDeviceSensor):
    _attr_icon = "mdi:map-marker"
    _attr_translation_key = "address"

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


class IcloudDeviceCommuteDistanceSensor(RestoreSensor, _IcloudDeviceSensor):
    _attr_native_unit_of_measurement = "公里"
    _attr_translation_key = "commute_distance"

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


class IcloudDeviceCommuteTimeSensor(RestoreSensor, _IcloudDeviceSensor):
    _attr_icon = "mdi:clock-outline"
    _attr_translation_key = "commute_time"

    @property
    def unique_id(self) -> str:
        return f"{self._device.unique_id}_commute_time"

    @property
    def native_value(self) -> str | None:
        return self._device.commute_time_text

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = await self.async_get_last_sensor_data()
        if data is not None and data.native_value is not None:
            self._device.restore_commute_time(data.native_value)
            return
        last = await self.async_get_last_state()
        if last is not None:
            self._device.restore_commute_time(last.state)


class IcloudDeviceCommuteInfoSensor(RestoreSensor, _IcloudDeviceSensor):
    _attr_icon = "mdi:briefcase-clock"
    _attr_translation_key = "commute_info"

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
