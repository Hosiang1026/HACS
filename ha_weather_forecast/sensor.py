from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.util import dt as dt_util

from .const import CONF_NAME, DEFAULT_NAME, DOMAIN, MANUFACTURER, VERSION
from .coordinators.update_stamp import coord_updated_at
from .coordinators.weather import WeatherCoordinator
from .entity import WeatherForecastEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    device_name = entry.title or entry.data.get(CONF_NAME) or DEFAULT_NAME

    entities.append(CreatedAtSensor(entry, device_name))

    for coord in data.get("cities") or []:
        slug = coord.slug
        entities.append(ModuleUpdatedSensor(coord, object_id=f"{slug}_updated_at"))
        entities.extend(
            [
                WeatherNumSensor(
                    coord, "temp", f"{slug}_temp", "weather_temp",
                    UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE,
                ),
                WeatherNumSensor(
                    coord, "feels", f"{slug}_feels", "weather_feels",
                    UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE,
                ),
                WeatherNumSensor(
                    coord, "humidity", f"{slug}_humidity", "weather_humidity",
                    PERCENTAGE, SensorDeviceClass.HUMIDITY,
                ),
                WeatherAqiSensor(coord, f"{slug}_aqi"),
                WeatherWindSensor(coord, f"{slug}_wind"),
                WeatherTextSensor(
                    coord, "indices", f"{slug}_indices", "weather_indices", "indices"
                ),
                WeatherTextSensor(
                    coord, "forecast", f"{slug}_forecast", "weather_forecast", "forecast"
                ),
            ]
        )

    async_add_entities(entities)


class CreatedAtSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "created_at"

    def __init__(self, entry: ConfigEntry, device_name: str) -> None:
        self._entry = entry
        self._object_id = "weather_created_at"
        self.entity_id = "sensor.weather_created_at"
        self._attr_suggested_object_id = "weather_created_at"
        self._attr_unique_id = f"{entry.entry_id}_created"
        self._attr_native_value = dt_util.utcnow()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=device_name,
            manufacturer=MANUFACTURER,
            sw_version=VERSION,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        wanted = f"sensor.{self._object_id}"
        if self.entity_id == wanted:
            return
        registry = async_get_entity_registry(self.hass)
        if registry.async_get(self.entity_id):
            try:
                registry.async_update_entity(self.entity_id, new_entity_id=wanted)
            except ValueError:
                pass


class ModuleUpdatedSensor(WeatherForecastEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: WeatherCoordinator, object_id: str) -> None:
        super().__init__(
            coordinator,
            key="updated_at",
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key="updated_at",
        )

    @property
    def native_value(self) -> datetime | None:
        return coord_updated_at(self.coordinator)


class WeatherNumSensor(WeatherForecastEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: WeatherCoordinator,
        data_key: str,
        object_id: str,
        translation_key: str,
        unit: str,
        device_class: SensorDeviceClass,
    ) -> None:
        super().__init__(
            coordinator,
            key=data_key,
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key=translation_key,
        )
        self._data_key = data_key
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._data_key)


class WeatherAqiSensor(WeatherForecastEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:air-filter"

    def __init__(self, coordinator: WeatherCoordinator, object_id: str) -> None:
        super().__init__(
            coordinator,
            key="aqi",
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key="weather_aqi",
        )

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("aqi")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sk = (self.coordinator.data or {}).get("raw_sk") or {}
        return {
            "pm25": sk.get("aqi_pm25") or sk.get("pm25"),
            "pm10": sk.get("aqi_pm10") or sk.get("pm10"),
            "update_time": (self.coordinator.data or {}).get("update_time"),
        }


class WeatherWindSensor(WeatherForecastEntity, SensorEntity):
    _attr_icon = "mdi:weather-windy"

    def __init__(self, coordinator: WeatherCoordinator, object_id: str) -> None:
        super().__init__(
            coordinator,
            key="wind",
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key="weather_wind",
        )

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        parts = [
            str(x)
            for x in (data.get("wind_dir"), data.get("wind_scale"))
            if x not in (None, "")
        ]
        return " ".join(parts) if parts else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "wind_dir": data.get("wind_dir"),
            "wind_scale": data.get("wind_scale"),
        }


class WeatherTextSensor(WeatherForecastEntity, SensorEntity):
    def __init__(
        self,
        coordinator: WeatherCoordinator,
        key: str,
        object_id: str,
        translation_key: str,
        attr_key: str,
    ) -> None:
        super().__init__(
            coordinator,
            key=key,
            platform="sensor",
            object_id=object_id,
            device_id=coordinator.device_id,
            device_name=coordinator.device_name,
            translation_key=translation_key,
        )
        self._attr_key = attr_key

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        if self._attr_key == "indices":
            indices = data.get("indices") or {}
            if isinstance(indices, dict) and indices:
                for key in ("ct", "uv", "yd", "gm"):
                    item = indices.get(key)
                    if isinstance(item, dict) and item.get("level"):
                        return f"{item.get('name') or key}:{item.get('level')}"
                first = next(iter(indices.values()))
                if isinstance(first, dict):
                    return first.get("level") or first.get("name")
                return str(first)
            return data.get("condition_desc")
        return data.get("forecast_summary") or data.get("condition_desc")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {self._attr_key: data.get(self._attr_key)}
