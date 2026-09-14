from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EnergyStatsCoordinator


class EnergyStatsEntity(CoordinatorEntity[EnergyStatsCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EnergyStatsCoordinator, key: str, domain: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = key
        self._object_id = key
        self.entity_id = f"{domain}.{self._object_id}"
        self._attr_suggested_object_id = self._object_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{domain}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.device_name,
            manufacturer="狂欢马克思",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        wanted = f"{self.platform.domain}.{self._object_id}"
        if self.entity_id == wanted:
            return
        registry = async_get_entity_registry(self.hass)
        if registry.async_get(self.entity_id):
            try:
                registry.async_update_entity(self.entity_id, new_entity_id=wanted)
            except ValueError:
                pass
