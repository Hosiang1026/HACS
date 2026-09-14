from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SceneCoordinator
from .entity import RuleEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SceneCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = [
        RuleEnabledSwitch(coordinator, rule) for rule in coordinator.rules
    ]
    async_add_entities(entities)


class RuleEnabledSwitch(RuleEntity, SwitchEntity):
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, coordinator: SceneCoordinator, rule: dict) -> None:
        super().__init__(coordinator, rule, "rule_enabled", "switch", "启用")

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_rule_enabled(self._rule_id)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_rule_enabled(self._rule_id, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_rule_enabled(self._rule_id, False)
