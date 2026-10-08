"""Device tracker for ha_xiaomi_cloud."""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .account import XiaomiAccount, XiaomiDevice, apply_suggested_entity_id, gcj02_to_wgs84
from .const import DOMAIN
from .entity import XiaomiAccountEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    account: XiaomiAccount = entry.runtime_data
    tracked: set[str] = set()

    @callback
    def update_account() -> None:
        add_entities(account, async_add_entities, tracked)

    account.listeners.append(
        async_dispatcher_connect(hass, account.signal_device_new, update_account)
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
        if dev_id in tracked:
            continue
        new_tracked.append(XiaomiTrackerEntity(account, device, tracked, dev_id))
        tracked.add(dev_id)
    if new_tracked:
        async_add_entities(new_tracked, True)


class XiaomiTrackerEntity(XiaomiAccountEntity, TrackerEntity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None
    _attr_force_update = True

    def __init__(
        self,
        account: XiaomiAccount,
        device: XiaomiDevice,
        tracked: set[str],
        track_key: str,
    ) -> None:
        self._account = account
        self._device = device
        self._tracked = tracked
        self._track_key = track_key
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        self._attr_suggested_object_id = f"{device.object_slug}_xiaomi"

    @property
    def unique_id(self) -> str:
        return self._device.unique_id

    @property
    def battery_level(self) -> int | None:
        return self._device.battery_level

    @property
    def latitude(self) -> float | None:
        lat = self._device.latitude
        lon = self._device.longitude
        if lat is None or lon is None:
            return None
        _, wgs_lat = gcj02_to_wgs84(lon, lat)
        return wgs_lat

    @property
    def longitude(self) -> float | None:
        lat = self._device.latitude
        lon = self._device.longitude
        if lat is None or lon is None:
            return None
        wgs_lon, _ = gcj02_to_wgs84(lon, lat)
        return wgs_lon

    @property
    def location_accuracy(self) -> int:
        return self._device.location_accuracy or 0

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def icon(self) -> str:
        return "mdi:cellphone-link"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(self._device.extra_state_attributes)
        attrs["coordinate_type"] = "wgs84"
        return attrs

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
