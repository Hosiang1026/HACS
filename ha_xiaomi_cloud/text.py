from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .account import XiaomiAccount, XiaomiDevice, apply_suggested_entity_id
from .const import DOMAIN
from .entity import XiaomiAccountEntity

PARALLEL_UPDATES = 1

_DEVICE_TEXTS = (
    ("lost_message", "lost_message", "lost_message", "mdi:message-alert", 200),
    ("lost_number", "lost_number", "lost_number", "mdi:phone", 32),
    ("clipboard", "clipboard_text", "clipboard", "mdi:clipboard-text", 500),
)

_FIELD_ALIASES = {"clipboard": "clipboard_text"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    account: XiaomiAccount = entry.runtime_data
    tracked: set[str] = set()

    @callback
    def update_account() -> None:
        add_entities(account, async_add_entities, tracked)

    account.listeners.append(
        async_dispatcher_connect(hass, account.signal_device_new, update_account)
    )
    update_account()


@callback
def add_entities(
    account: XiaomiAccount,
    async_add_entities: AddEntitiesCallback,
    tracked: set[str],
) -> None:
    new_tracked = []
    for dev_id, device in account.devices.items():
        for suffix, field, translation_key, icon, native_max in _DEVICE_TEXTS:
            key = f"{dev_id}_{suffix}"
            if key in tracked:
                continue
            new_tracked.append(
                XiaomiDeviceText(
                    account,
                    device,
                    tracked,
                    key,
                    suffix,
                    field,
                    translation_key,
                    icon,
                    native_max,
                )
            )
            tracked.add(key)
    if new_tracked:
        async_add_entities(new_tracked, True)


class XiaomiDeviceText(XiaomiAccountEntity, RestoreEntity, TextEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0

    def __init__(
        self,
        account: XiaomiAccount,
        device: XiaomiDevice,
        tracked: set[str],
        track_key: str,
        suffix: str,
        field: str,
        translation_key: str,
        icon: str,
        native_max: int,
    ) -> None:
        self._account = account
        self._device = device
        self._tracked = tracked
        self._track_key = track_key
        self._field = _FIELD_ALIASES.get(field, field)
        self._unsub_dispatcher: CALLBACK_TYPE | None = None
        self._attr_unique_id = track_key
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_native_max = native_max
        self._attr_suggested_object_id = f"{device.object_slug}_xiaomi_{suffix}"

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

    @property
    def native_value(self) -> str:
        return getattr(self._device, self._field, "") or ""

    async def async_set_value(self, value: str) -> None:
        setattr(self._device, self._field, value)
        if self._field == "clipboard_text" and value.strip():
            await self._account.async_send_clipboard(value.strip())
        self.async_write_ha_state()

    @callback
    def _handle_device_update(self) -> None:
        if self._device.unique_id not in self._account.devices:
            self.hass.async_create_task(self.async_remove(force_remove=True))
            return
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("", "unknown", "unavailable"):
            setattr(self._device, self._field, last.state)
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
        await super().async_will_remove_from_hass()
