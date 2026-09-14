from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, VERSION


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    if not data.get("cities"):
        return
    device_name = entry.title or entry.data.get(CONF_NAME) or DEFAULT_NAME
    async_add_entities([RefreshButton(hass, entry, device_name)])


class RefreshButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_name: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._object_id = "refresh_weather"
        self.entity_id = "button.refresh_weather"
        self._attr_suggested_object_id = "refresh_weather"
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_translation_key = "refresh_weather"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=device_name,
            manufacturer=MANUFACTURER,
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        wanted = f"button.{self._object_id}"
        if self.entity_id == wanted:
            return
        registry = async_get_entity_registry(self.hass)
        if registry.async_get(self.entity_id):
            try:
                registry.async_update_entity(self.entity_id, new_entity_id=wanted)
            except ValueError:
                pass

    async def async_press(self) -> None:
        runtime = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not isinstance(runtime, dict):
            return
        for coord in runtime.get("cities") or []:
            await coord.async_request_refresh()
