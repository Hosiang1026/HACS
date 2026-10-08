"""Xiaomi Cloud account."""
from __future__ import annotations

import asyncio
import logging
import math
import random
import re
from math import atan2, cos, sin, sqrt
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.util import slugify
from homeassistant.util.async_ import run_callback_threadsafe
from homeassistant.util.dt import now as dt_now

from .DataUpdateCoordinator import XiaomiCloudDataUpdateCoordinator
from .const import (
    ACTIVITY_BIKE,
    ACTIVITY_DRIVE,
    AMAP_DAILY_LIMIT,
    COMMUTE_BIKE_MAX_KM,
    COMMUTE_MODE_BICYCLING,
    COMMUTE_MODE_DRIVING,
    CONF_AMAP_ENABLED,
    CONF_AMAP_KEY,
    CONF_COMMUTE_ENABLED,
    CONF_COMMUTE_ZONES,
    CONF_ACTIVITY_ENTITY,
    CONF_COMPANY_ZONES,
    CONF_MAX_INTERVAL,
    CONF_OFFPEAK_ENABLED,
    CONF_OFFPEAK_INTERVAL,
    CONF_OFFPEAK_WINDOWS,
    CONF_PEAK_ENABLED,
    CONF_PEAK_INTERVAL,
    CONF_PEAK_WINDOWS,
    CONF_PERIOD_WEEKDAYS,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ACTIVITY_ENTITY,
    DEFAULT_AMAP_ENABLED,
    DEFAULT_COMMUTE_ENABLED,
    DEFAULT_COMMUTE_ZONES,
    DEFAULT_COMPANY_ZONES,
    DEFAULT_MAX_INTERVAL,
    DEFAULT_OFFPEAK_ENABLED,
    DEFAULT_OFFPEAK_INTERVAL,
    DEFAULT_OFFPEAK_WINDOWS,
    DEFAULT_PEAK_ENABLED,
    DEFAULT_PEAK_INTERVAL,
    DEFAULT_PEAK_WINDOWS,
    DEFAULT_PERIOD_WEEKDAYS,
    DOMAIN,
    HOME_EXIT_BUFFER_M,
    HOME_UPDATE_INTERVAL_MAX,
    HOME_UPDATE_INTERVAL_MIN,
    LOW_BATTERY_INTERVAL,
    LOW_BATTERY_THRESHOLD,
    activity_entities,
    default_options,
    in_windows,
    opt_windows_text,
    parse_windows,
)

_LOGGER = logging.getLogger(__name__)


def _amap_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            text = _amap_text(item)
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def device_object_slug(model: str, fallback: str) -> str:
    text = (model or "").strip()
    if text:
        slug = slugify(text.replace(" ", "_").lower())
        if slug:
            return slug
    return slugify(fallback) or "xiaomi_device"


def apply_suggested_entity_id(
    hass: HomeAssistant, entity_id: str, object_id: str
) -> None:
    domain = entity_id.split(".", 1)[0]
    desired = f"{domain}.{object_id}"
    if entity_id == desired:
        return
    try:
        er.async_get(hass).async_update_entity(entity_id, new_entity_id=desired)
    except (ValueError, HomeAssistantError):
        pass


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    a = 6378245.0
    ee = 0.00669342162296594323

    def transform_lat(x: float, y: float) -> float:
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
        ret += 0.2 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
        return ret

    def transform_lon(x: float, y: float) -> float:
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
        return ret

    dlat = transform_lat(lon - 105.0, lat - 35.0)
    dlon = transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    glon, glat = wgs84_to_gcj02(lon, lat)
    return lon * 2 - glon, lat * 2 - glat


_AMAP_TRAFFIC_RANK = {"缓行": 1, "拥堵": 2, "严重拥堵": 3}
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = lat1 * 0.0174532925
    p2 = lat2 * 0.0174532925
    dlat = (lat2 - lat1) * 0.0174532925
    dlon = (lon2 - lon1) * 0.0174532925
    a = (sin(dlat / 2) ** 2) + cos(p1) * cos(p2) * (sin(dlon / 2) ** 2)
    return 6371000 * 2 * atan2(sqrt(a), sqrt(1 - a))


def _amap_grid(lng: float, lat: float) -> tuple[int, int]:
    return int(round(lng * 278)), int(round(lat * 278))


def _identity_tokens(text: str) -> set[str]:
    raw = (text or "").strip()
    if not raw:
        return set()
    tokens: set[str] = set()
    cjk = "".join(_CJK_RE.findall(raw))
    if cjk:
        tokens.add(cjk)
    slug = slugify(raw)
    if slug:
        for part in slug.split("_"):
            if part and len(part) > 1:
                tokens.add(part)
    return tokens


