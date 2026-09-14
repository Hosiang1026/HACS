from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .work_coordinator import WorkTimeCoordinator
from .work_entity import WorkTimeEntity


def _to_dt(value: str) -> datetime:
    parts = (value or "00:00:00").split(":")
    now = dt_util.now()
    return now.replace(
        hour=int(parts[0]),
        minute=int(parts[1]),
        second=int(parts[2]) if len(parts) > 2 else 0,
        microsecond=0,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    work = hass.data[DOMAIN][entry.entry_id].get("work") or {}
    entities: list[DateTimeEntity] = []
    for coordinator in work.values():
        entities.extend(
            [WorkStartDateTime(coordinator), WorkEndDateTime(coordinator)]
        )
    async_add_entities(entities)


class WorkStartDateTime(WorkTimeEntity, DateTimeEntity):
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "work_start_time", "datetime")

    @property
    def native_value(self) -> datetime:
        return _to_dt((self.coordinator.data or {}).get("start_time", "00:00:00"))

    async def async_set_value(self, value: datetime) -> None:
        local = dt_util.as_local(value)
        await self.coordinator.async_set_start_time(local.strftime("%H:%M:%S"))


class WorkEndDateTime(WorkTimeEntity, DateTimeEntity):
    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "work_end_time", "datetime")

    @property
    def native_value(self) -> datetime:
        return _to_dt((self.coordinator.data or {}).get("end_time", "00:00:00"))

    async def async_set_value(self, value: datetime) -> None:
        local = dt_util.as_local(value)
        await self.coordinator.async_set_end_time(local.strftime("%H:%M:%S"))
