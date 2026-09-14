from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HOME_ZONES, CONF_PERSON, DOMAIN
from .coordinator import HomeTimeCoordinator, person_switch_id
from .entity import HomeTimeEntity
from .work_coordinator import WorkTimeCoordinator
from .work_entity import WorkTimeEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HomeTimeCoordinator = data["home"]
    entities: list[SwitchEntity] = []
    for person in coordinator.people:
        if person.get(CONF_HOME_ZONES) and person.get(CONF_PERSON):
            entities.append(AwaySwitch(coordinator, person))
    for work in (data.get("work") or {}).values():
        entities.append(WorkSwitch(work))
    async_add_entities(entities)


class AwaySwitch(HomeTimeEntity, SwitchEntity):
    _attr_translation_key = "away"
    _attr_icon = "mdi:home"

    def __init__(self, coordinator: HomeTimeCoordinator, person: dict) -> None:
        tracker = person[CONF_PERSON]
        super().__init__(
            coordinator,
            f"home_{tracker}",
            "switch",
            person_switch_id(person),
            f"{coordinator.entry.entry_id}_{tracker}",
            person.get("name") or coordinator.household_name,
        )
        self._tracker = tracker

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_away(self._tracker)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_away(self._tracker, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_away(self._tracker, False)


class WorkSwitch(WorkTimeEntity, SwitchEntity):
    _attr_icon = "mdi:briefcase"

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "work", "switch")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("is_working"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_working(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_working(False)