def _token_score(left: set[str], right: set[str]) -> int:
    score = 0
    for item in left:
        for other in right:
            if item == other:
                score += len(item)
            elif len(item) >= 2 and len(other) >= 2 and (item in other or other in item):
                score += min(len(item), len(other))
    return score


def _mode_from_activity(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    value = str(state.state or "").strip()
    if value in ACTIVITY_BIKE:
        return COMMUTE_MODE_BICYCLING
    if value in ACTIVITY_DRIVE:
        return COMMUTE_MODE_DRIVING
    return None


def _amap_traffic(path: dict[str, Any]) -> str | None:
    found = None
    rank = 0
    for step in path.get("steps") or []:
        if not isinstance(step, dict):
            continue
        status = str(step.get("tmc_status") or step.get("status") or "").strip()
        level = _AMAP_TRAFFIC_RANK.get(status, 0)
        if level > rank:
            rank = level
            found = status
    return found


async def _amap_regeo_async(
    session: aiohttp.ClientSession, key: str, lng: float, lat: float
) -> dict[str, str | None] | None:
    try:
        async with session.get(
            "https://restapi.amap.com/v3/geocode/regeo",
            params={
                "key": key,
                "location": f"{lng:.6f},{lat:.6f}",
                "extensions": "all",
            },
            timeout=10,
        ) as resp:
            data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
        _LOGGER.warning("高德逆地理请求失败: %s", err)
        return None
    if str(data.get("status")) != "1":
        _LOGGER.warning(
            "高德逆地理失败: info=%s infocode=%s",
            data.get("info"),
            data.get("infocode"),
        )
        return None
    geo = data.get("regeocode") or {}
    comp = geo.get("addressComponent") or {}
    pois = geo.get("pois") or []
    poi = _amap_text(pois[0].get("name") if pois and isinstance(pois[0], dict) else None)
    address = _amap_text(geo.get("formatted_address")) or poi
    return {
        "address": address,
        "poi": poi,
        "city": _amap_text(comp.get("city")) or _amap_text(comp.get("province")),
        "district": _amap_text(comp.get("district")),
    }


async def _amap_route_async(
    session: aiohttp.ClientSession,
    key: str,
    mode: str,
    olng: float,
    olat: float,
    dlng: float,
    dlat: float,
) -> tuple[float, int, str | None] | None:
    bike = mode == COMMUTE_MODE_BICYCLING
    endpoint = (
        "https://restapi.amap.com/v5/direction/electrobike"
        if bike
        else "https://restapi.amap.com/v5/direction/driving"
    )
    try:
        async with session.get(
            endpoint,
            params={
                "key": key,
                "origin": f"{olng:.6f},{olat:.6f}",
                "destination": f"{dlng:.6f},{dlat:.6f}",
                "show_fields": "cost" if bike else "cost,tmcs",
            },
            timeout=15,
        ) as resp:
            data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None
    if str(data.get("status")) != "1":
        return None
    paths = (data.get("route") or {}).get("paths") or []
    if not paths or not isinstance(paths[0], dict):
        return None
    path = paths[0]
    cost = path.get("cost") if isinstance(path.get("cost"), dict) else {}
    try:
        meters = float(path.get("distance") or 0)
        seconds = float(cost.get("duration") or 0)
    except (TypeError, ValueError):
        return None
    steps = path.get("steps") or []
    first = steps[0] if steps and isinstance(steps[0], dict) else None
    info = str(first.get("instruction") or "").strip() if first else None
    if not bike:
        traffic = _amap_traffic(path)
        if traffic:
            info = f"{info} · {traffic}" if info else traffic
    minutes = 0 if meters < 50 else max(1, int(round(seconds / 60)))
    return round(meters / 1000, 2), minutes, info


class XiaomiAccount:
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: XiaomiCloudDataUpdateCoordinator,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._coordinator = coordinator
        self._username = entry.data["username"]
        self._devices: dict[str, XiaomiDevice] = {}
        self._shutdown = False
        self.listeners: list[CALLBACK_TYPE] = []
        self._locate_count = 0
        self._amap_count = 0
        self._usage_day: str | None = None
        self._peak_enabled = DEFAULT_PEAK_ENABLED
        self._peak_windows: list[tuple[int, int]] = []
        self._offpeak_enabled = DEFAULT_OFFPEAK_ENABLED
        self._offpeak_windows: list[tuple[int, int]] = []
        self._peak_interval = DEFAULT_PEAK_INTERVAL
        self._offpeak_interval = DEFAULT_OFFPEAK_INTERVAL
        self._period_weekdays = DEFAULT_PERIOD_WEEKDAYS
        self._max_interval = DEFAULT_MAX_INTERVAL
        self._home_locate_mode = False
        self._logged_available: bool | None = None
        self._logged_reachable: bool | None = None
        self._coordinator_unsub: CALLBACK_TYPE | None = None
        self._load_period_options()
        self._coordinator_unsub = coordinator.async_add_listener(
            self._handle_coordinator_update
        )

    @property
    def username(self) -> str:
        return self._username

    @property
    def coordinator(self) -> XiaomiCloudDataUpdateCoordinator:
        return self._coordinator

    @property
    def devices(self) -> dict[str, XiaomiDevice]:
        return self._devices

    @property
    def locate_count(self) -> int:
        self._roll_usage_day()
        return self._locate_count

    @property
    def amap_count(self) -> int:
        self._roll_usage_day()
        return self._amap_count

    @property
    def usage_day(self) -> str:
        self._roll_usage_day()
        return self._usage_day or dt_now().strftime("%Y-%m-%d")

    @property
    def fetch_interval(self) -> float:
        return float(self._coordinator._scan_interval)

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success

    def _ensure_operational(self) -> None:
        if not self._coordinator.last_update_success:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            )
        if not self._coordinator.cloud_reachable:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="connection_failed",
            )

    @property
    def signal_device_new(self) -> str:
        return f"{DOMAIN}-{self._username}-device-new"

    @property
    def signal_device_update(self) -> str:
        return f"{DOMAIN}-{self._username}-device-update"

    def _opt(self, key: str, default: Any) -> Any:
        defaults = default_options()
        return self._entry.options.get(
            key, self._entry.data.get(key, defaults.get(key, default))
        )

    def _amap_key(self) -> str:
        return str(self._opt(CONF_AMAP_KEY, "") or "").strip()

    def _amap_enabled(self) -> bool:
        return bool(self._opt(CONF_AMAP_ENABLED, DEFAULT_AMAP_ENABLED)) and bool(
            self._amap_key()
        )

    def _load_period_options(self) -> None:
        self._max_interval = int(
            self._opt(CONF_MAX_INTERVAL, self._opt(CONF_UPDATE_INTERVAL, DEFAULT_MAX_INTERVAL))
        )
        self._peak_enabled = bool(self._opt(CONF_PEAK_ENABLED, DEFAULT_PEAK_ENABLED))
        self._offpeak_enabled = bool(
            self._opt(CONF_OFFPEAK_ENABLED, DEFAULT_OFFPEAK_ENABLED)
        )
        self._peak_windows = (
            parse_windows(
                opt_windows_text(
                    self._opt(CONF_PEAK_WINDOWS, DEFAULT_PEAK_WINDOWS),
                    DEFAULT_PEAK_WINDOWS,
                )
            )
            or []
        )
        self._offpeak_windows = (
            parse_windows(
                opt_windows_text(
                    self._opt(CONF_OFFPEAK_WINDOWS, DEFAULT_OFFPEAK_WINDOWS),
                    DEFAULT_OFFPEAK_WINDOWS,
                )
            )
            or []
        )
        self._peak_interval = int(self._opt(CONF_PEAK_INTERVAL, DEFAULT_PEAK_INTERVAL))
        self._offpeak_interval = int(
            self._opt(CONF_OFFPEAK_INTERVAL, DEFAULT_OFFPEAK_INTERVAL)
        )
        self._period_weekdays = bool(
            self._opt(CONF_PERIOD_WEEKDAYS, DEFAULT_PERIOD_WEEKDAYS)
        )

    def _roll_usage_day(self) -> None:
        today = dt_now().strftime("%Y-%m-%d")
        if self._usage_day != today:
            self._usage_day = today
            self._locate_count = 0
            self._amap_count = 0

    def restore_usage(
        self, *, locate: int | None = None, amap: int | None = None, day: str | None = None
    ) -> None:
        if day:
            self._usage_day = day
        if locate is not None:
            self._locate_count = locate
        if amap is not None:
            self._amap_count = amap

    def _coords_in_zones(
        self,
        lat: float,
        lon: float,
        zones: list[tuple[str, str, float, float, float]],
        expanded: bool,
    ) -> bool:
        extra = HOME_EXIT_BUFFER_M if expanded else 0
        for zone in zones:
            zone_lon, zone_lat = wgs84_to_gcj02(zone[3], zone[2])
            if _haversine_m(lat, lon, zone_lat, zone_lon) <= zone[4] + extra:
                return True
        return False

    def _all_devices_home_or_company(self) -> bool:
        zones = self._home_zones() + self._company_zones()
        devices = list(self._devices.values())
        if not zones or not devices:
            return False
        expanded = self._home_locate_mode
        for device in devices:
            lat = device.latitude
            lon = device.longitude
            if lat is None or lon is None:
                return False
            if not self._coords_in_zones(lat, lon, zones, expanded):
                return False
        return True

    def _device_at_home_or_company(self, device: XiaomiDevice) -> bool:
        entity_ids = [
            entity_id
            for entity_id in activity_entities(
                self._opt(CONF_ACTIVITY_ENTITY, DEFAULT_ACTIVITY_ENTITY)
            )
            if self.hass.states.get(entity_id) is not None
        ]
        if self._activity_mode(device, entity_ids) == COMMUTE_MODE_BICYCLING:
            return True
        lat = device.latitude
        lon = device.longitude
        zones = self._home_zones() + self._company_zones()
        if lat is None or lon is None or not zones:
            return False
        return self._coords_in_zones(lat, lon, zones, expanded=False)

    def _weekday_periods(self, weekday: int) -> bool:
        return not self._period_weekdays or weekday < 5

    def _period_interval(self) -> int:
        if self._all_devices_home_or_company():
            self._home_locate_mode = True
            interval = random.randint(HOME_UPDATE_INTERVAL_MIN, HOME_UPDATE_INTERVAL_MAX)
            _LOGGER.info("全部设备在家/公司区域，下次定位间隔随机为 %s 分钟", interval)
            return interval
        self._home_locate_mode = False
        now = dt_now()
        now_min = now.hour * 60 + now.minute
        if not self._weekday_periods(now.weekday()):
            return self._max_interval
        if self._peak_enabled and in_windows(now_min, self._peak_windows):
            return self._peak_interval
        if self._offpeak_enabled and in_windows(now_min, self._offpeak_windows):
            return self._offpeak_interval
        return self._max_interval

    def _apply_low_battery_slowdown(self, interval: int) -> int:
        if self._home_locate_mode:
            return interval
        for device in self._devices.values():
            battery = device.battery_level
            if battery is None or battery >= LOW_BATTERY_THRESHOLD:
                continue
            if self._device_at_home_or_company(device):
                continue
            return LOW_BATTERY_INTERVAL
        return interval

    async def _apply_fetch_interval(self, devices_data: list[dict] | None = None) -> None:
        self._load_period_options()
        interval = self._apply_low_battery_slowdown(self._period_interval())
        coordinator_interval = int(self._coordinator._scan_interval)
        if coordinator_interval != interval:
            await self._coordinator._update_interval_changed(interval)

    async def async_setup(self) -> None:
        await self._coordinator.async_refresh()
        data = self._coordinator.data if isinstance(self._coordinator.data, list) else []
        self._sync_devices()
        await self._apply_fetch_interval(data)

    async def async_keep_alive(self, force_locate: bool = False) -> None:
        await self._coordinator.async_refresh()
        self._ensure_operational()

    def reload_options(self) -> None:
        self._load_period_options()
        data = self._coordinator.data if isinstance(self._coordinator.data, list) else []
        self.hass.async_create_task(self._apply_fetch_interval(data))

    @callback
    def _handle_coordinator_update(self) -> None:
        available = self.available
        if self._logged_available is None:
            self._logged_available = available
        elif available != self._logged_available:
            if available:
                _LOGGER.info(
                    "Xiaomi Cloud account %s is available again", self._username
                )
            else:
                _LOGGER.warning(
                    "Xiaomi Cloud account %s is unavailable", self._username
                )
            self._logged_available = available
            dispatcher_send(self.hass, self.signal_device_update)

        reachable = self._coordinator.cloud_reachable
        if self._logged_reachable is None:
            self._logged_reachable = reachable
        elif reachable != self._logged_reachable:
            if reachable:
                _LOGGER.info(
                    "Xiaomi Cloud account %s cloud API reachable again",
                    self._username,
                )
            else:
                _LOGGER.warning(
                    "Xiaomi Cloud account %s using cached data (API unreachable)",
                    self._username,
                )
            self._logged_reachable = reachable
        if self._coordinator.last_update_success:
            self._roll_usage_day()
            self._locate_count += 1
        data = self._coordinator.data if isinstance(self._coordinator.data, list) else []
        self._sync_devices()
        self.hass.async_create_task(self._apply_fetch_interval(data))

    async def async_shutdown(self) -> None:
        if self._coordinator_unsub is not None:
            self._coordinator_unsub()
            self._coordinator_unsub = None
        for unsub in self.listeners:
            unsub()
        self.listeners.clear()
        await self._coordinator.async_shutdown()

    async def _post_sync_update(self) -> None:
        dispatcher_send(self.hass, self.signal_device_update)
        try:
            await self._update_amap_addresses()
        except Exception as err:
            _LOGGER.warning("高德地址更新失败: %s", err)
        dispatcher_send(self.hass, self.signal_device_update)

    def _sync_devices(self) -> None:
        data = self._coordinator.data
        if not isinstance(data, list):
            return
        current: set[str] = set()
        new_device = False
        for item in data:
            imei = item.get("imei")
            if not imei:
                continue
            current.add(imei)
            if imei not in self._devices:
                self._devices[imei] = XiaomiDevice(self, item)
                new_device = True
            else:
                self._devices[imei].update(item)
        for imei in list(self._devices):
            if imei not in current:
                del self._devices[imei]
        if new_device:
            dispatcher_send(self.hass, self.signal_device_new)
        self.hass.async_create_task(self._post_sync_update())

    async def _update_amap_addresses(self) -> None:
        if not self._amap_enabled():
            return
        key = self._amap_key()
        if not self._amap_allowed():
            _LOGGER.debug("今日高德调用已达上限 %s，跳过", AMAP_DAILY_LIMIT)
            return
        if bool(self._opt(CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED)):
            await self._update_commute()
        tasks = [
            device.async_fetch_address(key)
            for device in self._devices.values()
            if device.needs_amap_address
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _amap_allowed(self) -> bool:
        self._roll_usage_day()
        return self._amap_count < AMAP_DAILY_LIMIT

    def _bump_amap(self) -> None:
        self._roll_usage_day()
        if self._amap_count < AMAP_DAILY_LIMIT:
            self._amap_count += 1

    @callback
    def _zones_from_opt(
        self, key: str, default: list[str]
    ) -> list[tuple[str, str, float, float, float]]:
        result: list[tuple[str, str, float, float, float]] = []
        zone_ids = self._opt(key, default)
        if isinstance(zone_ids, str):
            zone_ids = [zone_ids] if zone_ids else []
        elif not isinstance(zone_ids, list):
            zone_ids = []
        for entity_id in zone_ids:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            lat = state.attributes.get(ATTR_LATITUDE)
            lon = state.attributes.get(ATTR_LONGITUDE)
            if lat is None or lon is None:
                continue
            try:
                radius = float(state.attributes.get("radius") or 100)
            except (TypeError, ValueError):
                radius = 100.0
            name = state.attributes.get("friendly_name") or entity_id
            result.append((entity_id, str(name), float(lat), float(lon), radius))
        return result

    @callback
    def _home_zones(self) -> list[tuple[str, str, float, float, float]]:
        return self._zones_from_opt(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES)

    @callback
    def _company_zones(self) -> list[tuple[str, str, float, float, float]]:
        return self._zones_from_opt(CONF_COMPANY_ZONES, DEFAULT_COMPANY_ZONES)

    def _device_activity_tokens(self, device: XiaomiDevice) -> set[str]:
        tokens = _identity_tokens(device.name) | _identity_tokens(device.model)
        tracker_id = er.async_get(self.hass).async_get_entity_id(
            "device_tracker", DOMAIN, device.unique_id
        )
        tracker_ids = {f"device_tracker.{device.object_slug}_xiaomi"}
        if tracker_id:
            tracker_ids.add(tracker_id)
        for state in self.hass.states.async_all("person"):
            trackers = state.attributes.get("device_trackers") or []
            if not any(t in tracker_ids for t in trackers):
                continue
            tokens |= _identity_tokens(state.name)
            tokens |= _identity_tokens(state.entity_id.split(".", 1)[-1])
            tokens |= _identity_tokens(str(state.attributes.get("friendly_name") or ""))
        return tokens

    def _activity_mode(self, device: XiaomiDevice, entity_ids: list[str]) -> str | None:
        if not entity_ids:
            return None
        tokens = self._device_activity_tokens(device)
        best_id = None
        best_score = 0
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            score = _token_score(
                tokens,
                _identity_tokens(entity_id.split(".", 1)[-1])
                | _identity_tokens(state.name)
                | _identity_tokens(str(state.attributes.get("friendly_name") or "")),
            )
            if score > best_score:
                best_score = score
                best_id = entity_id
        if best_id is None:
            return None
        return _mode_from_activity(self.hass, best_id)

    @callback
    def _commute_context(
        self,
    ) -> tuple[list[tuple[str, str, float, float, float]], dict[str, str | None]]:
        entity_ids = [
            entity_id
            for entity_id in activity_entities(
                self._opt(CONF_ACTIVITY_ENTITY, DEFAULT_ACTIVITY_ENTITY)
            )
            if self.hass.states.get(entity_id) is not None
        ]
        modes: dict[str, str | None] = {}
        for device in list(self._devices.values()):
            modes[device.unique_id] = self._activity_mode(device, entity_ids)
        return self._home_zones(), modes

    async def _update_commute(self) -> None:
        if not bool(self._opt(CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED)):
            return
        key = self._amap_key()
        if not key:
            return
        devices = [
            device
            for device in self._devices.values()
            if device._commute_pending
            and device.latitude is not None
            and device.longitude is not None
        ]
        if not devices:
            return
        try:
            zones, modes = await self.hass.async_add_executor_job(
                lambda: run_callback_threadsafe(
                    self.hass.loop, self._commute_context
                ).result(timeout=10)
            )
        except TimeoutError:
            return
        if not zones:
            for device in devices:
                device._commute_pending = False
            return
        async with aiohttp.ClientSession() as session:
            for device in devices:
                device._commute_pending = False
                try:
                    await device.async_apply_commute(
                        session, key, modes.get(device.unique_id), zones
                    )
                except Exception as err:
                    _LOGGER.debug("Commute update failed for %s: %s", device.name, err)

    async def _invoke_service(self, payload: dict[str, Any]) -> None:
        self._coordinator.last_service_ok = None
        await self._coordinator._send_command(payload)
        self._ensure_operational()
        if self._coordinator.last_service_ok is False:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="service_failed",
            )

    async def async_play_sound(self, imei: str) -> None:
        await self._invoke_service(
            {"service": "noise", "data": {"imei": imei}}
        )

    async def async_find_device(self, imei: str) -> None:
        await self._invoke_service(
            {"service": "find", "data": {"imei": imei}}
        )

    async def async_lost_device(
        self, imei: str, phone: str, content: str, onlinenotify: bool = True
    ) -> None:
        await self._invoke_service(
            {
                "service": "lost",
                "data": {
                    "imei": imei,
                    "phone": phone,
                    "content": content,
                    "onlinenotify": onlinenotify,
                },
            }
        )

    async def async_send_clipboard(self, text: str) -> None:
        if not str(text or "").strip():
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="clipboard_empty",
            )
        await self._invoke_service(
            {"service": "clipboard", "data": {"text": text}}
        )


