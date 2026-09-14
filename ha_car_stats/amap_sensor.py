from __future__ import annotations

import datetime
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify
from homeassistant.util import dt as dt_util

from .amap_coordinator import AmapGpsCoordinator
from .const import (
    AMAP_DEFAULT_SENSORS,
    CONF_AMAP_LOGIN_AT,
    DOMAIN,
    KEY_ADDRESS,
    KEY_AMAP_CALLS,
    KEY_CARSTATUS,
    KEY_COMMUTE_DISTANCE,
    KEY_COMMUTE_TIME,
    KEY_COMMUTE_TOLL,
    KEY_COURSE,
    KEY_DRIVETIME,
    KEY_NAVI_DEST,
    KEY_NAVISTATUS,
    KEY_PARKING_TIME,
    KEY_QUERYTIME,
    KEY_RESTRICT_TAIL,
    KEY_SPEED,
    KEY_TRAFFIC_LIGHTS,
    UNIT_CNY,
    UNIT_KMH,
)
from .coordinator import CarStatsCoordinator
from .helpers import cfg_name, fmt_duration

_LOGGER = logging.getLogger(__name__)

AMAP_SENSOR_META: dict[str, tuple[str, str | None, SensorDeviceClass | None, SensorStateClass | None]] = {
    KEY_PARKING_TIME: ("mdi:parking", None, None, None),
    KEY_SPEED: ("mdi:speedometer", UNIT_KMH, SensorDeviceClass.SPEED, SensorStateClass.MEASUREMENT),
    KEY_ADDRESS: ("mdi:map", None, None, None),
    KEY_NAVISTATUS: ("mdi:car-connected", None, None, None),
    KEY_CARSTATUS: ("mdi:car-side", None, None, None),
    KEY_DRIVETIME: ("mdi:timer-play", None, None, None),
    KEY_COMMUTE_DISTANCE: ("mdi:map-marker-distance", None, None, SensorStateClass.MEASUREMENT),
    KEY_COMMUTE_TIME: ("mdi:clock-outline", None, None, None),
    KEY_NAVI_DEST: ("mdi:map-marker", None, None, None),
    KEY_COMMUTE_TOLL: ("mdi:cash", UNIT_CNY, SensorDeviceClass.MONETARY, None),
    KEY_TRAFFIC_LIGHTS: ("mdi:traffic-light", None, None, SensorStateClass.MEASUREMENT),
    KEY_COURSE: ("mdi:compass", None, None, None),
    KEY_RESTRICT_TAIL: ("mdi:numeric", None, None, None),
    KEY_QUERYTIME: ("mdi:clock-check", None, None, None),
    KEY_AMAP_CALLS: ("mdi:api", None, None, SensorStateClass.TOTAL_INCREASING),
}

_FLOAT_KEYS = frozenset({KEY_SPEED, KEY_COMMUTE_DISTANCE, KEY_COMMUTE_TOLL})
_INT_KEYS = frozenset({KEY_TRAFFIC_LIGHTS, KEY_AMAP_CALLS})


def create_amap_sensors(stats: CarStatsCoordinator, amap: AmapGpsCoordinator) -> list[SensorEntity]:
    entities: list[SensorEntity] = [AmapGpsSensor(stats, amap, key) for key in AMAP_DEFAULT_SENSORS if key in AMAP_SENSOR_META]
    entities.append(AmapLoginTimeSensor(stats, amap))
    return entities


