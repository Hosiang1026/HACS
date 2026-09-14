from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FuelPriceCoordinator
from .entity import FuelPriceEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FuelPriceCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ManualUpdateButton(coordinator)])


class ManualUpdateButton(FuelPriceEntity, ButtonEntity):
    _attr_translation_key = "manual_update"

    def __init__(self, coordinator: FuelPriceCoordinator) -> None:
        super().__init__(
            coordinator,
            "manual_update",
            "fuel_price_manual_update",
            platform="button",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