class XiaomiDevice:
    def __init__(self, account: XiaomiAccount, data: dict[str, Any]) -> None:
        self._account = account
        self._data = data
        self.lost_message = ""
        self.lost_number = ""
        self.clipboard_text = ""
        self._location_address: str | None = None
        self._location_poi: str | None = None
        self._location_city: str | None = None
        self._location_district: str | None = None
        self._last_address_key: tuple[float, float] | None = None
        self._commute_distance: float | None = None
        self._commute_time: int | None = None
        self._commute_info: str | None = None
        self._commute_pending = False
        self._amap_grid: tuple[int, int] | None = None
        self._amap_route_key: tuple[int, int, int, int, str] | None = None
        self._home_entered_at: float | None = None
        self._home_address_done = False
        self._commute_inside = False
        self._last_lat: float | None = None
        self._last_lon: float | None = None
        self.update(data)

    @property
    def clipboard(self) -> str:
        return self.clipboard_text

    @clipboard.setter
    def clipboard(self, value: str) -> None:
        self.clipboard_text = value or ""

    def update(self, data: dict[str, Any]) -> None:
        prev_lat = self._last_lat
        prev_lon = self._last_lon
        merged = dict(data)
        for key in (
            "device_lat",
            "device_lon",
            "device_accuracy",
            "device_location_update_time",
            "coordinate_type",
            "device_power",
            "last_poll_time",
        ):
            if merged.get(key) is None and self._data.get(key) is not None:
                merged[key] = self._data[key]
        lat = merged.get("device_lat")
        lon = merged.get("device_lon")
        self._data = merged
        if lat is not None and lon is not None:
            lat_f = float(lat)
            lon_f = float(lon)
            if prev_lat != lat_f or prev_lon != lon_f:
                self._commute_pending = True
            self._last_lat = lat_f
            self._last_lon = lon_f

    @property
    def unique_id(self) -> str:
        return str(self._data.get("imei", ""))

    @property
    def imei(self) -> str:
        return self.unique_id

    @property
    def model(self) -> str:
        return str(self._data.get("model") or "")

    @property
    def name(self) -> str:
        return self.model or self.imei

    @property
    def object_slug(self) -> str:
        return device_object_slug(self.model, self.imei)

    @property
    def version(self) -> str | None:
        value = self._data.get("version")
        return str(value) if value else None

    @property
    def battery_level(self) -> int | None:
        power = self._data.get("device_power")
        if power is None:
            return None
        try:
            return int(power)
        except (TypeError, ValueError):
            return None

    @property
    def phone_status(self) -> str:
        status = self._data.get("device_status")
        if status in (True, "online", "on"):
            return "online"
        if status in (False, "offline", "off"):
            return "offline"
        return "unknown"

    @property
    def commute_distance(self) -> float | None:
        return self._commute_distance

    @property
    def commute_time(self) -> int | None:
        return self._commute_time

    @property
    def commute_info(self) -> str | None:
        return self._commute_info

    @property
    def latitude(self) -> float | None:
        lat = self._data.get("device_lat")
        return float(lat) if lat is not None else None

    @property
    def longitude(self) -> float | None:
        lon = self._data.get("device_lon")
        return float(lon) if lon is not None else None

    @property
    def location_accuracy(self) -> int | None:
        acc = self._data.get("device_accuracy")
        return int(acc) if acc is not None else None

    @property
    def location_update_time(self) -> str | None:
        return self._data.get("device_location_update_time")

    @property
    def location_address(self) -> str | None:
        return self._location_address

    @property
    def location_poi(self) -> str | None:
        return self._location_poi

    @property
    def location_city(self) -> str | None:
        return self._location_city

    @property
    def location_district(self) -> str | None:
        return self._location_district

    @property
    def coordinate_type(self) -> str:
        return "gcj02"

    @property
    def device_phone(self) -> str | None:
        phone = self._data.get("device_phone")
        return str(phone) if phone else None

    @property
    def last_poll_time(self) -> str | None:
        value = self._data.get("last_poll_time")
        return str(value) if value else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"imei": self.imei}
        if self.location_update_time:
            attrs["last_update"] = self.location_update_time
        if self.last_poll_time:
            attrs["last_poll"] = self.last_poll_time
        attrs["coordinate_type"] = self.coordinate_type
        if self.device_phone:
            attrs["device_phone"] = self.device_phone
        return attrs

    def restore_location_address(self, state: str | None) -> None:
        if state and state not in ("unknown", "unavailable"):
            self._location_address = state

    def restore_location_attrs(self, attrs: dict[str, Any]) -> None:
        self._location_poi = attrs.get("poi")
        self._location_city = attrs.get("city")
        self._location_district = attrs.get("district")

    def restore_commute_distance(self, state: Any) -> None:
        if state in (None, "", "unknown", "unavailable"):
            return
        try:
            self._commute_distance = float(state)
        except (TypeError, ValueError):
            pass

    def restore_commute_time(self, state: Any) -> None:
        if state in (None, "", "unknown", "unavailable"):
            return
        try:
            self._commute_time = int(float(state))
        except (TypeError, ValueError):
            pass

    def restore_commute_info(self, state: Any) -> None:
        if state in (None, "", "unknown", "unavailable"):
            return
        text = str(state).strip()
        if text:
            self._commute_info = text

    @property
    def needs_amap_address(self) -> bool:
        lat = self.latitude
        lon = self.longitude
        if lat is None or lon is None:
            return False
        if not self._location_address:
            return True
        return self._amap_grid != _amap_grid(lon, lat)

    async def async_fetch_address(self, key: str) -> None:
        lat = self.latitude
        lon = self.longitude
        if lat is None or lon is None:
            return
        if not self._account._amap_allowed():
            return
        grid = _amap_grid(lon, lat)
        if self._amap_grid == grid and self._location_address:
            return
        url = "https://restapi.amap.com/v3/geocode/regeo"
        params = {
            "location": f"{lon:.6f},{lat:.6f}",
            "key": key,
            "radius": 1000,
            "extensions": "all",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("高德逆地理 HTTP %s", resp.status)
                        return
                    js = await resp.json()
            if str(js.get("status")) != "1":
                _LOGGER.warning(
                    "高德逆地理失败: info=%s infocode=%s",
                    js.get("info"),
                    js.get("infocode"),
                )
                return
            geo = js.get("regeocode") or {}
            comp = geo.get("addressComponent") or {}
            pois = geo.get("pois") or []
            poi = _amap_text(
                pois[0].get("name") if pois and isinstance(pois[0], dict) else None
            )
            address = _amap_text(geo.get("formatted_address")) or poi
            if not address:
                _LOGGER.warning("高德逆地理无地址结果: %s,%s", lon, lat)
                return
            self._location_address = address
            self._location_poi = poi
            self._location_city = _amap_text(comp.get("city")) or _amap_text(
                comp.get("province")
            )
            self._location_district = _amap_text(comp.get("district"))
            self._amap_grid = grid
            self._last_address_key = (round(lat, 5), round(lon, 5))
            self._account._bump_amap()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.warning("高德逆地理异常: %s", err)

    async def async_apply_commute(
        self,
        session: aiohttp.ClientSession,
        key: str,
        mode: str | None,
        zones: list[tuple[str, str, float, float, float]],
    ) -> None:
        lat = self.latitude
        lon = self.longitude
        if lat is None or lon is None:
            return
        olng, olat = lon, lat
        grid = _amap_grid(olng, olat)
        inside = None
        inside_dist = None
        best = None
        best_dist = None
        for zone in zones:
            zone_gcj_lon, zone_gcj_lat = wgs84_to_gcj02(zone[3], zone[2])
            meters = _haversine_m(lat, lon, zone_gcj_lat, zone_gcj_lon)
            leave_limit = zone[4] + (
                HOME_EXIT_BUFFER_M if self._commute_inside else 0
            )
            if meters <= leave_limit and (
                inside_dist is None or meters < inside_dist
            ):
                inside = zone
                inside_dist = meters
            if best_dist is None or meters < best_dist:
                best_dist = meters
                best = zone

        async def _refresh_address() -> bool:
            if self._amap_grid == grid and self._location_address:
                return True
            if not self._account._amap_allowed():
                return bool(self._location_address)
            geo = await _amap_regeo_async(session, key, olng, olat)
            if not geo or not geo.get("address"):
                return False
            self._account._bump_amap()
            self._amap_grid = grid
            self._location_address = geo["address"]
            self._location_poi = geo.get("poi")
            self._location_city = geo.get("city")
            self._location_district = geo.get("district")
            self._last_address_key = (round(lat, 5), round(lon, 5))
            return True

        if inside is not None:
            self._commute_inside = True
            now_ts = dt_now().timestamp()
            if self._home_entered_at is None:
                self._home_entered_at = now_ts
                self._home_address_done = False
            if not self._home_address_done and now_ts - self._home_entered_at < 3600:
                await _refresh_address()
                self._home_address_done = True
            self._commute_distance = 0.0
            self._commute_time = 0
            self._commute_info = inside[1]
            self._amap_route_key = None
            return

        self._commute_inside = False
        self._home_entered_at = None
        self._home_address_done = False
        if best is None:
            return
        if mode is None:
            mode = (
                COMMUTE_MODE_BICYCLING
                if (best_dist or 0) < COMMUTE_BIKE_MAX_KM * 1000
                else COMMUTE_MODE_DRIVING
            )
        dlng, dlat = wgs84_to_gcj02(best[3], best[2])
        dest_grid = _amap_grid(dlng, dlat)
        route_key = (*grid, *dest_grid, mode)
        if route_key == self._amap_route_key:
            return
        await _refresh_address()
        if not self._account._amap_allowed():
            return
        route = await _amap_route_async(session, key, mode, olng, olat, dlng, dlat)
        if route is None:
            return
        self._account._bump_amap()
        self._amap_route_key = route_key
        distance_km, minutes, info = route
        self._commute_distance = distance_km
        self._commute_time = minutes
        self._commute_info = info or best[1]

    async def async_play_sound(self) -> None:
        await self._account.async_play_sound(self.imei)

    async def async_find_device(self) -> None:
        await self._account.async_find_device(self.imei)

    async def async_lost_device(self) -> None:
        phone = (self.lost_number or "").strip()
        message = (self.lost_message or "").strip()
        if not phone:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="lost_number_required",
            )
        if not message:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="lost_message_required",
            )
        await self._account.async_lost_device(self.imei, phone, message)