class AmapLoginTimeSensor(CoordinatorEntity[AmapGpsCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, stats: CarStatsCoordinator, amap: AmapGpsCoordinator) -> None:
        super().__init__(amap)
        self.stats = stats
        self._entry_id = stats.entry.entry_id
        self._attr_unique_id = f"{self._entry_id}_amap_login_time"
        self._attr_translation_key = "amap_login_time"
        self._attr_icon = "mdi:clock-check-outline"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        slug = slugify(cfg_name(self.entry)) or "car"
        self._attr_suggested_object_id = f"{slug}_amap_login_time"
        self.entity_id = f"sensor.{slug}_amap_login_time"

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
    def available(self) -> bool:
        return True

    @property
    def native_value(self):
        raw = self.entry.data.get(CONF_AMAP_LOGIN_AT)
        if not raw:
            return None
        parsed = dt_util.parse_datetime(str(raw))
        if not parsed:
            return None
        return dt_util.as_utc(parsed)


class AmapGpsSensor(CoordinatorEntity[AmapGpsCoordinator], RestoreEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, stats: CarStatsCoordinator, amap: AmapGpsCoordinator, key: str) -> None:
        super().__init__(amap)
        self.stats = stats
        self._entry_id = stats.entry.entry_id
        self._key = key
        icon, unit, device_class, state_class = AMAP_SENSOR_META[key]
        self._attr_unique_id = f"{self._entry_id}_amap_{key}"
        self._attr_translation_key = f"amap_{key}"
        self._attr_icon = icon
        if unit:
            self._attr_native_unit_of_measurement = unit
        if device_class:
            self._attr_device_class = device_class
        if state_class:
            self._attr_state_class = state_class
        slug = slugify(cfg_name(self.entry)) or "car"
        self._attr_suggested_object_id = f"{slug}_{key}"
        self.entity_id = f"sensor.{slug}_{key}"
        self._state: Any = None
        self._unsub_tick = None
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
    def available(self) -> bool:
        return bool(self.coordinator.data) or self._state is not None

    @property
    def native_value(self):
        return self._state

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._key == KEY_COMMUTE_DISTANCE:
            registry = er.async_get(self.hass)
            if registry.async_get(self.entity_id):
                registry.async_update_entity(self.entity_id, device_class=None)
                registry.async_update_entity_options(self.entity_id, "sensor", {})
        if self._state is None:
            last = await self.async_get_last_state()
            if last and last.state not in (None, STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
                if self._key in _FLOAT_KEYS:
                    try:
                        self._state = float(last.state)
                    except (TypeError, ValueError):
                        pass
                elif self._key in _INT_KEYS:
                    try:
                        self._state = int(float(last.state))
                    except (TypeError, ValueError):
                        pass
                else:
                    self._state = last.state
                if self._state is not None:
                    self.async_write_ha_state()
        if self._key == KEY_PARKING_TIME:
            self._unsub_tick = async_track_time_interval(
                self.hass, self._async_tick_parking, datetime.timedelta(minutes=1)
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_tick:
            self._unsub_tick()
            self._unsub_tick = None
        await super().async_will_remove_from_hass()

    @callback
    def _async_tick_parking(self, _now=None) -> None:
        old = self._state
        self._load_state()
        if self._state != old:
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._load_state()
        self.async_write_ha_state()

    def _fmt_course(self, deg: int) -> str:
        names = (
            "北", "北偏东", "东北", "东偏北",
            "东", "东偏南", "东南", "南偏东",
            "南", "南偏西", "西南", "西偏南",
            "西", "西偏北", "西北", "北偏西",
        )
        return names[int(((deg + 11.25) % 360) / 22.5) % 16]

    def _fmt_duration(self, seconds: int) -> str:
        return fmt_duration(seconds)

    def _calc_parkingtime(self, attrs: dict) -> str:
        laststop = attrs.get("laststoptime")
        if not laststop:
            return "00:00"
        try:
            if attrs.get("onlinestatus") == "在线" and attrs.get("runorstop") == "run":
                return "00:00"
            stop = datetime.datetime.strptime(str(laststop), "%Y-%m-%d %H:%M:%S")
            return self._fmt_duration(int((datetime.datetime.now() - stop).total_seconds()))
        except (ValueError, TypeError):
            return "00:00"

    def _calc_drivetime(self, attrs: dict) -> str:
        lastrun = attrs.get("lastruntime")
        laststop = attrs.get("laststoptime")
        if not lastrun:
            return "00:00"
        try:
            start = datetime.datetime.strptime(str(lastrun), "%Y-%m-%d %H:%M:%S")
            now = datetime.datetime.now()
            if start > now:
                return "00:00"
            running = attrs.get("onlinestatus") == "在线" and attrs.get("runorstop") == "run"
            if running:
                return self._fmt_duration(int((now - start).total_seconds()))
            if not attrs.get("had_run") or not laststop:
                return "00:00"
            stop = datetime.datetime.strptime(str(laststop), "%Y-%m-%d %H:%M:%S")
            if stop <= start:
                return "00:00"
            return self._fmt_duration(int((stop - start).total_seconds()))
        except (ValueError, TypeError):
            return "00:00"

    def _load_state(self) -> None:
        data = self.coordinator.data or {}
        if not data:
            if self._key == KEY_AMAP_CALLS:
                try:
                    self._state = int(getattr(self.coordinator, "_api_calls", 0) or 0)
                except (TypeError, ValueError):
                    self._state = 0
            elif self._key == KEY_COMMUTE_DISTANCE and self._state is None:
                self._state = 0.0
            elif self._key == KEY_COMMUTE_TIME and self._state is None:
                self._state = "0分钟"
            elif self._key == KEY_COMMUTE_TOLL and self._state is None:
                self._state = 0.0
            elif self._key == KEY_TRAFFIC_LIGHTS and self._state is None:
                self._state = 0
            return
        attrs = data.get("attrs") or {}
        key = self._key
        if key == KEY_PARKING_TIME:
            self._state = self._calc_parkingtime(attrs)
        elif key == KEY_SPEED:
            self._state = float(attrs.get("speed") or 0)
        elif key == KEY_ADDRESS:
            if attrs.get("address"):
                self._state = attrs.get("address")
        elif key == KEY_NAVISTATUS:
            online = attrs.get("onlinestatus")
            navi = attrs.get("naviStatus")
            self._state = "导航中" if online == "在线" and navi == "导航中" else ("在线" if online == "在线" else "离线")
        elif key == KEY_CARSTATUS:
            if attrs.get("runorstop") in ("run", "运动"):
                self._state = "开车中"
            else:
                self._state = "停车"
        elif key == KEY_DRIVETIME:
            self._state = self._calc_drivetime(attrs)
        elif key == KEY_COMMUTE_DISTANCE:
            val = attrs.get("commute_distance")
            self._state = float(val) if val not in (None, "") else 0.0
        elif key == KEY_COMMUTE_TIME:
            self._state = attrs.get("commute_time") or "0分钟"
        elif key == KEY_NAVI_DEST:
            if attrs.get("navi_dest"):
                self._state = attrs.get("navi_dest")
        elif key == KEY_COMMUTE_TOLL:
            val = attrs.get("commute_toll")
            self._state = float(val) if val not in (None, "") else 0.0
        elif key == KEY_TRAFFIC_LIGHTS:
            val = attrs.get("traffic_lights")
            self._state = int(val) if val not in (None, "") else 0
        elif key == KEY_COURSE:
            if attrs.get("course") not in (None, ""):
                try:
                    self._state = self._fmt_course(int(float(attrs.get("course"))) % 360)
                except (TypeError, ValueError):
                    pass
        elif key == KEY_RESTRICT_TAIL:
            if attrs.get("restrict_tail"):
                self._state = attrs.get("restrict_tail")
        elif key == KEY_QUERYTIME:
            val = attrs.get("querytime")
            if val:
                self._state = val
            elif self._state is None:
                self._state = attrs.get("lastonlinetime") or attrs.get("laststoptime") or None
        elif key == KEY_AMAP_CALLS:
            val = attrs.get("api_calls")
            if val is None:
                val = getattr(self.coordinator, "_api_calls", 0)
            try:
                self._state = int(val or 0)
            except (TypeError, ValueError):
                self._state = 0
