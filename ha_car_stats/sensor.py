from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .amap_sensor import create_amap_sensors
from .const import (
    CONF_LOGIN_AT,
    DOMAIN,
    UNIT_CNY,
    UNIT_CNY_PER_KM,
    UNIT_CNY_PER_L,
    UNIT_DAY,
    UNIT_KM,
    UNIT_L,
    UNIT_L_PER_100KM,
    UNIT_YEAR,
)
from .coordinator import CarStatsCoordinator
from .entity import CarStatsEntity
from .helpers import (
    cfg_12123,
    cfg_amap,
    cfg_insurance_expiry,
    cfg_inspect_expiry,
    cfg_maint_date,
    cfg_purchase_date,
    cfg_battery_replace_date,
)

STAT_SENSORS = (
    ("avg_consumption", UNIT_L_PER_100KM, "mdi:speedometer", None, SensorStateClass.MEASUREMENT),
    ("consumption_rating", None, "mdi:emoticon-neutral-outline", None, None),
    ("last_refuel_liters", UNIT_L, "mdi:fuel", SensorDeviceClass.VOLUME, None),
    ("last_refuel_cost", UNIT_CNY, "mdi:cash", SensorDeviceClass.MONETARY, None),
    ("fuel_price", UNIT_CNY_PER_L, "mdi:currency-cny", None, SensorStateClass.MEASUREMENT),
    ("monthly_fuel_cost", UNIT_CNY, "mdi:gas-station-outline", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL),
    ("yearly_fuel_cost", UNIT_CNY, "mdi:chart-bar", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL),
    ("monthly_etc_cost", UNIT_CNY, "mdi:highway", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL),
    ("yearly_total_cost", UNIT_CNY, "mdi:cash-multiple", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL),
    ("cost_per_km", UNIT_CNY_PER_KM, "mdi:map-marker-distance", None, SensorStateClass.MEASUREMENT),
    ("driving_odometer", UNIT_KM, "mdi:counter", SensorDeviceClass.DISTANCE, SensorStateClass.TOTAL_INCREASING),
)

USAGE_TIME_SENSOR = ("usage_time", UNIT_YEAR, "mdi:car-clock", None, SensorStateClass.MEASUREMENT)
BATTERY_USAGE_TIME_SENSOR = ("battery_usage_time", UNIT_YEAR, "mdi:car-battery", None, SensorStateClass.MEASUREMENT)
INSURANCE_DAYS_SENSOR = ("insurance_days", UNIT_DAY, "mdi:shield-car", SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT)
INSPECTION_DAYS_SENSOR = ("inspection_days", UNIT_DAY, "mdi:calendar-check", SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT)
MAINT_SENSORS = (
    ("km_until_maint", UNIT_KM, "mdi:car-wrench", SensorDeviceClass.DISTANCE, SensorStateClass.MEASUREMENT),
    ("days_until_maint", UNIT_DAY, "mdi:calendar-clock", SensorDeviceClass.DURATION, SensorStateClass.MEASUREMENT),
)

RATING_ICONS = {
    "优秀": "mdi:emoticon-excited-outline",
    "良好": "mdi:emoticon-happy-outline",
    "正常": "mdi:emoticon-neutral-outline",
    "偏高": "mdi:emoticon-sad-outline",
    "费油": "mdi:emoticon-cry-outline",
    "未知": "mdi:car-speed-limiter",
}

_TRANSLATED_UNIT_KEYS = frozenset(
    {"avg_consumption", "fuel_price", "cost_per_km", "usage_time", "battery_usage_time"}
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CarStatsCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        CarStatsValueSensor(coordinator, key, unit, icon, device_class, state_class)
        for key, unit, icon, device_class, state_class in STAT_SENSORS
    ]
    if cfg_purchase_date(entry):
        key, unit, icon, device_class, state_class = USAGE_TIME_SENSOR
        entities.append(CarStatsValueSensor(coordinator, key, unit, icon, device_class, state_class))
    if cfg_battery_replace_date(entry):
        key, unit, icon, device_class, state_class = BATTERY_USAGE_TIME_SENSOR
        entities.append(CarStatsValueSensor(coordinator, key, unit, icon, device_class, state_class))
    if cfg_insurance_expiry(entry):
        key, unit, icon, device_class, state_class = INSURANCE_DAYS_SENSOR
        entities.append(CarStatsValueSensor(coordinator, key, unit, icon, device_class, state_class))
    if cfg_inspect_expiry(entry):
        key, unit, icon, device_class, state_class = INSPECTION_DAYS_SENSOR
        entities.append(CarStatsValueSensor(coordinator, key, unit, icon, device_class, state_class))
    if cfg_maint_date(entry):
        for key, unit, icon, device_class, state_class in MAINT_SENSORS:
            entities.append(CarStatsValueSensor(coordinator, key, unit, icon, device_class, state_class))
    entities.append(CarStatsYearlyRefuelsSensor(coordinator))
    entities.append(CarStatsYearlyHistorySensor(coordinator))
    if cfg_12123(entry):
        entities.extend(
            [
                CarStatsPlateSensor(coordinator),
                CarStatsVehicleTypeSensor(coordinator),
                CarStatsVehicleStatusSensor(coordinator),
                CarStatsLicenseTypeSensor(coordinator),
                CarStatsLicenseStatusSensor(coordinator),
                CarStatsLicensePointsSensor(coordinator),
                CarStatsLicenseClearSensor(coordinator),
                CarStatsLicenseExpirySensor(coordinator),
                CarStatsViolationsSensor(coordinator),
                CarStatsSessionSensor(coordinator),
                CarStatsLoginTimeSensor(coordinator),
            ]
        )
    if cfg_amap(entry):
        amap = getattr(coordinator, "amap_coordinator", None)
        if amap:
            entities.extend(create_amap_sensors(coordinator, amap))
    async_add_entities(entities)


