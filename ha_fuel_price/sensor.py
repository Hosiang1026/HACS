from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    CODE_TO_NAME,
    CONF_FILL_LITERS,
    CONF_PROVINCE_CODE,
    CONF_PROVINCE_NAME,
    DEFAULT_FILL_LITERS,
    DOMAIN,
    FUEL_ICONS,
    FUEL_TYPES,
    normalize_fill_liters,
)
from .coordinator import FuelPriceCoordinator
from .entity import FuelPriceEntity
from .localize import tr

_UNIT_CNY_L = "CNY/L"
_UNIT_CNY = "CNY"
_TREND_STATE_MAX = 255


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FuelPriceCoordinator = hass.data[DOMAIN][entry.entry_id]
    fill_liters = normalize_fill_liters(
        entry.options.get(CONF_FILL_LITERS, DEFAULT_FILL_LITERS)
    )
    entities: list[SensorEntity] = [
        CreatedAtSensor(coordinator),
        UpdateTimeSensor(coordinator),
        TrendSensor(coordinator),
    ]
    for province in coordinator.provinces:
        code = province.get(CONF_PROVINCE_CODE)
        if not code:
            continue
        name = province.get(CONF_PROVINCE_NAME) or CODE_TO_NAME.get(code, code)
        for fuel in FUEL_TYPES:
            entities.append(FuelPriceSensor(coordinator, code, name, fuel))
        entities.append(FuelLowDateSensor(coordinator, code, name))
        for fuel in FUEL_TYPES:
            entities.append(FuelLowSensor(coordinator, code, name, fuel))
        if fill_liters > 0:
            for fuel in FUEL_TYPES:
                entities.append(
                    FuelFillCostSensor(coordinator, code, name, fuel, fill_liters)
                )
    async_add_entities(entities)


class CreatedAtSensor(FuelPriceEntity, SensorEntity):
    _attr_translation_key = "created_at"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-plus"

    def __init__(self, coordinator: FuelPriceCoordinator) -> None:
        super().__init__(coordinator, "created_at", "fuel_price_created_time")

    @property
    def native_value(self) -> datetime | None:
        raw = self.coordinator.entry.data.get("created_at")
        if not raw:
            return None
        return dt_util.parse_datetime(str(raw))


class UpdateTimeSensor(FuelPriceEntity, SensorEntity):
    _attr_translation_key = "update_time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator: FuelPriceCoordinator) -> None:
        super().__init__(coordinator, "update_time", "fuel_price_update_time")

    @property
    def native_value(self) -> datetime | None:
        return (self.coordinator.data or {}).get("update_time")


class TrendSensor(FuelPriceEntity, SensorEntity):
    _attr_translation_key = "trend"
    _attr_icon = "mdi:trending-up"

    def __init__(self, coordinator: FuelPriceCoordinator) -> None:
        super().__init__(coordinator, "trend", "fuel_price_trend")

    @property
    def native_value(self) -> str | None:
        trend = str((self.coordinator.data or {}).get("trend") or "").strip()
        if not trend:
            return None
        if len(trend) <= _TREND_STATE_MAX:
            return trend
        return trend[: _TREND_STATE_MAX - 1] + "…"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"full_text": str((self.coordinator.data or {}).get("trend") or "")}


class FuelPriceSensor(FuelPriceEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = _UNIT_CNY_L
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: FuelPriceCoordinator,
        code: str,
        name: str,
        fuel: str,
    ) -> None:
        slug = code.replace("-", "_")
        super().__init__(
            coordinator,
            f"{code}_{fuel}",
            f"{slug}_fuel_price_{fuel}",
            f"{coordinator.entry.entry_id}_{code}",
            name,
        )
        self._code = code
        self._name = name
        self._fuel = fuel
        self._attr_translation_key = f"fuel_{fuel}"
        self._attr_icon = FUEL_ICONS.get(fuel, "mdi:gas-station")

    @property
    def native_value(self) -> float | None:
        province = ((self.coordinator.data or {}).get("provinces") or {}).get(
            self._code
        ) or {}
        value = province.get(self._fuel)
        return float(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        update_time = (self.coordinator.data or {}).get("update_time")
        return {
            "province": self._name,
            "fuel_type": tr(self.hass, f"fuel_{self._fuel}"),
            "update_time": (
                dt_util.as_local(update_time).isoformat()
                if isinstance(update_time, datetime)
                else None
            ),
        }


class FuelLowSensor(FuelPriceEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = _UNIT_CNY_L
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:trending-down"

    def __init__(
        self,
        coordinator: FuelPriceCoordinator,
        code: str,
        name: str,
        fuel: str,
    ) -> None:
        slug = code.replace("-", "_")
        super().__init__(
            coordinator,
            f"{code}_{fuel}_low",
            f"{slug}_fuel_price_{fuel}_low",
            f"{coordinator.entry.entry_id}_{code}",
            name,
        )
        self._code = code
        self._name = name
        self._fuel = fuel
        self._attr_translation_key = f"fuel_{fuel}_low"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.low_price(self._code, self._fuel)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {
            "province": self._name,
            "fuel_type": tr(self.hass, f"fuel_{self._fuel}"),
            "low_date": self.coordinator.low_date(self._code),
        }


class FuelLowDateSensor(FuelPriceEntity, SensorEntity):
    _attr_translation_key = "fuel_low_date"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-star"

    def __init__(
        self, coordinator: FuelPriceCoordinator, code: str, name: str
    ) -> None:
        slug = code.replace("-", "_")
        super().__init__(
            coordinator,
            f"{code}_low_date",
            f"{slug}_fuel_price_low_date",
            f"{coordinator.entry.entry_id}_{code}",
            name,
        )
        self._code = code
        self._name = name

    @property
    def native_value(self) -> date | None:
        raw = self.coordinator.low_date(self._code)
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        attrs: dict[str, str | float | None] = {"province": self._name}
        for fuel in FUEL_TYPES:
            attrs[f"low_{fuel}"] = self.coordinator.low_price(self._code, fuel)
        return attrs


class FuelFillCostSensor(FuelPriceEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = _UNIT_CNY
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash"

    def __init__(
        self,
        coordinator: FuelPriceCoordinator,
        code: str,
        name: str,
        fuel: str,
        liters: float,
    ) -> None:
        slug = code.replace("-", "_")
        super().__init__(
            coordinator,
            f"{code}_{fuel}_cost",
            f"{slug}_fuel_price_{fuel}_cost",
            f"{coordinator.entry.entry_id}_{code}",
            name,
        )
        self._code = code
        self._name = name
        self._fuel = fuel
        self._liters = liters
        self._attr_translation_key = f"fuel_{fuel}_cost"

    @property
    def native_value(self) -> float | None:
        province = ((self.coordinator.data or {}).get("provinces") or {}).get(
            self._code
        ) or {}
        price = province.get(self._fuel)
        if price is None:
            return None
        try:
            return round(float(price) * self._liters, 2)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, str | float | None]:
        province = ((self.coordinator.data or {}).get("provinces") or {}).get(
            self._code
        ) or {}
        price = province.get(self._fuel)
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        return {
            "province": self._name,
            "fuel_type": tr(self.hass, f"fuel_{self._fuel}"),
            "fill_liters": self._liters,
            "unit_price": price_f,
        }
