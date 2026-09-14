from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CarStatsCoordinator
from .entity import CarStatsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CarStatsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([CarStatsAddRefuelButton(coordinator)])


class CarStatsAddRefuelButton(CarStatsEntity, ButtonEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "add_refuel", "button")
        self._attr_icon = "mdi:gas-station-in-use"

    async def async_press(self) -> None:
        await self.coordinator.async_add_refuel_from_inputs()
