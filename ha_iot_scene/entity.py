from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_RULE_ID, CONF_RULE_NAME, CONF_RULE_ROOM, DOMAIN
from .coordinator import SceneCoordinator, rule_entity_key


def _rule_device_info(
    coordinator: SceneCoordinator, rule: dict
) -> DeviceInfo:
    rule_name = rule.get(CONF_RULE_NAME) or "规则"
    room = (rule.get(CONF_RULE_ROOM) or "").strip()
    info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.entry.entry_id, rule[CONF_RULE_ID])},
        name=rule_name,
        manufacturer="狂欢马克思",
        model="智能场景",
        suggested_area=room or None,
    )
    return info


class SceneEntity(CoordinatorEntity[SceneCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: SceneCoordinator, key: str, domain: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = key
        prefix = coordinator.entity_prefix
        self._object_id = f"{prefix}_{key}"
        self.entity_id = f"{domain}.{self._object_id}"
        self._attr_suggested_object_id = self._object_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{domain}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="场景统计",
            manufacturer="狂欢马克思",
            model="智能场景",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        wanted = f"{self.platform.domain}.{self._object_id}"
        if self.entity_id == wanted:
            return
        registry = async_get_entity_registry(self.hass)
        if registry.async_get(self.entity_id):
            try:
                registry.async_update_entity(self.entity_id, new_entity_id=wanted)
            except ValueError:
                pass


class RuleEntity(CoordinatorEntity[SceneCoordinator]):
    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: SceneCoordinator,
        rule: dict,
        key: str,
        domain: str,
        name_suffix: str,
    ) -> None:
        super().__init__(coordinator)
        self._rule_id = rule[CONF_RULE_ID]
        self._data_key = key
        entity_key = rule_entity_key(rule)
        rule_name = rule.get(CONF_RULE_NAME) or "规则"
        self._attr_name = f"{rule_name} {name_suffix}"
        prefix = coordinator.entity_prefix
        self._object_id = f"{prefix}_{entity_key}_{key}"
        self.entity_id = f"{domain}.{self._object_id}"
        self._attr_suggested_object_id = self._object_id
        self._attr_unique_id = (
            f"{coordinator.entry.entry_id}_{domain}_{rule[CONF_RULE_ID]}_{key}"
        )
        self._attr_device_info = _rule_device_info(coordinator, rule)

    def _rule(self) -> dict | None:
        return next(
            (r for r in self.coordinator.rules if r[CONF_RULE_ID] == self._rule_id),
            None,
        )

    def _rule_data(self) -> dict:
        return (self.coordinator.data or {}).get("rules", {}).get(self._rule_id, {})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        wanted = f"{self.platform.domain}.{self._object_id}"
        if self.entity_id == wanted:
            return
        registry = async_get_entity_registry(self.hass)
        if registry.async_get(self.entity_id):
            try:
                registry.async_update_entity(self.entity_id, new_entity_id=wanted)
            except ValueError:
                pass
