from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CAROUSEL_ENABLED,
    CONF_CHANNEL_ID,
    CONF_CHANNEL_NAME,
    CONF_ENABLED,
    DEFAULT_CAROUSEL_ENABLED,
    DOMAIN,
)
from .coordinator import MsgNotifyCoordinator
from .entity import MsgNotifyEntity, channel_switch_id


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MsgNotifyCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[SwitchEntity] = [CarouselSwitch(coordinator)]
    for channel in coordinator.channels:
        cid = channel.get(CONF_CHANNEL_ID)
        if cid:
            entities.append(ChannelSwitch(coordinator, channel))
    async_add_entities(entities)


class CarouselSwitch(MsgNotifyEntity, SwitchEntity):
    _attr_translation_key = "carousel_enabled"
    _attr_icon = "mdi:view-carousel"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(coordinator, "carousel_enabled", "switch", "carousel_enabled")

    @property
    def is_on(self) -> bool:
        return bool(
            self.coordinator.cfg(CONF_CAROUSEL_ENABLED, DEFAULT_CAROUSEL_ENABLED)
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_update_option(CONF_CAROUSEL_ENABLED, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_update_option(CONF_CAROUSEL_ENABLED, False)
        self.async_write_ha_state()


class ChannelSwitch(MsgNotifyEntity, SwitchEntity):
    _attr_icon = "mdi:bell-ring"

    def __init__(self, coordinator: MsgNotifyCoordinator, channel: dict) -> None:
        self._channel_id = channel[CONF_CHANNEL_ID]
        super().__init__(
            coordinator,
            f"channel_{self._channel_id}",
            "switch",
            channel_switch_id(channel),
            f"{coordinator.entry.entry_id}_{self._channel_id}",
            channel.get(CONF_CHANNEL_NAME) or self._channel_id,
        )
        self._attr_name = channel.get(CONF_CHANNEL_NAME) or self._channel_id

    @property
    def is_on(self) -> bool:
        channel = self.coordinator.channel_by_id(self._channel_id)
        return bool(channel.get(CONF_ENABLED, True)) if channel else False

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_channel_enabled(self._channel_id, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_channel_enabled(self._channel_id, False)
        self.async_write_ha_state()
