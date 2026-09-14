from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .work_coordinator import WorkTimeCoordinator
from .work_entity import WorkTimeEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    work = hass.data[DOMAIN][entry.entry_id].get("work") or {}
    entities: list[NumberEntity] = []
    for coordinator in work.values():
        entities.extend(
            [CompTimeNumber(coordinator), MonthSalaryNumber(coordinator)]
        )
    async_add_entities(entities)


class CompTimeNumber(WorkTimeEntity, NumberEntity):
    _attr_icon = "mdi:dots-circle"
    _attr_native_min_value = 0
    _attr_native_max_value = 100000
    _attr_native_step = 0.01
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.HOURS

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "comp_time", "number")

    @property
    def native_value(self) -> float:
        return float((self.coordinator.data or {}).get("comp_time", 0))

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_comp_time(value)


class MonthSalaryNumber(WorkTimeEntity, NumberEntity):
    _attr_icon = "mdi:cash"
    _attr_native_min_value = 0
    _attr_native_max_value = 1000000
    _attr_native_step = 0.01
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "month_salary", "number")

    @property
    def native_value(self) -> float:
        return float((self.coordinator.data or {}).get("month_salary", 0))

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_month_salary(value)
