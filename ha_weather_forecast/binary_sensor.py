from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinators.weather import WeatherCoordinator
from .entity import WeatherForecastEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[BinarySensorEntity] = []
    for coord in data.get("cities") or []:
        entities.append(WeatherAlarmBinary(coord))
    async_add_entities(entities)


class WeatherAlarmBinary(WeatherForecastEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    def __init__(self, coordinator: WeatherCoordinator) -> None:
        super().__init__(
            coordinator,
            key="alarm",
            platform="binary_sensor",
            object_id=f"{coordinator.slug}_alarm",
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key="weather_alarm",
        )

    @property
    def is_on(self) -> bool:
        alarms = (self.coordinator.data or {}).get("alarms") or []
        return bool(alarms)

    @property
    def extra_state_attributes(self) -> dict:
        return {"alarms": (self.coordinator.data or {}).get("alarms") or []}
