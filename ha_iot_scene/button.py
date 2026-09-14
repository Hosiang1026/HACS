from homeassistant.components.button import ButtonEntity
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
    async_add_entities(
        [RuleManualTriggerButton(coordinator, rule) for rule in coordinator.rules]
    )


class RuleManualTriggerButton(RuleEntity, ButtonEntity):
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator: SceneCoordinator, rule: dict) -> None:
        super().__init__(coordinator, rule, "rule_manual", "button", "手动触发")

    async def async_press(self) -> None:
        await self.coordinator.async_manual_trigger(self._rule_id)
