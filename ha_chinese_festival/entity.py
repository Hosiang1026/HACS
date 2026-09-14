from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HolidayDailyCoordinator


class HolidayDailyEntity(CoordinatorEntity[HolidayDailyCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HolidayDailyCoordinator,
        key: str,
        domain: str,
        object_id: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        oid = object_id or key
        self._attr_suggested_object_id = oid
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{domain}_{key}"
        self.entity_id = f"{domain}.{oid}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="狂欢马克思",
        )
