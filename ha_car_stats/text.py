from __future__ import annotations

from homeassistant.components.text import RestoreText, TextEntity, TextMode
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
    async_add_entities([CarStatsStationText(coordinator)])


class CarStatsStationText(CarStatsEntity, RestoreText, TextEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "station_name", 'text')
        self._attr_native_min = 0
        self._attr_native_max = 64
        self._attr_mode = TextMode.TEXT
        self._attr_icon = "mdi:gas-station"

    @property
    def native_value(self) -> str:
        return str(self.coordinator.inputs.get("station_name") or "")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        snap = self.coordinator.store.snapshot(self.entry.entry_id).get("inputs") or {}
        if snap.get("station_name") is not None:
            return
        last = await self.async_get_last_text_data()
        if last and last.native_value is not None:
            self.coordinator.inputs["station_name"] = str(last.native_value)

    async def async_set_value(self, value: str) -> None:
        self.coordinator.inputs["station_name"] = (value or "").strip()
        await self.coordinator.async_persist_snapshot()
        self.async_write_ha_state()
