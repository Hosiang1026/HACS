from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN, MANUFACTURER, VERSION


class GeneralInfoEntity(CoordinatorEntity[DataUpdateCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        *,
        key: str,
        platform: str,
        object_id: str,
        device_id: str,
        device_name: str,
        translation_key: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._object_id = object_id
        self.entity_id = f"{platform}.{object_id}"
        self._attr_suggested_object_id = object_id
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            manufacturer=MANUFACTURER,
            sw_version=VERSION,
        )
        if translation_key:
            self._attr_translation_key = translation_key
        if name:
            self._attr_name = name
            self._attr_has_entity_name = False

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
