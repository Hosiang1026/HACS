from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHANNEL_ID, CONF_ENABLED, DOMAIN
from .coordinator import MsgNotifyCoordinator
from .entity import MsgNotifyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MsgNotifyCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            CurrentMessageSensor(coordinator),
            CurrentSourceSensor(coordinator),
            MessageTimeSensor(coordinator),
            MessageCountSensor(coordinator),
            MessageQueueSensor(coordinator),
            EnabledChannelsSensor(coordinator),
            DisabledChannelsSensor(coordinator),
        ]
    )


class _CarouselSensor(MsgNotifyEntity, SensorEntity):
    def __init__(
        self,
        coordinator: MsgNotifyCoordinator,
        key: str,
        object_id: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator, key, "sensor", object_id)
        self._data_key = key
        self._attr_icon = icon


class CurrentMessageSensor(_CarouselSensor):
    _attr_translation_key = "current_message"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(coordinator, "current_message", "current_message", "mdi:message-text")

    @property
    def native_value(self) -> str:
        msg = str((self.coordinator.data or {}).get("current_message", "") or "")
        if len(msg) > 255:
            return msg[:252] + "..."
        return msg

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "message": (self.coordinator.data or {}).get("current_message", ""),
        }


class CurrentSourceSensor(_CarouselSensor):
    _attr_translation_key = "current_source"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(coordinator, "current_source", "current_source", "mdi:tag-text")

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("current_source", "")


class MessageTimeSensor(_CarouselSensor):
    _attr_translation_key = "message_time"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(coordinator, "message_time", "message_time", "mdi:clock-outline")

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("message_time", "")


class MessageCountSensor(_CarouselSensor):
    _attr_translation_key = "message_count"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(coordinator, "message_count", "message_count", "mdi:counter")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("message_count", 0))


class MessageQueueSensor(_CarouselSensor):
    _attr_translation_key = "message_queue"
    _attr_icon = "mdi:format-list-bulleted"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(coordinator, "message_queue", "message_queue", "mdi:format-list-bulleted")

    @property
    def native_value(self) -> int:
        return int((self.coordinator.data or {}).get("message_count", 0))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "messages": data.get("messages") or [],
            "index": data.get("index", 0),
        }


class EnabledChannelsSensor(_CarouselSensor):
    _attr_translation_key = "enabled_channels"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(
            coordinator, "enabled_channels", "enabled_channels", "mdi:bell-check"
        )

    @property
    def native_value(self) -> int:
        return sum(
            1
            for c in self.coordinator.channels
            if c.get(CONF_CHANNEL_ID) and c.get(CONF_ENABLED, True)
        )


class DisabledChannelsSensor(_CarouselSensor):
    _attr_translation_key = "disabled_channels"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(
            coordinator, "disabled_channels", "disabled_channels", "mdi:bell-off"
        )

    @property
    def native_value(self) -> int:
        return sum(
            1
            for c in self.coordinator.channels
            if c.get(CONF_CHANNEL_ID) and not c.get(CONF_ENABLED, True)
        )
