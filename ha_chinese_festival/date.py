from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HolidayDailyCoordinator
from .entity import HolidayDailyEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: HolidayDailyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChineseFestivalTapDate(coordinator)])


class ChineseFestivalTapDate(HolidayDailyEntity, DateEntity):
    _attr_translation_key = "chinese_festival_tap"
    _attr_icon = "mdi:calendar-cursor"

    def __init__(self, coordinator: HolidayDailyCoordinator) -> None:
        super().__init__(
            coordinator, "chinese_festival_tap", "date", "chinese_festival_tap"
        )
        self._attr_native_value = dt_util.now().date()
        self._last_midnight = self._midnight_of(dt_util.now())
        self._unsub_midnight = None

    @staticmethod
    def _midnight_of(now: datetime) -> datetime:
        return now.replace(hour=0, minute=0, second=1, microsecond=0)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._schedule_midnight()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None
        await super().async_will_remove_from_hass()

    def _schedule_midnight(self) -> None:
        if self._unsub_midnight:
            self._unsub_midnight()
            self._unsub_midnight = None
        now = dt_util.now()
        nxt = self._midnight_of(now) + timedelta(days=1)
        self._unsub_midnight = async_track_point_in_time(
            self.hass, self._on_midnight, nxt
        )

    async def async_set_value(self, value: date) -> None:
        self._attr_native_value = value
        self.coordinator.set_tap_date(value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        grid = data.get("month_grid") or {}
        return {
            "selected_date": data.get("tap_date"),
            "month_grid": grid,
            "tap_solar": grid.get("tap_solar"),
            "tap_lunar": grid.get("tap_lunar"),
            "almanac": data.get("almanac") or {},
        }

    @callback
    def _on_midnight(self, now: datetime) -> None:
        local = dt_util.as_local(now)
        current = self._midnight_of(local)
        if current > self._last_midnight:
            self._last_midnight = current
            self._attr_native_value = local.date()
            self.coordinator.set_tap_date(local.date())
            self.async_write_ha_state()
            self.hass.async_create_task(self.coordinator.async_request_refresh())
        self._schedule_midnight()
