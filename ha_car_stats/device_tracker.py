from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_GPS_ACCURACY, ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .amap_coordinator import AmapGpsCoordinator
from .const import (
    CONF_MAP_BD_LAT,
    CONF_MAP_BD_LNG,
    CONF_MAP_GCJ_LAT,
    CONF_MAP_GCJ_LNG,
    DOMAIN,
)
from .coordinator import CarStatsCoordinator
from .helpers import cfg_amap, cfg_name, gcj02_to_bd09, wgs84togcj02

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if not cfg_amap(entry):
        return
    coordinator: CarStatsCoordinator = hass.data[DOMAIN][entry.entry_id]
    amap: AmapGpsCoordinator | None = getattr(coordinator, "amap_coordinator", None)
    if not amap:
        return
    async_add_entities([AmapTrackerEntity(coordinator, amap)])


class AmapTrackerEntity(CoordinatorEntity[AmapGpsCoordinator], RestoreEntity, TrackerEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "gps"
    _attr_icon = "mdi:car"
    _attr_source_type = SourceType.GPS

    def __init__(self, stats: CarStatsCoordinator, amap: AmapGpsCoordinator) -> None:
        super().__init__(amap)
        self.stats = stats
        self._entry_id = stats.entry.entry_id
        self._attr_unique_id = f"{self._entry_id}_gps"
        slug = slugify(cfg_name(self.entry)) or "car"
        self._attr_suggested_object_id = f"{slug}_gps"
        self.entity_id = f"device_tracker.{slug}_gps"
        self._lat: float | None = None
        self._lon: float | None = None
        self._acc = 0
        self._attrs: dict[str, Any] = {}
        self._load_state()

    @property
    def entry(self):
        return self.stats.entry

    @property
    def device_info(self) -> DeviceInfo:
        plate = ((self.stats.data or {}).get("vehicle") or {}).get("plate")
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=cfg_name(self.entry),
            manufacturer="狂欢马克思",
            model=plate or "车辆",
        )

    @property
    def latitude(self):
        return self._lat

    @property
    def longitude(self):
        return self._lon

    @property
    def location_accuracy(self):
        return self._acc

    @property
    def extra_state_attributes(self):
        return self._attrs

    @property
    def available(self) -> bool:
        return bool(self.coordinator.data) or self._lat is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._load_state()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None and not self.coordinator.data:
            try:
                lon = last.attributes.get(ATTR_LONGITUDE)
                lat = last.attributes.get(ATTR_LATITUDE)
                self._lon = float(lon) if lon not in (None, "") else None
                self._lat = float(lat) if lat not in (None, "") else None
            except (TypeError, ValueError):
                pass
            try:
                self._acc = int(float(last.attributes.get(ATTR_GPS_ACCURACY) or 0))
            except (TypeError, ValueError):
                self._acc = 0
        if self.coordinator.data:
            self._load_state()

    def _load_state(self) -> None:
        data = self.coordinator.data or {}
        if not data:
            return
        try:
            lon = float(data.get("thislon"))
            lat = float(data.get("thislat"))
        except (TypeError, ValueError):
            return
        try:
            acc = int(float(data.get("accuracy") or 0))
        except (TypeError, ValueError):
            acc = 0
        self._lon = lon
        self._lat = lat
        self._acc = acc
        attrs: dict[str, Any] = {"status": data.get("status", "unknown")}
        if data.get("imei"):
            attrs["imei"] = data["imei"]
        gcj = wgs84togcj02(lon, lat)
        attrs[CONF_MAP_GCJ_LNG] = gcj[0]
        attrs[CONF_MAP_GCJ_LAT] = gcj[1]
        bd = gcj02_to_bd09(gcj[0], gcj[1])
        attrs[CONF_MAP_BD_LNG] = bd[0]
        attrs[CONF_MAP_BD_LAT] = bd[1]
        for k, v in (data.get("attrs") or {}).items():
            attrs[k] = v
        self._attrs = attrs
