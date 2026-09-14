from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, VERSION

_MODULES = (
    ("lottery", "refresh_lottery", "refresh_lottery"),
    ("metal", "refresh_metal", "refresh_metal"),
    ("news", "refresh_news", "refresh_news"),
    ("stock", "refresh_stock", "refresh_stock"),
    ("media", "refresh_media", "refresh_media"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    device_name = entry.title or entry.data.get(CONF_NAME) or DEFAULT_NAME
    entities: list[ModuleRefreshButton] = []
    for module, key, translation_key in _MODULES:
        if not data.get(module):
            continue
        entities.append(
            ModuleRefreshButton(
                hass,
                entry,
                device_name,
                module=module,
                key=key,
                translation_key=translation_key,
            )
        )
    if entities:
        async_add_entities(entities)


class ModuleRefreshButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        device_name: str,
        *,
        module: str,
        key: str,
        translation_key: str,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._module = module
        self._object_id = key
        self.entity_id = f"button.{key}"
        self._attr_suggested_object_id = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = translation_key
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
        coord = runtime.get(self._module)
        if coord:
            await coord.async_request_refresh()
