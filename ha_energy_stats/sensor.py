from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EnergyStatsCoordinator
from .entity import EnergyStatsEntity

_KWH = UnitOfEnergy.KILO_WATT_HOUR
_YUAN = "¥"
_YUAN_KWH = "¥/kWh"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: EnergyStatsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EnergyValueSensor(
                coordinator, "daily_peak_energy", "daily_peak",
                "mdi:lightning-bolt", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "daily_valley_energy", "daily_valley",
                "mdi:lightning-bolt-outline", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "daily_energy", "daily_energy",
                "mdi:lightning-bolt", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "daily_peak_cost", "daily_peak_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "daily_valley_cost", "daily_valley_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "daily_cost", "daily_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "monthly_peak_energy", "monthly_peak",
                "mdi:lightning-bolt", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "monthly_valley_energy", "monthly_valley",
                "mdi:lightning-bolt-outline", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "monthly_energy", "monthly_energy",
                "mdi:lightning-bolt", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "monthly_peak_cost", "monthly_peak_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "monthly_valley_cost", "monthly_valley_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "monthly_cost", "monthly_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "yearly_peak_energy", "yearly_peak",
                "mdi:lightning-bolt", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "yearly_valley_energy", "yearly_valley",
                "mdi:lightning-bolt-outline", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "yearly_energy", "yearly_energy",
                "mdi:lightning-bolt", SensorDeviceClass.ENERGY, _KWH, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "yearly_peak_cost", "yearly_peak_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "yearly_valley_cost", "yearly_valley_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "yearly_cost", "yearly_cost",
                "mdi:currency-cny", None, _YUAN, 2,
                SensorStateClass.TOTAL,
            ),
            EnergyValueSensor(
                coordinator, "current_tier", "tier",
                "mdi:stairs", None, None, 0, SensorStateClass.MEASUREMENT,
            ),
            EnergyValueSensor(
                coordinator, "peak_rate", "peak_rate",
                "mdi:cash", None, _YUAN_KWH, 4, SensorStateClass.MEASUREMENT,
            ),
            EnergyValueSensor(
                coordinator, "valley_rate", "valley_rate",
                "mdi:cash", None, _YUAN_KWH, 4, SensorStateClass.MEASUREMENT,
            ),
            EnergyValueSensor(
                coordinator, "realtime_rate", "realtime_rate",
                "mdi:cash-clock", None, _YUAN_KWH, 4, SensorStateClass.MEASUREMENT,
            ),
            DailyHistorySensor(coordinator),
            MonthlyHistorySensor(coordinator),
            YearlyHistorySensor(coordinator),
        ]
    )


class EnergyValueSensor(EnergyStatsEntity, SensorEntity):
    def __init__(
        self,
        coordinator: EnergyStatsCoordinator,
        key: str,
        data_key: str,
        icon: str,
        device_class: SensorDeviceClass | None,
        unit: str | None,
        precision: int,
        state_class: SensorStateClass | None,
    ) -> None:
        super().__init__(coordinator, key, "sensor")
        self._data_key = data_key
        self._attr_icon = icon
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit
        self._attr_suggested_display_precision = precision
        self._attr_state_class = state_class

    @property
    def native_value(self) -> float | int:
        value = (self.coordinator.data or {}).get(self._data_key, 0)
        if self._data_key == "tier":
            return int(value or 1)
        return 0 if value is None else value


class DailyHistorySensor(EnergyStatsEntity, SensorEntity):
    _attr_icon = "mdi:calendar-week"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: EnergyStatsCoordinator) -> None:
        super().__init__(coordinator, "daily_history", "sensor")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("daily_history_count", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        days = (self.coordinator.data or {}).get("daily_history") or []
        attrs: dict[str, Any] = {"days": days, "dayList": days}
        for item in days:
            day = item.get("date") or item.get("day")
            if day:
                attrs[day] = item
        return attrs


class MonthlyHistorySensor(EnergyStatsEntity, SensorEntity):
    _attr_icon = "mdi:calendar-month"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: EnergyStatsCoordinator) -> None:
        super().__init__(coordinator, "monthly_history", "sensor")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("history_count", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        history = (self.coordinator.data or {}).get("history") or []
        attrs: dict[str, Any] = {"months": history, "monthList": history}
        for item in history:
            month = item.get("month")
            if month:
                attrs[month] = item
        return attrs


class YearlyHistorySensor(EnergyStatsEntity, SensorEntity):
    _attr_icon = "mdi:calendar-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: EnergyStatsCoordinator) -> None:
        super().__init__(coordinator, "yearly_history", "sensor")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("yearly_history_count", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        years = (self.coordinator.data or {}).get("yearly_history") or []
        attrs: dict[str, Any] = {"years": years, "yearList": years}
        for item in years:
            year = item.get("year")
            if year:
                attrs[str(year)] = item
        return attrs
