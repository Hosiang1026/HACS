from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, UNIT_CNY, UNIT_KM, UNIT_L
from .coordinator import CarStatsCoordinator
from .entity import CarStatsEntity
from .helpers import cfg_odometer_entity

NUMBERS = (
    ("odometer", 0, 999999, 0.1, UNIT_KM, NumberDeviceClass.DISTANCE, "mdi:counter"),
    ("refuel_cost", 0, 9000, 0.01, UNIT_CNY, NumberDeviceClass.MONETARY, "mdi:cash"),
    ("refuel_liters", 0, 200, 0.01, UNIT_L, NumberDeviceClass.VOLUME, "mdi:gas-station"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CarStatsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CarStatsNumber(coordinator, key, mn, mx, step, unit, device_class, icon)
            for key, mn, mx, step, unit, device_class, icon in NUMBERS
        ]
    )


class CarStatsNumber(CarStatsEntity, RestoreNumber, NumberEntity):
    def __init__(
        self,
        coordinator: CarStatsCoordinator,
        key: str,
        mn: float,
        mx: float,
        step: float,
        unit: str,
        device_class: NumberDeviceClass,
        icon: str,
    ) -> None:
        super().__init__(coordinator, key, 'number')
        self._attr_native_min_value = mn
        self._attr_native_max_value = mx
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self) -> float:
        if self._key == "odometer":
            return self.coordinator.current_odometer()
        return float(self.coordinator.inputs.get(self._key) or 0)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        snap = self.coordinator.store.snapshot(self.entry.entry_id).get("inputs") or {}
        if snap.get(self._key) is not None:
            return
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self.coordinator.inputs[self._key] = float(last.native_value)

    async def async_set_native_value(self, value: float) -> None:
        if self._key == "odometer" and cfg_odometer_entity(self.entry):
            raise HomeAssistantError("已配置外部里程实体，请修改该实体")
        self.coordinator.inputs[self._key] = float(value)
        if self._key == "odometer":
            await self.coordinator.store.set_odometer(self.entry.entry_id, float(value))
        await self.coordinator.async_persist_snapshot()
        if self._key == "odometer":
            self.coordinator.push()
        self.async_write_ha_state()
