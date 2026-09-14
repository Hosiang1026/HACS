from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ALMANAC_KEYS,
    ALMANAC_MAIN,
    DOMAIN,
    NEXT_CATEGORIES,
    NEXT_OBJECT_IDS,
    STATE_HOLIDAY,
    STATE_REPAIR,
    STATE_REST,
    STATE_WEEKEND,
    STATE_WORKDAY,
)
from .coordinator import HolidayDailyCoordinator
from .entity import HolidayDailyEntity

PARALLEL_UPDATES = 0

_NEXT_ICONS = {
    "sftv": "mdi:calendar-sun",
    "lftv": "mdi:moon-waning-crescent",
    "term": "mdi:weather-partly-cloudy",
    "special": "mdi:calendar-star",
    "internation": "mdi:earth",
    "seasonal": "mdi:thermometer",
    "legal": "mdi:beach",
    "birthday": "mdi:cake-variant",
    "anniversary": "mdi:heart",
}

_ALMANAC_ICONS = {
    "suit": "mdi:thumb-up-outline",
    "avoid": "mdi:thumb-down-outline",
    "eight_char": "mdi:yin-yang",
    "hour": "mdi:clock-outline",
    "clash": "mdi:swap-horizontal",
    "moon_phase": "mdi:moon-waning-crescent",
    "solar_term": "mdi:weather-partly-cloudy",
    "taboo": "mdi:book-open-page-variant",
    "good_spirit": "mdi:shield-check",
    "bad_spirit": "mdi:shield-alert",
    "fetus": "mdi:baby-face-outline",
    "tone": "mdi:music-note",
    "triad": "mdi:circle-slice-3",
    "hexad": "mdi:circle-slice-6",
    "grade": "mdi:stairs",
    "zodiac_sign": "mdi:star-circle",
    "season": "mdi:flower",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HolidayDailyCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        HolidayDailySensor(coordinator),
        LicenseExpirySensor(coordinator),
        DayTypeSensor(coordinator),
        SolarDateSensor(coordinator),
        WeekdaySensor(coordinator),
        AstroSensor(coordinator),
        LunarDateSensor(coordinator),
        YearDaySensor(coordinator),
        FestivalCountSensor(coordinator),
        LicenseCountSensor(coordinator),
        BirthdayCountSensor(coordinator),
        AnniversaryCountSensor(coordinator),
        LoveDaysSensor(coordinator),
        HolidayPlanSensor(coordinator),
    ]
    entities.extend(
        NextCategorySensor(coordinator, category) for category in NEXT_CATEGORIES
    )
    entities.extend(AlmanacSensor(coordinator, key) for key in ALMANAC_KEYS)
    entities.append(AiFortuneSensor(coordinator))
    async_add_entities(entities)


class HolidayDailySensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "chinese_festival"
    _attr_icon = "mdi:calendar-star"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "chinese_festival", "sensor", "chinese_festival")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("next_days")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "next_name": data.get("next_name"),
            "content": data.get("festival_content"),
            "today": data.get("today"),
            "next": data.get("next"),
            "tips": data.get("tips"),
            "has_near_festival": data.get("has_near_festival"),
        }


class LicenseExpirySensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "license_expiry"
    _attr_icon = "mdi:card-account-details"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "license_expiry", "sensor", "license_expiry")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("nearest_license_days")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "items": data.get("license_items"),
            "near": data.get("license_near"),
            "content": data.get("license_content"),
            "has_near_license": data.get("has_near_license"),
        }


class DayTypeSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "day_type"
    _attr_icon = "mdi:calendar-check"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        STATE_WORKDAY,
        STATE_HOLIDAY,
        STATE_WEEKEND,
        STATE_REST,
        STATE_REPAIR,
    ]

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "day_type", "sensor", "day_type")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("day_type")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "name": data.get("day_name"),
            "freeway": data.get("freeway"),
            "holiday_day": data.get("holiday_day"),
        }


class SolarDateSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "solar_date"
    _attr_icon = "mdi:calendar"

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "solar_date", "sensor", "solar_date")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("solar_date")


class WeekdaySensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "weekday"
    _attr_icon = "mdi:calendar-week"

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "weekday", "sensor", "weekday")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("weekday")


class AstroSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "astro"
    _attr_icon = "mdi:star-circle"

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "astro", "sensor", "astro")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("astro")


class LunarDateSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "lunar_date"
    _attr_icon = "mdi:moon-waning-crescent"

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "lunar_date", "sensor", "lunar_date")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("lunar_date")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        lunar = data.get("lunar") or {}
        return {
            "gz_year": data.get("gz_year"),
            "gz_month": data.get("gz_month"),
            "gz_day": data.get("gz_day"),
            "animal": data.get("animal"),
            "l_year": lunar.get("lYear"),
            "l_month": lunar.get("lMonth"),
            "l_day": lunar.get("lDay"),
            "month_cn": lunar.get("IMonthCn"),
            "day_cn": lunar.get("IDayCn"),
            "is_leap": lunar.get("isLeap"),
            "term": data.get("term"),
        }


class YearDaySensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "year_day"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "year_day", "sensor", "year_day")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("year_day")


class FestivalCountSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "festival_count"
    _attr_icon = "mdi:calendar-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "festival_count", "sensor", "festival_count")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("count_festival")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return data.get("count_festival_detail") or {}


class LicenseCountSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "license_count"
    _attr_icon = "mdi:card-account-details-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "license_count", "sensor", "license_count")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("count_license")


class BirthdayCountSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "birthday_count"
    _attr_icon = "mdi:cake-variant"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "birthday_count", "sensor", "birthday_count")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("count_birthday")


class AnniversaryCountSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "anniversary_count"
    _attr_icon = "mdi:heart"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "anniversary_count", "sensor", "anniversary_count")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("count_anniversary")


class LoveDaysSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "love_days"
    _attr_icon = "mdi:heart-outline"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "love_days", "sensor", "love_days")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("love_days")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "name": data.get("love_name"),
            "items": data.get("love_items") or [],
            "content": data.get("love_content"),
        }


class HolidayPlanSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "holiday_plan"
    _attr_icon = "mdi:calendar-weekend"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "holiday_plan", "sensor", "holiday_plan")

    @property
    def native_value(self):
        plan = (self.coordinator.data or {}).get("holiday_plan") or {}
        return plan.get("days")

    @property
    def extra_state_attributes(self) -> dict:
        return (self.coordinator.data or {}).get("holiday_plan") or {}


class AlmanacSensor(HolidayDailyEntity, SensorEntity):
    def __init__(self, coordinator: HolidayDailyCoordinator, key: str) -> None:
        self._almanac_key = key
        super().__init__(coordinator, key, "sensor", key)
        self._attr_translation_key = key
        self._attr_icon = _ALMANAC_ICONS.get(key, "mdi:book-open-variant")
        if key not in ALMANAC_MAIN:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        almanac = (self.coordinator.data or {}).get("almanac") or {}
        return almanac.get(self._almanac_key)

    @property
    def extra_state_attributes(self) -> dict:
        if self._almanac_key != "moon_phase":
            return {}
        almanac = (self.coordinator.data or {}).get("almanac") or {}
        return almanac.get("moon_phase_attrs") or {}


class NextCategorySensor(HolidayDailyEntity, SensorEntity):
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HolidayDailyCoordinator, category: str) -> None:
        self._category = category
        object_id = NEXT_OBJECT_IDS[category]
        super().__init__(
            coordinator,
            object_id,
            "sensor",
            object_id,
        )
        self._attr_translation_key = object_id
        self._attr_icon = _NEXT_ICONS.get(category, "mdi:calendar")

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        item = (data.get("next_by_category") or {}).get(self._category) or {}
        return item.get("days")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        item = (data.get("next_by_category") or {}).get(self._category) or {}
        return {"next_name": item.get("name")}


class AiFortuneSensor(HolidayDailyEntity, SensorEntity):
    _attr_translation_key = "ai_fortune"
    _attr_icon = "mdi:crystal-ball"

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "ai_fortune", "sensor", "ai_fortune")

    @property
    def native_value(self):
        info = (self.coordinator.data or {}).get("ai_fortune") or {}
        if not info.get("enabled"):
            return "disabled"
        prediction = str(info.get("prediction") or "").strip()
        if not prediction:
            return "empty"
        return prediction[:80]

    @property
    def extra_state_attributes(self) -> dict:
        info = (self.coordinator.data or {}).get("ai_fortune") or {}
        return {
            "prediction": info.get("prediction") or "",
            "model": info.get("model") or "",
            "person": info.get("person") or "",
            "updated": info.get("updated") or "",
        }
