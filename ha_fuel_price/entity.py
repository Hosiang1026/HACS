from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FuelPriceCoordinator


class FuelPriceEntity(CoordinatorEntity[FuelPriceCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FuelPriceCoordinator,
        key: str,
        object_id: str | None = None,
        device_id: str | None = None,
        device_name: str | None = None,
        platform: str = "sensor",
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._platform = platform
        self._object_id = object_id or key
        self.entity_id = f"{platform}.{self._object_id}"
        self._attr_suggested_object_id = self._object_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{platform}_{key}"
        ident = device_id or coordinator.entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ident)},
            name=device_name or coordinator.integration_name,
            manufacturer="狂欢马克思",
            sw_version=None,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        wanted = f"{self._platform}.{self._object_id}"
        if self.entity_id == wanted:
            return
        registry = async_get_entity_registry(self.hass)
        if registry.async_get(self.entity_id):
            try:
                registry.async_update_entity(self.entity_id, new_entity_id=wanted)
            except ValueError:
                pass
