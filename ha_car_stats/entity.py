from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import CarStatsCoordinator
from .helpers import cfg_name


class CarStatsEntity(CoordinatorEntity[CarStatsCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: CarStatsCoordinator, key: str, domain: str) -> None:
        super().__init__(coordinator)
        self._key = key
        entry = coordinator.entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        slug = slugify(cfg_name(entry)) or "car"
        object_id = f"{slug}_{key}"
        self._attr_suggested_object_id = object_id
        self.entity_id = f"{domain}.{object_id}"

    @property
    def entry(self) -> ConfigEntry:
        return self.coordinator.entry

    @property
    def device_info(self) -> DeviceInfo:
        plate = ((self.coordinator.data or {}).get("vehicle") or {}).get("plate")
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=cfg_name(self.entry),
            manufacturer="狂欢马克思",
            model=plate or "车辆",
        )
