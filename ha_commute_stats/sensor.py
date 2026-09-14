from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ACTIVITY_AWAY,
    ACTIVITY_COMPANY,
    ACTIVITY_HOME,
    ACTIVITY_OUT,
    CONF_HOME_ZONES,
    CONF_PERSON,
    DOMAIN,
    STATE_HOLIDAY,
    STATE_LUNCH,
    STATE_OFF,
    STATE_OVERTIME,
    STATE_REST,
    STATE_WORKING,
)
from .coordinator import HomeTimeCoordinator, person_activity_id, person_duration_id
from .entity import HomeTimeEntity
from .work_coordinator import WorkTimeCoordinator
from .work_entity import WorkTimeEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HomeTimeCoordinator = data["home"]
    entities: list[SensorEntity] = [
        PeopleCountSensor(coordinator, "home_count", "people_home_count", "mdi:home-account"),
        PeopleCountSensor(coordinator, "comp_count", "people_comp_count", "mdi:office-building"),
        PeopleCountSensor(coordinator, "waidi_count", "people_waidi_count", "mdi:airplane"),
        PeopleCountSensor(coordinator, "out_count", "people_out_count", "mdi:walk"),
    ]
    for person in coordinator.people:
        if person.get(CONF_PERSON):
            entities.append(ActivitySensor(coordinator, person))
        if person.get(CONF_PERSON) and person.get(CONF_HOME_ZONES):
            entities.append(HomeDurationSensor(coordinator, person))
    for work in (data.get("work") or {}).values():
        entities.extend(
            [
                WorkDurationSensor(work),
                WorkTimeSensor(work),
                OverTimeSensor(work),
                WorkStateSensor(work),
            ]
        )
    async_add_entities(entities)


class PeopleCountSensor(HomeTimeEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: HomeTimeCoordinator,
        data_key: str,
        object_id: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, data_key, "sensor", object_id)
        self._data_key = data_key
        self._attr_translation_key = data_key
        self._attr_icon = icon

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get(self._data_key, 0))


class HomeDurationSensor(HomeTimeEntity, SensorEntity):
    _attr_translation_key = "home_duration"
    _attr_icon = "mdi:home-clock"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: HomeTimeCoordinator, person: dict) -> None:
        tracker = person[CONF_PERSON]
        super().__init__(
            coordinator,
            f"home_duration_{tracker}",
            "sensor",
            person_duration_id(person),
            f"{coordinator.entry.entry_id}_{tracker}",
            person.get("name") or coordinator.household_name,
        )
        self._tracker = tracker

    @property
    def native_value(self) -> float:
        return self.coordinator.home_duration(self._tracker)


class ActivitySensor(HomeTimeEntity, SensorEntity):
    _attr_translation_key = "activity"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [ACTIVITY_HOME, ACTIVITY_COMPANY, ACTIVITY_OUT, ACTIVITY_AWAY]
    _ICONS = {
        ACTIVITY_HOME: "mdi:home-account",
        ACTIVITY_COMPANY: "mdi:office-building",
        ACTIVITY_OUT: "mdi:walk",
        ACTIVITY_AWAY: "mdi:airplane",
    }

    def __init__(self, coordinator: HomeTimeCoordinator, person: dict) -> None:
        tracker = person[CONF_PERSON]
        super().__init__(
            coordinator,
            f"activity_{tracker}",
            "sensor",
            person_activity_id(person),
            f"{coordinator.entry.entry_id}_{tracker}",
            person.get("name") or coordinator.household_name,
        )
        self._tracker = tracker

    @property
    def native_value(self) -> str:
        return self.coordinator.activity(self._tracker)

    @property
    def icon(self) -> str:
        return self._ICONS.get(self.native_value, "mdi:account")


class WorkDurationSensor(WorkTimeEntity, SensorEntity):
    _attr_icon = "mdi:briefcase"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "work_duration", "sensor")

    @property
    def native_value(self) -> float:
        return (self.coordinator.data or {}).get("duration", 0)


class WorkTimeSensor(WorkTimeEntity, SensorEntity):
    _attr_icon = "mdi:briefcase"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "work_time", "sensor")

    @property
    def native_value(self) -> float:
        return (self.coordinator.data or {}).get("work_time", 0)


class OverTimeSensor(WorkTimeEntity, SensorEntity):
    _attr_icon = "mdi:account-hard-hat"
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "over_time", "sensor")

    @property
    def native_value(self) -> float:
        return (self.coordinator.data or {}).get("over_time", 0)


class WorkStateSensor(WorkTimeEntity, SensorEntity):
    _attr_icon = "mdi:clipboard-text-clock"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        STATE_HOLIDAY,
        STATE_REST,
        STATE_OFF,
        STATE_LUNCH,
        STATE_OVERTIME,
        STATE_WORKING,
    ]

    def __init__(self, coordinator: WorkTimeCoordinator) -> None:
        super().__init__(coordinator, "work_state", "sensor")

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("work_state", STATE_REST)
