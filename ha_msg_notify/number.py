from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CAROUSEL_INTERVAL, DEFAULT_CAROUSEL_INTERVAL, DOMAIN
from .coordinator import MsgNotifyCoordinator
from .entity import MsgNotifyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: MsgNotifyCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([CarouselIntervalNumber(coordinator)])


class CarouselIntervalNumber(MsgNotifyEntity, NumberEntity):
    _attr_translation_key = "carousel_interval"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 3600
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "s"

    def __init__(self, coordinator: MsgNotifyCoordinator) -> None:
        super().__init__(
            coordinator, "carousel_interval", "number", "carousel_interval"
        )

    @property
    def native_value(self) -> float:
        return float(
            self.coordinator.cfg(CONF_CAROUSEL_INTERVAL, DEFAULT_CAROUSEL_INTERVAL)
        )

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_option(
            CONF_CAROUSEL_INTERVAL, int(value)
        )
        self.async_write_ha_state()
