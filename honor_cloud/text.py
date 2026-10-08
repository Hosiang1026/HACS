from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, PARALLEL_UPDATES
from .coordinator import SyncCoordinator
from .runtime_data import get_runtime
from .device_tracker import _get_stable_device_id

_LOGGER = logging.getLogger(__name__)

_DEVICE_TEXTS = (
    ("lost_password", "lost_password", "mdi:lock", 16, TextMode.PASSWORD),
    ("lost_message", "lost_message", "mdi:message-alert", 200, TextMode.TEXT),
    ("lost_number", "lost_number", "mdi:phone", 32, TextMode.TEXT),
)


def get_lost_fields(hass: HomeAssistant, entry_id: str, device_id: str) -> dict[str, str]:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.runtime_data is None:
        return {"lost_password": "", "lost_message": "", "lost_number": ""}
    store = get_runtime(entry).lost_fields
    return store.setdefault(
        device_id,
        {"lost_password": "", "lost_message": "", "lost_number": ""},
    )


def _create_text_entities(
    sync_coordinator: SyncCoordinator,
    entry: ConfigEntry,
    known_ids: set[str],
) -> list[HonorLostText]:
    if not sync_coordinator.data:
        return []
    reason = sync_coordinator.data.get("reason", "")
    code = sync_coordinator.data.get("code", 0)
    if reason in ["NO_SESSION", "LOGIN_IN_PROGRESS"] or code == 990:
        return []

    entities: list[HonorLostText] = []
    for device in sync_coordinator.data.get("devices", []):
        if device.get("is_shared"):
            continue
        device_id = _get_stable_device_id(device)
        if not device_id:
            continue
        device_alias = device.get("deviceAliasName", "")
        model = device.get("model", "")
        name = device.get("name", "")
        if not (device_alias or model or name):
            continue
        final_name = device_alias or model or name or f"honor_{device_id[:6]}"
        for suffix, translation_key, icon, native_max, mode in _DEVICE_TEXTS:
            key = f"{device_id}:{suffix}"
            if key in known_ids:
                continue
            known_ids.add(key)
            entities.append(
                HonorLostText(
                    sync_coordinator,
                    entry,
                    device_id,
                    final_name,
                    model or final_name,
                    suffix,
                    translation_key,
                    icon,
                    native_max,
                    mode,
                )
            )
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    sync_coordinator: SyncCoordinator = get_runtime(entry).sync_coordinator
    known_ids: set[str] = set()

    entities = _create_text_entities(sync_coordinator, entry, known_ids)
    if entities:
        async_add_entities(entities)

    def _on_coordinator_update() -> None:
        new_entities = _create_text_entities(sync_coordinator, entry, known_ids)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(sync_coordinator.async_add_listener(_on_coordinator_update))


class HonorLostText(CoordinatorEntity, RestoreEntity, TextEntity):
    _attr_has_entity_name = True
    _attr_parallel_updates = PARALLEL_UPDATES
    _attr_native_min = 0

    def __init__(
        self,
        coordinator: SyncCoordinator,
        entry: ConfigEntry,
        device_id: str,
        device_name: str,
        model: str,
        field: str,
        translation_key: str,
        icon: str,
        native_max: int,
        mode: TextMode,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._field = field
        self._attr_unique_id = f"{DOMAIN}:{device_id}:{field}"
        self._attr_translation_key = translation_key
        self._attr_icon = icon
        self._attr_native_max = native_max
        self._attr_mode = mode

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="荣耀",
            model=self._model or "未知型号",
        )

    @property
    def native_value(self) -> str:
        fields = get_lost_fields(self.hass, self._entry.entry_id, self._device_id)
        return fields.get(self._field, "") or ""

    async def async_set_value(self, value: str) -> None:
        fields = get_lost_fields(self.hass, self._entry.entry_id, self._device_id)
        fields[self._field] = value or ""
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("", "unknown", "unavailable"):
            fields = get_lost_fields(self.hass, self._entry.entry_id, self._device_id)
            fields[self._field] = last.state
            self.async_write_ha_state()
