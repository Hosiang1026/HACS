from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHANNEL_ID, CONF_CHANNEL_NAME, DOMAIN
from .coordinator import MsgNotifyCoordinator
from .entity import MsgNotifyEntity

_TEST_TITLE = "测试"
_TEST_MESSAGE = "这是一条测试通知"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MsgNotifyCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities: list[ButtonEntity] = []
    for channel in coordinator.channels:
        cid = channel.get(CONF_CHANNEL_ID)
        if cid:
            entities.append(ChannelTestButton(coordinator, channel))
    async_add_entities(entities)


class ChannelTestButton(MsgNotifyEntity, ButtonEntity):
    _attr_translation_key = "test_send"
    _attr_icon = "mdi:send"

    def __init__(self, coordinator: MsgNotifyCoordinator, channel: dict) -> None:
        self._channel_id = channel[CONF_CHANNEL_ID]
        super().__init__(
            coordinator,
            f"channel_{self._channel_id}_test",
            "button",
            f"channel_{self._channel_id}_test",
            f"{coordinator.entry.entry_id}_{self._channel_id}",
            channel.get(CONF_CHANNEL_NAME) or self._channel_id,
        )

    async def async_press(self) -> None:
        if not self.coordinator.channel_by_id(self._channel_id):
            return
        await self.coordinator.async_send(
            title=_TEST_TITLE,
            message=_TEST_MESSAGE,
            channels=[self._channel_id],
        )
