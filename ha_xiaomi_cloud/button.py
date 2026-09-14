from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .account import XiaomiAccount, XiaomiDevice, apply_suggested_entity_id
from .const import DOMAIN, INTEGRATION_HUB_SUFFIX

_DEVICE_BUTTONS = (
    ("play_sound", "play_sound", "mdi:volume-high"),
    ("find_device", "find_device", "mdi:crosshairs-gps"),
    ("lost_device", "lost_device", "mdi:cellphone-lock"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    account: XiaomiAccount = hass.data[DOMAIN][entry.unique_id]
    tracked: set[str] = set()
    hub_id = f"{entry.unique_id or account.username}{INTEGRATION_HUB_SUFFIX}"

    @callback
    def update_account() -> None:
        add_entities(account, async_add_entities, tracked)

    account.listeners.append(
        async_dispatcher_connect(hass, account.signal_device_new, update_account)
    )
    async_add_entities([XiaomiHubUpdateButton(account, hub_id)])
    update_account()


@callback
def add_entities(
    account: XiaomiAccount,
    async_add_entities: AddEntitiesCallback,
    tracked: set[str],
) -> None:
    new_tracked = []
    for dev_id, device in account.devices.items():
        for suffix, translation_key, icon in _DEVICE_BUTTONS:
            key = f"{dev_id}_{suffix}"
            if key in tracked:
                continue
            new_tracked.append(
                XiaomiDeviceButton(
                    account, device, tracked, key, suffix, translation_key, icon
                )
            )
            tracked.add(key)
    if new_tracked:
        async_add_entities(new_tracked, True)


class XiaomiHubUpdateButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "update"
    _attr_icon = "mdi:crosshairs-gps"

    def __init__(self, account: XiaomiAccount, hub_id: str) -> None:
        self._account = account
        self._attr_unique_id = f"{hub_id}_update"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub_id)})

    async def async_press(self) -> None:
        await self._account.async_keep_alive(force_locate=True)


class XiaomiDeviceButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        account: XiaomiAccount,
        device: XiaomiDevice,
        tracked: set[str],
        track_key: str,
        action: str,
        translation_key: str,
        icon: str,
    ) -> None:
        self._account = account
        self._device = device
        self._tracked = tracked
        self._track_key = track_key
        self._action = action
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        self._attr_unique_id = track_key
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_suggested_object_id = f"{device.object_slug}_xiaomi_{action}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            configuration_url="https://i.mi.com/",
            identifiers={(DOMAIN, self._device.unique_id)},
            manufacturer="Xiaomi",
            model=self._device.model,
            name=self._device.name,
            sw_version=self._device.version,
        )

    async def async_press(self) -> None:
        if self._action == "play_sound":
            await self._device.async_play_sound()
        elif self._action == "find_device":
            await self._device.async_find_device()
        else:
            await self._device.async_lost_device()

    @callback
    def _handle_device_update(self) -> None:
        if self._device.unique_id not in self._account.devices:
            self.hass.async_create_task(self.async_remove(force_remove=True))
            return
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, self._account.signal_device_update, self._handle_device_update
        )
        self.hass.loop.call_soon(
            apply_suggested_entity_id,
            self.hass,
            self.entity_id,
            self._attr_suggested_object_id,
        )

    async def async_will_remove_from_hass(self) -> None:
        self._tracked.discard(self._track_key)
        if self._unsub_dispatcher:
            self._unsub_dispatcher()
            self._unsub_dispatcher = None