class CarStatsValueSensor(CarStatsEntity, SensorEntity):
    def __init__(
        self,
        coordinator: CarStatsCoordinator,
        key: str,
        unit: str | None,
        icon: str,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
    ) -> None:
        super().__init__(coordinator, key, 'sensor')
        if unit and key not in _TRANSLATED_UNIT_KEYS:
            self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class
        if state_class:
            self._attr_state_class = state_class

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("stats", {}).get(self._key)

    @property
    def icon(self) -> str:
        if self._key == "consumption_rating":
            return RATING_ICONS.get(str(self.native_value), "mdi:car-speed-limiter")
        return self._attr_icon


class CarStatsYearlyRefuelsSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "yearly_refuels", 'sensor')
        self._attr_icon = "mdi:gas-station"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        records = (self.coordinator.data or {}).get("stats", {}).get("yearly_refuels") or []
        return len(records)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        records = (self.coordinator.data or {}).get("stats", {}).get("yearly_refuels") or []
        attrs: dict[str, Any] = {"本年加油次数": len(records)}
        for i, rec in enumerate(records, 1):
            attrs[f"记录{i}_日期"] = rec.get("date")
            attrs[f"记录{i}_费用"] = rec.get("cost")
            if rec.get("liters") is not None:
                attrs[f"记录{i}_升数"] = rec["liters"]
            attrs[f"记录{i}_里程"] = rec.get("odometer")
            if rec.get("station"):
                attrs[f"记录{i}_加油站"] = rec["station"]
        return attrs


class CarStatsYearlyHistorySensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "yearly_history", 'sensor')
        self._attr_icon = "mdi:calendar-multiselect"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        records = (self.coordinator.data or {}).get("stats", {}).get("yearly_history") or []
        return len(records)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        records = (self.coordinator.data or {}).get("stats", {}).get("yearly_history") or []
        attrs: dict[str, Any] = {"统计年数": len(records)}
        for rec in records:
            year = rec.get("year")
            if year is None:
                continue
            attrs[f"{year}_总费用"] = rec.get("cost")
            attrs[f"{year}_总里程"] = rec.get("km")
        return attrs


class CarStatsPlateSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "plate", 'sensor')
        self._attr_icon = "mdi:card-text-outline"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("vehicle", {}).get("plate")


class CarStatsVehicleTypeSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "vehicle_type", 'sensor')
        self._attr_icon = "mdi:car-info"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("vehicle", {}).get("type")


class CarStatsVehicleStatusSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "vehicle_status", 'sensor')
        self._attr_icon = "mdi:car"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("vehicle", {}).get("status")


class CarStatsLicenseTypeSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "license_type", 'sensor')
        self._attr_icon = "mdi:card-account-details"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("license", {}).get("type")


class CarStatsLicenseStatusSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "license_status", 'sensor')
        self._attr_icon = "mdi:account-check"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("license", {}).get("status")


class CarStatsLicensePointsSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "license_points", 'sensor')
        self._attr_icon = "mdi:numeric-10-box-outline"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("license", {}).get("points")


class CarStatsLicenseClearSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "license_clear", 'sensor')
        self._attr_icon = "mdi:calendar-refresh"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("license", {}).get("clear")


class CarStatsLicenseExpirySensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "license_expiry", 'sensor')
        self._attr_icon = "mdi:calendar-end"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("license", {}).get("expiry")


class CarStatsViolationsSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "violations", 'sensor')
        self._attr_icon = "mdi:alert-octagon"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("violations", {}).get("count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        records = (self.coordinator.data or {}).get("violations", {}).get("records") or []
        attrs: dict[str, Any] = {"监控记录总数": len(records)}
        for i, rec in enumerate(records, 1):
            if rec.get("plate"):
                attrs[f"记录{i}_车牌号"] = rec["plate"]
            if rec.get("time"):
                attrs[f"记录{i}_时间"] = rec["time"]
            if rec.get("location"):
                attrs[f"记录{i}_地点"] = rec["location"]
            if rec.get("behavior"):
                attrs[f"记录{i}_行为"] = rec["behavior"]
            if rec.get("fine") is not None:
                attrs[f"记录{i}_罚款"] = rec["fine"]
            if rec.get("points") is not None:
                attrs[f"记录{i}_记分"] = rec["points"]
        return attrs


class CarStatsSessionSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "session", 'sensor')
        self._attr_icon = "mdi:shield-check"

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get("session", {}).get("state")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        session = (self.coordinator.data or {}).get("session") or {}
        attrs = {"登录状态": session.get("state")}
        if session.get("error"):
            attrs["失败原因"] = session["error"]
        if session.get("message"):
            attrs["说明"] = session["message"]
        return attrs


class CarStatsLoginTimeSensor(CarStatsEntity, SensorEntity):
    def __init__(self, coordinator: CarStatsCoordinator) -> None:
        super().__init__(coordinator, "login_time", 'sensor')
        self._attr_icon = "mdi:clock-check-outline"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> Any:
        raw = self.entry.data.get(CONF_LOGIN_AT)
        if not raw:
            return None
        parsed = dt_util.parse_datetime(str(raw))
        if not parsed:
            return None
        return dt_util.as_utc(parsed)
