from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CHANNEL_ID, DOMAIN, MANUFACTURER
from .coordinator import MsgNotifyCoordinator


class MsgNotifyEntity(CoordinatorEntity[MsgNotifyCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: MsgNotifyCoordinator,
        key: str,
        domain: str,
        object_id: str | None = None,
        device_id: str | None = None,
        device_name: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._object_id = object_id or key
        self.entity_id = f"{domain}.{self._object_id}"
        self._attr_suggested_object_id = self._object_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{domain}_{key}"
        ident = device_id or coordinator.entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ident)},
            name=device_name or coordinator.instance_name,
            manufacturer=MANUFACTURER,
            model="通知管理",
        )


def channel_switch_id(channel: dict) -> str:
    return f"channel_{channel[CONF_CHANNEL_ID]}"
