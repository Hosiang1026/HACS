"""Support for tracking for iCloud devices."""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .account import IcloudAccount, IcloudDevice, apply_suggested_entity_id
from .const import (
    DEVICE_LOCATION_HORIZONTAL_ACCURACY,
    DEVICE_LOCATION_LATITUDE,
    DEVICE_LOCATION_LONGITUDE,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up device tracker for iCloud component."""
    account: IcloudAccount = hass.data[DOMAIN][entry.unique_id]
    tracked = set[str]()

    @callback
    def update_account():
        """Update the values of the account."""
        add_entities(account, async_add_entities, tracked)

    account.listeners.append(
        async_dispatcher_connect(hass, account.signal_device_new, update_account)
    )

    update_account()


@callback
def add_entities(account: IcloudAccount, async_add_entities, tracked):
    """Add new tracker entities from the account."""
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
        if dev_id in tracked or device.location is None:
            continue

        new_tracked.append(IcloudTrackerEntity(account, device, tracked, dev_id))
        tracked.add(dev_id)

    if new_tracked:
        async_add_entities(new_tracked, True)


class IcloudTrackerEntity(TrackerEntity):
    """Represent a tracked device."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        account: IcloudAccount,
        device: IcloudDevice,
        tracked: set[str],
        track_key: str,
    ) -> None:
        """Set up the iCloud tracker entity."""
        self._account = account
        self._device = device
        self._tracked = tracked
        self._track_key = track_key
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        self._attr_suggested_object_id = f"{device.object_slug}_icloud"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._device.unique_id

    @property
    def location_accuracy(self) -> int:
        if self._device.location is None:
            return 0
        acc = self._device.location.get(DEVICE_LOCATION_HORIZONTAL_ACCURACY)
        if acc is None:
            return 0
        return int(float(acc))

    @property
    def latitude(self) -> float | None:
        if self._device.location is None:
            return None
        val = self._device.location.get(DEVICE_LOCATION_LATITUDE)
        return float(val) if val is not None else None

    @property
    def longitude(self) -> float | None:
        if self._device.location is None:
            return None
        val = self._device.location.get(DEVICE_LOCATION_LONGITUDE)
        return float(val) if val is not None else None

    @property
    def battery_level(self) -> int | None:
        """Return the battery level of the device."""
        return self._device.battery_level

    @property
    def source_type(self) -> SourceType:
        """Return the source type, eg gps or router, of the device."""
        return SourceType.GPS

    @property
    def icon(self) -> str:
        """Return the icon."""
        return icon_for_icloud_device(self._device)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the device state attributes."""
        return self._device.extra_state_attributes

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
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
        """Register state update callback."""
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
        """Clean up after entity before removal."""
        self._tracked.discard(self._track_key)
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None


def icon_for_icloud_device(icloud_device: IcloudDevice) -> str:
    """Return an icon for the device."""
    switcher = {
        "iPad": "mdi:tablet",
        "iPhone": "mdi:cellphone",
        "iPod": "mdi:ipod",
        "iMac": "mdi:monitor",
        "MacBookPro": "mdi:laptop",
    }

    return switcher.get(icloud_device.device_class, "mdi:cellphone-link")
