from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import (
    SceneCoordinator,
    rule_extra_condition_text,
    rule_trigger_condition_text,
)
from .entity import RuleEntity, SceneEntity

_SCENE_STATS: tuple[tuple[str, str], ...] = (
    ("enabled_count", "mdi:toggle-switch"),
    ("disabled_count", "mdi:toggle-switch-off"),
    ("today_success", "mdi:calendar-check"),
    ("today_fail", "mdi:calendar-remove"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SceneCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = [
        SceneStatSensor(coordinator, key, icon) for key, icon in _SCENE_STATS
    ]
    for rule in coordinator.rules:
        entities.extend(
            [
                RuleTriggerConditionSensor(coordinator, rule),
                RuleExtraConditionSensor(coordinator, rule),
                RuleExecStateSensor(coordinator, rule),
                RuleExecTimeSensor(coordinator, rule),
            ]
        )
    async_add_entities(entities)


class SceneStatSensor(SceneEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: SceneCoordinator, data_key: str, icon: str
    ) -> None:
        super().__init__(coordinator, data_key, "sensor")
        self._data_key = data_key
        self._attr_translation_key = data_key
        self._attr_icon = icon

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get(self._data_key, 0))


class RuleTriggerConditionSensor(RuleEntity, SensorEntity):
    _attr_icon = "mdi:filter-check"

    def __init__(self, coordinator: SceneCoordinator, rule: dict) -> None:
        super().__init__(coordinator, rule, "rule_condition", "sensor", "触发条件")

    @property
    def native_value(self) -> str:
        rule = self._rule()
        if rule:
            return rule_trigger_condition_text(rule)
        return self._rule_data().get("trigger_condition") or "—"


class RuleExtraConditionSensor(RuleEntity, SensorEntity):
    _attr_icon = "mdi:filter-variant"

    def __init__(self, coordinator: SceneCoordinator, rule: dict) -> None:
        super().__init__(coordinator, rule, "rule_extra", "sensor", "附加条件")

    @property
    def native_value(self) -> str:
        rule = self._rule()
        if rule:
            return rule_extra_condition_text(rule)
        return self._rule_data().get("extra_condition") or "无"


class RuleExecStateSensor(RuleEntity, SensorEntity):
    _attr_icon = "mdi:check-circle-outline"

    def __init__(self, coordinator: SceneCoordinator, rule: dict) -> None:
        super().__init__(coordinator, rule, "rule_exec_state", "sensor", "执行状态")

    @property
    def native_value(self) -> str:
        return self._rule_data().get("exec_state") or "—"


class RuleExecTimeSensor(RuleEntity, SensorEntity):
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: SceneCoordinator, rule: dict) -> None:
        super().__init__(coordinator, rule, "rule_exec_time", "sensor", "执行时间")

    @property
    def native_value(self) -> str | None:
        return self._rule_data().get("exec_time")
