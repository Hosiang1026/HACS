from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HolidayDailyCoordinator
from .entity import HolidayDailyEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HolidayDailyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            IsHolidayBinarySensor(coordinator),
            IsRepairBinarySensor(coordinator),
        ]
    )


class IsHolidayBinarySensor(HolidayDailyEntity, BinarySensorEntity):
    _attr_translation_key = "is_holiday"
    _attr_icon = "mdi:beach"

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "is_holiday", "binary_sensor", "is_holiday")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("is_holiday"))


class IsRepairBinarySensor(HolidayDailyEntity, BinarySensorEntity):
    _attr_translation_key = "is_repair"
    _attr_icon = "mdi:briefcase-clock"

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(coordinator, "is_repair", "binary_sensor", "is_repair")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("is_repair"))
