"""iCloud account."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from math import atan2, cos, pi, sin, sqrt
import logging
import random
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests

_path = str(Path(__file__).resolve().parent)
if _path not in sys.path:
    sys.path.insert(0, _path)

from pyicloud import PyiCloudService
from pyicloud.exceptions import (
    PyiCloud2FARequiredException,
    PyiCloud2SARequiredException,
    PyiCloudAPIResponseException,
    PyiCloudAuthRequiredException,
    PyiCloudFailedLoginException,
    PyiCloudNoDevicesException,
    PyiCloudServiceNotActivatedException,
    PyiCloudServiceUnavailable,
)
from pyicloud.services.findmyiphone import AppleDevice

from homeassistant.components.zone import async_active_zone
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify
from homeassistant.util.async_ import run_callback_threadsafe
from homeassistant.util.dt import now as dt_now, utcnow
from homeassistant.util.location import distance

from .const import (
    ACTIVITY_BIKE,
    ACTIVITY_DRIVE,
    COMMUTE_BIKE_MAX_KM,
    CONF_ACTIVITY_ENTITY,
    CONF_AMAP_KEY,
    CONF_COMMUTE_ENABLED,
    CONF_COMMUTE_ZONES,
    CONF_OFFPEAK_ENABLED,
    CONF_OFFPEAK_INTERVAL,
    CONF_OFFPEAK_WINDOWS,
    CONF_PEAK_ENABLED,
    CONF_PEAK_INTERVAL,
    CONF_PEAK_WINDOWS,
    CONF_PERIOD_WEEKDAYS,
    COMMUTE_MODE_BICYCLING,
    COMMUTE_MODE_DRIVING,
    DEFAULT_ACTIVITY_ENTITY,
    DEFAULT_COMMUTE_ENABLED,
    DEFAULT_COMMUTE_ZONES,
    DEFAULT_OFFPEAK_ENABLED,
    DEFAULT_OFFPEAK_INTERVAL,
    DEFAULT_OFFPEAK_WINDOWS,
    DEFAULT_PEAK_ENABLED,
    DEFAULT_PEAK_INTERVAL,
    DEFAULT_PEAK_WINDOWS,
    DEFAULT_PERIOD_WEEKDAYS,
    DEVICE_BATTERY_LEVEL,
    DEVICE_BATTERY_STATUS,
    DEVICE_CLASS,
    DEVICE_DISPLAY_NAME,
    DEVICE_ID,
    DEVICE_LOCATION,
    DEVICE_LOCATION_HORIZONTAL_ACCURACY,
    DEVICE_LOCATION_LATITUDE,
    DEVICE_LOCATION_LONGITUDE,
    DEVICE_LOCATION_TIMESTAMP,
    RUN_CADENCE,
    RUN_STEP_LENGTH,
    STEP_LENGTH,
    WALK_CADENCE,
    WALK_MIN_DISTANCE,
    WALK_MIN_INTERVAL,
    WALK_PATH_FACTOR,
    WALK_PATH_FACTOR_DENSE,
    WALK_PATH_FACTOR_SPARSE,
    WALK_SPEED_MAX,
    WALK_SPEED_RUN,
    DEVICE_LOST_MODE_CAPABLE,
    DEVICE_LOW_POWER_MODE,
    DEVICE_NAME,
    DEVICE_PERSON_ID,
    DEVICE_RAW_DEVICE_MODEL,
    DEVICE_STATUS,
    DEVICE_STATUS_CODES,
    DEVICE_STATUS_SET,
    DOMAIN,
    FAR_DISTANCE_KM,
    FAR_INTERVAL_100_200,
    FAR_INTERVAL_200_300,
    FAR_INTERVAL_2000_PLUS,
    FAR_INTERVAL_300_800,
    FAR_INTERVAL_50_100,
    FAR_INTERVAL_800_2000,
    INTEGRATION_HUB_SUFFIX,
    HOME_EXIT_BUFFER_M,
    LOCAL_DISTANCE_KM,
    LOW_BATTERY_LEVEL,
    activity_entities,
    in_windows,
    opt_windows_text,
    parse_windows,
)
from .session_storage import clear_session_files

# entity attributes
ATTR_ACCOUNT_FETCH_INTERVAL = "account_fetch_interval"
ATTR_BATTERY = "battery"
ATTR_BATTERY_STATUS = "battery_status"
ATTR_DEVICE_NAME = "device_name"
ATTR_DEVICE_STATUS = "device_status"
ATTR_LOW_POWER_MODE = "low_power_mode"
ATTR_OWNER_NAME = "owner_fullname"

# services
SERVICE_ICLOUD_PLAY_SOUND = "play_sound"
SERVICE_ICLOUD_DISPLAY_MESSAGE = "display_message"
SERVICE_ICLOUD_LOST_DEVICE = "lost_device"
SERVICE_ICLOUD_UPDATE = "update"
ATTR_ACCOUNT = "account"
ATTR_LOST_DEVICE_MESSAGE = "message"
ATTR_LOST_DEVICE_NUMBER = "number"
ATTR_LOST_DEVICE_SOUND = "sound"

_LOGGER = logging.getLogger(__name__)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = lat1 * 0.0174532925
    p2 = lat2 * 0.0174532925
    dlat = (lat2 - lat1) * 0.0174532925
    dlon = (lon2 - lon1) * 0.0174532925
    a = (sin(dlat / 2) ** 2) + cos(p1) * cos(p2) * (sin(dlon / 2) ** 2)
    return 6371000 * 2 * atan2(sqrt(a), sqrt(1 - a))


def _out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(lng: float, lat: float) -> float:
    ret = (
        -100.0
        + 2.0 * lng
        + 3.0 * lat
        + 0.2 * lat * lat
        + 0.1 * lng * lat
        + 0.2 * sqrt(abs(lng))
    )
    ret += (20.0 * sin(6.0 * lng * pi) + 20.0 * sin(2.0 * lng * pi)) * 2.0 / 3.0
    ret += (20.0 * sin(lat * pi) + 40.0 * sin(lat / 3.0 * pi)) * 2.0 / 3.0
    ret += (160.0 * sin(lat / 12.0 * pi) + 320 * sin(lat * pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = (
        300.0
        + lng
        + 2.0 * lat
        + 0.1 * lng * lng
        + 0.1 * lng * lat
        + 0.1 * sqrt(abs(lng))
    )
    ret += (20.0 * sin(6.0 * lng * pi) + 20.0 * sin(2.0 * lng * pi)) * 2.0 / 3.0
    ret += (20.0 * sin(lng * pi) + 40.0 * sin(lng / 3.0 * pi)) * 2.0 / 3.0
    ret += (150.0 * sin(lng / 12.0 * pi) + 300.0 * sin(lng / 30.0 * pi)) * 2.0 / 3.0
    return ret


def _wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    if _out_of_china(lng, lat):
        return lng, lat
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * cos(radlat) * pi)
    return lng + dlng, lat + dlat


_AMAP_TRAFFIC_RANK = {"缓行": 1, "拥堵": 2, "严重拥堵": 3}


def _amap_text(value: Any) -> str | None:
    if value in (None, "", []):
        return None
    if isinstance(value, list):
        return None
    text = str(value).strip()
    return text or None


def _amap_grid(lng: float, lat: float) -> tuple[int, int]:
    return int(round(lng * 278)), int(round(lat * 278))


def _amap_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        items: list[dict[str, Any]] = []
        for item in value:
            items.extend(_amap_items(item))
        return items
    if isinstance(value, dict):
        if "name" in value or "instruction" in value or "tmc_status" in value:
            return [value]
        for key in ("pois", "poi", "aois", "aoi", "tmcs", "tmc"):
            if key in value:
                return _amap_items(value[key])
        return [value]
    return []


def _amap_name(items: Any, inside: bool = False) -> str | None:
    first = None
    for item in _amap_items(items):
        name = _amap_text(item.get("name"))
        if not name:
            continue
        if first is None:
            first = name
        if inside and str(item.get("distance") or "") == "0":
            return name
    return first


def _amap_traffic(path: dict[str, Any]) -> str | None:
    found = None
    rank = 0
    chunks = list(_amap_items(path.get("tmcs")))
    for step in _amap_items(path.get("steps")):
        chunks.extend(_amap_items(step.get("tmcs")))
        status = _amap_text(step.get("tmc_status"))
        if status:
            chunks.append({"tmc_status": status})
    for item in chunks:
        status = _amap_text(item.get("tmc_status") or item.get("status"))
        level = _AMAP_TRAFFIC_RANK.get(status or "", 0)
        if level > rank:
            rank = level
            found = status
    return found


def _amap_regeo(key: str, lng: float, lat: float) -> dict[str, str | None] | None:
    try:
        response = requests.get(
            "https://restapi.amap.com/v3/geocode/regeo",
            params={
                "key": key,
                "location": f"{lng:.6f},{lat:.6f}",
                "extensions": "all",
            },
            timeout=10,
        )
        data = response.json()
    except (OSError, ValueError, requests.RequestException):
        return None
    if str(data.get("status")) != "1":
        return None
    geo = data.get("regeocode") or {}
    if not isinstance(geo, dict):
        return None
    comp = geo.get("addressComponent") or {}
    if not isinstance(comp, dict):
        comp = {}
    formatted = _amap_text(geo.get("formatted_address"))
    poi = _amap_name(geo.get("pois"))
    aoi = _amap_name(geo.get("aois"), inside=True)
    city = _amap_text(comp.get("city")) or _amap_text(comp.get("province"))
    district = _amap_text(comp.get("district"))
    return {
        "address": formatted or poi or aoi,
        "poi": poi or aoi,
        "city": city,
        "district": district,
    }


def _amap_route(
    key: str, mode: str, olng: float, olat: float, dlng: float, dlat: float
) -> tuple[float, int, str | None] | None:
    origin = f"{olng:.6f},{olat:.6f}"
    destination = f"{dlng:.6f},{dlat:.6f}"
    bike = mode == COMMUTE_MODE_BICYCLING
    endpoint = (
        "https://restapi.amap.com/v5/direction/electrobike"
        if bike
        else "https://restapi.amap.com/v5/direction/driving"
    )
    try:
        response = requests.get(
            endpoint,
            params={
                "key": key,
                "origin": origin,
                "destination": destination,
                "show_fields": "cost" if bike else "cost,tmcs",
            },
            timeout=15,
        )
        data = response.json()
    except (OSError, ValueError, requests.RequestException):
        return None
    if str(data.get("status")) != "1":
        return None
    paths = (data.get("route") or {}).get("paths") or []
    if not paths:
        return None
    path = paths[0]
    if not isinstance(path, dict):
        return None
    cost = path.get("cost")
    if not isinstance(cost, dict):
        cost = {}
    try:
        meters = float(path.get("distance") or 0)
        seconds = float(cost.get("duration") or 0)
    except (TypeError, ValueError):
        return None
    steps = path.get("steps") or []
    first = steps[0] if steps and isinstance(steps[0], dict) else None
    info = _amap_text(first.get("instruction")) if first else None
    if not bike:
        traffic = _amap_traffic(path)
        if traffic:
            info = f"{info} · {traffic}" if info else traffic
    minutes = 0 if meters < 50 else max(1, int(round(seconds / 60)))
    return round(meters / 1000, 2), minutes, info


def _format_commute_time(minutes: int) -> str:
    total = max(0, int(minutes))
    if total < 60:
        return f"{total}分钟"
    days = total // 1440
    hours = (total % 1440) // 60
    mins = total % 60
    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if mins:
        parts.append(f"{mins}分钟")
    return "".join(parts) if parts else "0分钟"


_ENTITY_SUFFIXES = (
    "_phone_status",
    "_location_time",
    "_icloud_update_time",
    "_update_time",
    "_icloud_query_time",
    "_query_time",
    "_commute_distance",
    "_commute_time",
    "_commute_info",
    "_address",
    "_battery",
    "_steps",
    "_send_message",
    "_lost_device",
    "_lost_number",
    "_lost_message",
    "_play_sound",
    "_message",
)


def _unique_id_to_device_id(unique_id: str) -> str:
    for suffix in _ENTITY_SUFFIXES:
        if unique_id.endswith(suffix):
            return unique_id[: -len(suffix)]
    return unique_id


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_APPLE_DEVICE_RE = re.compile(
    r"(?:的)?\s*(iphone|ipad|ipod|watch|imac|macbook(?:air|pro)?|mac\s*mini|airpods)",
    re.I,
)


_ACTIVITY_NOISE = {
    "iphone",
    "ipad",
    "ipod",
    "watch",
    "imac",
    "macbook",
    "mac",
    "airpods",
    "icloud",
}


def device_object_slug(name: str, fallback: str) -> str:
    text = (name or "").strip()
    cjk = _CJK_RE.findall(text)
    device_m = _APPLE_DEVICE_RE.search(text)
    device_part = slugify(device_m.group(1)) if device_m else ""
    if cjk:
        parts = [p for p in (slugify(cjk[-1]), device_part) if p]
        if parts:
            return "_".join(parts)
    return slugify(text) or slugify(fallback)


def _identity_tokens(text: str) -> set[str]:
    raw = (text or "").strip()
    if not raw:
        return set()
    cleaned = _APPLE_DEVICE_RE.sub(" ", raw)
    tokens: set[str] = set()
    cjk = "".join(_CJK_RE.findall(cleaned))
    if cjk:
        tokens.add(cjk)
    slug = slugify(cleaned)
    if slug:
        for part in slug.split("_"):
            if part and part not in _ACTIVITY_NOISE and len(part) > 1:
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


def _device_activity_tokens(hass: HomeAssistant, device: IcloudDevice) -> set[str]:
    tokens = _identity_tokens(device.name)
    tokens |= _identity_tokens(str(device._attrs.get(ATTR_OWNER_NAME) or ""))
    tracker_ids = {f"device_tracker.{device.object_slug}_icloud"}
    entity_id = er.async_get(hass).async_get_entity_id(
        "device_tracker", DOMAIN, device.unique_id
    )
    if entity_id:
        tracker_ids.add(entity_id)
    for state in hass.states.async_all("person"):
        trackers = state.attributes.get("device_trackers") or []
        if not any(tracker in tracker_ids for tracker in trackers):
            continue
        tokens |= _identity_tokens(state.name)
        tokens |= _identity_tokens(state.entity_id.split(".", 1)[-1])
        tokens |= _identity_tokens(str(state.attributes.get("friendly_name") or ""))
        tokens |= _identity_tokens(str(state.attributes.get("id") or ""))
    return tokens


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


def _status_battery_available(status: dict[str, Any]) -> bool:
    battery_status = status.get(DEVICE_BATTERY_STATUS)
    if battery_status is None or str(battery_status).lower() == "unknown":
        return False
    return status.get(DEVICE_BATTERY_LEVEL) is not None


def _location_epoch(location: dict[str, Any] | None) -> float | None:
    if not location:
        return None
    ts = location.get(DEVICE_LOCATION_TIMESTAMP)
    if ts is None:
        return None
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return None
    if value > 1e12:
        value /= 1000
    return value


class IcloudAccount:
    """Representation of an iCloud account."""

    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        icloud_dir: Store,
        with_family: bool,
        max_interval: int,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize an iCloud account."""
        self.hass = hass
        self._username = username
        self._password = password
        self._with_family = with_family
        self._fetch_interval: float = max_interval
        self._max_interval = max_interval
        self._peak_enabled = DEFAULT_PEAK_ENABLED
        self._peak_windows: list[tuple[int, int]] = []
        self._offpeak_enabled = DEFAULT_OFFPEAK_ENABLED
        self._offpeak_windows: list[tuple[int, int]] = []
        self._peak_interval = DEFAULT_PEAK_INTERVAL
        self._offpeak_interval = DEFAULT_OFFPEAK_INTERVAL
        self._period_weekdays = DEFAULT_PERIOD_WEEKDAYS

        self._icloud_dir = icloud_dir

        self.api: PyiCloudService | None = None
        self._owner_fullname: str | None = None
        self._family_members_fullname: dict[str, str] = {}
        self._devices: dict[str, IcloudDevice] = {}
        self._retried_fetch = False
        self._locate_count = 0
        self._amap_count = 0
        self._usage_day: str | None = None
        self._locate_restored = False
        self._amap_restored = False
        self._all_in_zone = False
        self._config_entry = config_entry
        self._load_period_options()

        self.listeners: list[CALLBACK_TYPE] = []
        self._unsub_polling: CALLBACK_TYPE | None = None
        self._unsub_midnight: CALLBACK_TYPE | None = None
        self._shutdown = False
        self._reauth_requested = False
        self._query_timestamp: datetime | None = None
        self._update_lock = threading.Lock()

    def _stop_api(self) -> None:
        if self.api is not None and self.api._devices is not None:
            devices = self.api._devices
            devices.stop_event.set()
            monitor = devices._monitor
            if monitor is not None and monitor.is_alive():
                monitor.join(timeout=30)
                if monitor.is_alive():
                    _LOGGER.warning(
                        "Find My monitor thread did not stop for %s", self._username
                    )
        self.api = None

    def _clear_session_files(self) -> None:
        clear_session_files(self._icloud_dir.path, self._username)

    def setup(self, *, schedule_update: bool = True) -> None:
        """Set up an iCloud account."""
        self._stop_api()
        try:
            self.api = PyiCloudService(
                self._username,
                self._password,
                self._icloud_dir.path,
                with_family=self._with_family,
                china_mainland=True,
                accept_terms=True,
            )

            if self.api.requires_2fa or self.api.requires_2sa:
                raise PyiCloudFailedLoginException("Authentication required")

        except PyiCloudFailedLoginException:
            _LOGGER.error(
                (
                    "Your password for '%s' is no longer working; Go to the "
                    "Integrations menu and click on Configure on the discovered Apple "
                    "iCloud card to login again"
                ),
                self._config_entry.data[CONF_USERNAME],
            )

            self._require_reauth(start_flow=False)
            raise ConfigEntryAuthFailed("Authentication required")

        self.api.set_on_locate(self._bump_locate)

        try:
            user_info = self.api.devices.user_info
        except (
            PyiCloudFailedLoginException,
            PyiCloud2FARequiredException,
            PyiCloud2SARequiredException,
            PyiCloudAuthRequiredException,
        ):
            self._require_reauth(start_flow=False)
            raise ConfigEntryAuthFailed("Authentication required")
        except (
            PyiCloudServiceNotActivatedException,
            PyiCloudNoDevicesException,
            PyiCloudServiceUnavailable,
        ) as err:
            _LOGGER.error("No iCloud device found")
            self._stop_api()
            raise ConfigEntryNotReady from err

        if user_info is None:
            self._stop_api()
            raise ConfigEntryNotReady("No user info found in iCloud devices response")

        self._owner_fullname = (
            f"{user_info.get('firstName') or ''} {user_info.get('lastName') or ''}"
        ).strip()

        self._family_members_fullname = {}
        if user_info.get("membersInfo") is not None:
            for prs_id, member in user_info["membersInfo"].items():
                name = (
                    f"{member.get('firstName') or ''} {member.get('lastName') or ''}"
                ).strip()
                if name:
                    self._family_members_fullname[str(prs_id)] = name

        self._reauth_requested = False
        self.hass.data.pop(self._reauth_flag_key(), None)
        self._schedule_midnight_reset()
        if schedule_update:
            self._query_timestamp = datetime.now(timezone.utc)
            locate_done = False
            try:
                locate_done = self._poll_locate_results(self.api)
            except Exception:  # pylint: disable=broad-except
                locate_done = False
            self.update_devices(locate_done=locate_done)

    def update_devices(self, *, locate_done: bool = True) -> None:
        """Update iCloud devices."""
        if self._shutdown:
            return
        if not self._update_lock.acquire(blocking=False):
            if not self._reauth_in_progress():
                self._schedule_polling(self._fetch_interval)
            return
        try:
            self._update_devices(locate_done=locate_done)
        finally:
            self._update_lock.release()

    def _update_devices(
        self, *, accept_inaccurate: bool = False, locate_done: bool = True
    ) -> None:
        api = self.api
        if api is None:
            if not self._reauth_in_progress():
                self._schedule_polling(self._fetch_interval)
            if accept_inaccurate:
                raise ServiceValidationError("iCloud account is not available")
            return

        if api.requires_2fa or api.requires_2sa:
            self._require_reauth()
            if accept_inaccurate:
                raise ServiceValidationError("iCloud account is not available")
            return

        api_devices = {}
        try:
            api_devices = api.devices
        except (
            PyiCloudFailedLoginException,
            PyiCloud2FARequiredException,
            PyiCloud2SARequiredException,
            PyiCloudAuthRequiredException,
        ):
            self._require_reauth()
            if accept_inaccurate:
                raise ServiceValidationError("iCloud account is not available")
            return
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Unknown iCloud error: %s", err)
            if api.requires_2fa or api.requires_2sa:
                self._require_reauth()
                if accept_inaccurate:
                    raise ServiceValidationError("iCloud account is not available")
                return
            self._fetch_interval = 5
            dispatcher_send(self.hass, self.signal_device_update)
            self._schedule_polling(self._fetch_interval)
            if accept_inaccurate:
                raise ServiceValidationError("Failed to refresh iCloud location") from err
            return

        if self._shutdown:
            if accept_inaccurate:
                raise ServiceValidationError("iCloud account is not available")
            return

        try:
            registered_ids = self._hass_call(self._collect_registered_device_ids)
        except Exception:  # pylint: disable=broad-except
            registered_ids = set(self._devices)

        # Gets devices infos
        new_device = False
        try:
            for device in api_devices:
                if self._shutdown:
                    if accept_inaccurate:
                        raise ServiceValidationError("iCloud account is not available")
                    return
                status = device.status(DEVICE_STATUS_SET)
                device_id = status.get(DEVICE_ID)
                if not device_id:
                    continue
                device_name = status.get(DEVICE_NAME, device_id)

                if self._devices.get(device_id) is not None:
                    _LOGGER.debug("Updating iCloud device: %s", device_name)
                    self._devices[device_id]._device = device
                    self._devices[device_id].update(status)
                elif not _status_battery_available(status):
                    if device_id not in registered_ids:
                        continue
                    _LOGGER.debug(
                        "Restoring registered iCloud device without battery: %s",
                        device_name,
                    )
                    self._devices[device_id] = IcloudDevice(self, device, status)
                    self._devices[device_id].update(status)
                    new_device = True
                else:
                    _LOGGER.debug(
                        "Adding iCloud device: %s [model: %s]",
                        device_name,
                        status.get(DEVICE_RAW_DEVICE_MODEL),
                    )
                    self._devices[device_id] = IcloudDevice(self, device, status)
                    self._devices[device_id].update(status)
                    new_device = True
        except (
            PyiCloudFailedLoginException,
            PyiCloud2FARequiredException,
            PyiCloud2SARequiredException,
            PyiCloudAuthRequiredException,
        ):
            self._require_reauth()
            if accept_inaccurate:
                raise ServiceValidationError("iCloud account is not available")
            return
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Error updating iCloud devices: %s", err)
            if api.requires_2fa or api.requires_2sa:
                self._require_reauth()
                if accept_inaccurate:
                    raise ServiceValidationError("iCloud account is not available")
                return
            dispatcher_send(self.hass, self.signal_device_update)
            self._schedule_polling(self._fetch_interval)
            if accept_inaccurate:
                raise ServiceValidationError("Failed to refresh iCloud location") from err
            return

        if self._shutdown:
            if accept_inaccurate:
                raise ServiceValidationError("iCloud account is not available")
            return

        pending_retry = False
        try:
            if (
                len(api_devices) > 0
                and DEVICE_STATUS_CODES.get(
                    str(list(api_devices)[0].status([DEVICE_STATUS]).get(DEVICE_STATUS))
                )
                == "pending"
                and not self._retried_fetch
            ):
                _LOGGER.debug("Pending devices, trying again in 30s")
                self._fetch_interval = 0.5
                self._retried_fetch = True
                pending_retry = True
            else:
                self._fetch_interval = self._determine_interval()
                self._retried_fetch = False
        except (
            PyiCloudFailedLoginException,
            PyiCloud2FARequiredException,
            PyiCloud2SARequiredException,
            PyiCloudAuthRequiredException,
        ):
            self._require_reauth()
            dispatcher_send(self.hass, self.signal_device_update)
            if accept_inaccurate:
                raise ServiceValidationError("iCloud account is not available")
            return
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Error determining iCloud poll interval: %s", err)
            self._fetch_interval = self._max_interval
            self._retried_fetch = False

        if self._shutdown:
            dispatcher_send(self.hass, self.signal_device_update)
            if accept_inaccurate:
                raise ServiceValidationError("iCloud account is not available")
            return

        if pending_retry and not accept_inaccurate:
            self._schedule_polling(self._fetch_interval)
            return

        self._update_commute()
        self._finish_device_sync(new_device)
        self._schedule_polling(self._fetch_interval)

    def _finish_device_sync(self, new_device: bool) -> None:
        def _run() -> None:
            if self._shutdown:
                return
            self._purge_unavailable_devices()
            dispatcher_send(self.hass, self.signal_device_update)
            if new_device:
                dispatcher_send(self.hass, self.signal_device_new)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                self.hass.loop.call_soon_threadsafe(_run)
            except RuntimeError:
                pass
        else:
            _run()

    @callback
    def _collect_registered_device_ids(self) -> set[str]:
        device_reg = dr.async_get(self.hass)
        ids: set[str] = set()
        for device_entry in dr.async_entries_for_config_entry(
            device_reg, self._config_entry.entry_id
        ):
            for ident in device_entry.identifiers:
                if ident[0] != DOMAIN:
                    continue
                device_id = ident[1]
                if device_id.endswith(INTEGRATION_HUB_SUFFIX):
                    continue
                ids.add(device_id)
        return ids

    @callback
    def _last_known_location(self, device_id: str) -> dict[str, Any] | None:
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "device_tracker", DOMAIN, device_id
        )
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        lat = state.attributes.get("latitude")
        lon = state.attributes.get("longitude")
        if lat is None or lon is None:
            return None
        location: dict[str, Any] = {
            DEVICE_LOCATION_LATITUDE: float(lat),
            DEVICE_LOCATION_LONGITUDE: float(lon),
        }
        acc = state.attributes.get("gps_accuracy")
        if acc is not None:
            try:
                location[DEVICE_LOCATION_HORIZONTAL_ACCURACY] = float(acc)
            except (TypeError, ValueError):
                pass
        return location

    @callback
    def _purge_unavailable_devices(self) -> None:
        keep_devices = dict(self._devices)
        keep_slugs = {device.object_slug for device in keep_devices.values()}
        entity_reg = er.async_get(self.hass)
        for entry in er.async_entries_for_config_entry(
            entity_reg, self._config_entry.entry_id
        ):
            uid = entry.unique_id
            if not uid:
                continue
            if any(
                uid.endswith(f"{INTEGRATION_HUB_SUFFIX}_{suffix}")
                for suffix in (
                    "update",
                    "created_at",
                    "query_time",
                    "locate_count",
                    "amap_count",
                )
            ):
                continue
            if (
                uid.endswith("_location_time")
                or (
                    uid.endswith("_update_time")
                    and not uid.endswith("_icloud_update_time")
                )
                or uid.endswith("_icloud_query_time")
                or uid.endswith("_query_time")
            ):
                entity_reg.async_remove(entry.entity_id)
                continue
            if uid.endswith("_icloud_update_time"):
                slug = uid[: -len("_icloud_update_time")]
                if slug not in keep_slugs:
                    continue
                desired = f"{entry.domain}.{slug}_icloud_update_time"
            else:
                device_id = _unique_id_to_device_id(uid)
                if device_id not in keep_devices:
                    continue
                slug = keep_devices[device_id].object_slug
                if uid.endswith("_phone_status"):
                    object_id = f"{slug}_icloud_status"
                elif uid.endswith("_battery"):
                    object_id = f"{slug}_icloud_battery"
                elif uid.endswith("_steps"):
                    object_id = f"{slug}_icloud_steps"
                elif uid.endswith("_address"):
                    object_id = f"{slug}_icloud_address"
                elif uid.endswith("_commute_distance"):
                    object_id = f"{slug}_icloud_commute_distance"
                elif uid.endswith("_commute_time"):
                    object_id = f"{slug}_icloud_commute_time"
                elif uid.endswith("_commute_info"):
                    object_id = f"{slug}_icloud_commute_info"
                elif uid.endswith("_send_message"):
                    object_id = f"{slug}_icloud_send_message"
                elif uid.endswith("_lost_device"):
                    object_id = f"{slug}_icloud_lost_device"
                elif uid.endswith("_lost_number"):
                    object_id = f"{slug}_icloud_lost_number"
                elif uid.endswith("_lost_message"):
                    object_id = f"{slug}_icloud_lost_message"
                elif uid.endswith("_play_sound"):
                    object_id = f"{slug}_icloud_play_sound"
                elif uid.endswith("_message"):
                    object_id = f"{slug}_icloud_message"
                else:
                    object_id = f"{slug}_icloud"
                desired = f"{entry.domain}.{object_id}"
            if entry.entity_id != desired:
                try:
                    entity_reg.async_update_entity(
                        entry.entity_id, new_entity_id=desired
                    )
                except (ValueError, HomeAssistantError):
                    pass

    def _cancel_polling(self) -> None:
        if not self._unsub_polling:
            return
        unsub = self._unsub_polling
        self._unsub_polling = None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                self.hass.loop.call_soon_threadsafe(unsub)
            except RuntimeError:
                pass
        else:
            unsub()

    def _schedule_polling(self, interval_minutes: float) -> None:
        if self._shutdown or self._reauth_in_progress():
            return
        all_far = bool(
            self._devices
            and all(device._away_far for device in self._devices.values())
        )
        if not all_far:
            period_cap, period_fixed = self._period_interval_cap()
            if period_fixed:
                interval_minutes = min(float(interval_minutes), float(period_cap))
            if self._all_in_zone:
                if not period_fixed:
                    until_boundary = self._minutes_until_next_boundary(
                        peak_starts_only=True
                    )
                    if until_boundary is not None:
                        interval_minutes = min(
                            interval_minutes, max(until_boundary, 0.05)
                        )
            else:
                until_boundary = self._minutes_until_next_boundary()
                if until_boundary is not None:
                    interval_minutes = min(
                        interval_minutes, max(until_boundary, 0.05)
                    )

        @callback
        def _schedule() -> None:
            if self._shutdown or self._reauth_in_progress():
                return
            if self._unsub_polling:
                self._unsub_polling()
                self._unsub_polling = None
            self._unsub_polling = async_track_point_in_utc_time(
                self.hass,
                self._trigger_keep_alive,
                utcnow() + timedelta(minutes=interval_minutes),
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                self.hass.loop.call_soon_threadsafe(_schedule)
            except RuntimeError:
                pass
        else:
            _schedule()

    def _cancel_midnight(self) -> None:
        if not self._unsub_midnight:
            return
        unsub = self._unsub_midnight
        self._unsub_midnight = None
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                self.hass.loop.call_soon_threadsafe(unsub)
            except RuntimeError:
                pass
        else:
            unsub()

    def _schedule_midnight_reset(self) -> None:
        if self._shutdown:
            return

        @callback
        def _schedule() -> None:
            if self._shutdown or self._unsub_midnight:
                return
            self._unsub_midnight = async_track_time_change(
                self.hass, self._reset_daily_steps, hour=0, minute=0, second=0
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                self.hass.loop.call_soon_threadsafe(_schedule)
            except RuntimeError:
                pass
        else:
            _schedule()

    @callback
    def _reset_daily_steps(self, _now=None) -> None:
        if self._shutdown:
            return
        self._roll_usage_day()
        for device in list(self._devices.values()):
            device._reset_steps_if_new_day()
        dispatcher_send(self.hass, self.signal_device_update)

    @callback
    def _trigger_keep_alive(self, _now=None) -> None:
        if self._shutdown or self._reauth_in_progress():
            return
        self._config_entry.async_create_background_task(
            self.hass, self.async_keep_alive(), f"{DOMAIN} keep_alive {self._username}"
        )

    async def async_keep_alive(self, force_locate: bool = False) -> None:
        if self._shutdown or self._reauth_in_progress():
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return
        await self.hass.async_add_executor_job(self.keep_alive, None, force_locate)

    def shutdown(self) -> None:
        self._shutdown = True
        self._cancel_polling()
        self._cancel_midnight()
        listeners = list(self.listeners)
        self.listeners.clear()
        self.hass.data.pop(self._reauth_flag_key(), None)
        acquired = self._update_lock.acquire(blocking=True, timeout=60)
        try:
            if acquired:
                self._stop_api()
            else:
                api = self.api
                self.api = None
                if api is not None and api._devices is not None:
                    devices = api._devices
                    devices.stop_event.set()
                    monitor = devices._monitor
                    if monitor is not None and monitor.is_alive():
                        monitor.join(timeout=30)
        finally:
            if acquired:
                self._update_lock.release()
        for unsub in listeners:
            try:
                self.hass.loop.call_soon_threadsafe(unsub)
            except RuntimeError:
                try:
                    unsub()
                except Exception:  # pylint: disable=broad-except
                    pass

    def _reauth_in_progress(self) -> bool:
        return self._reauth_requested or bool(
            self.hass.data.get(self._reauth_flag_key())
        )

    def _reauth_flag_key(self) -> str:
        return f"{DOMAIN}_reauth_{self._config_entry.entry_id}"

    def _require_reauth(self, *, start_flow: bool = True):
        """Require the user to log in again."""
        if self._shutdown:
            return
        already = bool(self.hass.data.get(self._reauth_flag_key()))
        self._reauth_requested = True
        self.hass.data[self._reauth_flag_key()] = True
        self._cancel_polling()
        self._stop_api()
        if already:
            return
        self._clear_session_files()
        if start_flow:
            self.hass.add_job(self._config_entry.async_start_reauth, self.hass)

    def _hass_call(self, func, *args):
        loop = self.hass.loop
        ident = loop.__dict__.get("_thread_id")
        if ident is None:
            ident = loop.__dict__.get("_thread_ident")
        if ident == threading.get_ident():
            return func(*args)
        return run_callback_threadsafe(loop, func, *args).result(timeout=10)

    @callback
    def _zone_points(self) -> list[tuple[float, float, float]]:
        points: list[tuple[float, float, float]] = []
        for entity_id in self.hass.states.async_entity_ids("zone"):
            zone_state = self.hass.states.get(entity_id)
            if zone_state is None or zone_state.attributes.get("passive"):
                continue
            zone_state_lat = zone_state.attributes.get(DEVICE_LOCATION_LATITUDE)
            zone_state_long = zone_state.attributes.get(DEVICE_LOCATION_LONGITUDE)
            if zone_state_lat is None or zone_state_long is None:
                continue
            try:
                radius = float(zone_state.attributes.get("radius") or 100)
            except (TypeError, ValueError):
                radius = 100.0
            points.append((float(zone_state_lat), float(zone_state_long), radius))
        return points

    @callback
    def _zone_coordinates(self) -> list[tuple[float, float]]:
        return [(lat, lon) for lat, lon, _radius in self._zone_points()]

    @callback
    def _home_zones(self) -> list[tuple[str, str, float, float, float]]:
        result: list[tuple[str, str, float, float, float]] = []
        zone_ids = self._opt(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES)
        if isinstance(zone_ids, str):
            zone_ids = [zone_ids] if zone_ids else []
        elif not isinstance(zone_ids, list):
            zone_ids = []
        for entity_id in zone_ids:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            lat = state.attributes.get(DEVICE_LOCATION_LATITUDE)
            lon = state.attributes.get(DEVICE_LOCATION_LONGITUDE)
            if lat is None or lon is None:
                continue
            try:
                radius = float(state.attributes.get("radius") or 100)
            except (TypeError, ValueError):
                radius = 100.0
            name = state.attributes.get("friendly_name") or entity_id
            result.append((entity_id, str(name), float(lat), float(lon), radius))
        return result

    def _activity_mode(self, device: IcloudDevice, entity_ids: list[str]) -> str | None:
        if not entity_ids:
            return None
        tokens = _device_activity_tokens(self.hass, device)
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
        try:
            devices = list(self._devices.values())
        except RuntimeError:
            devices = []
        for device in devices:
            modes[device.unique_id] = self._activity_mode(device, entity_ids)
        return self._home_zones(), modes

    def _update_commute(self) -> None:
        if not bool(self._opt(CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED)):
            return
        key = str(self._opt(CONF_AMAP_KEY, "") or "").strip()
        if not key:
            return
        devices = [
            device
            for device in self._devices.values()
            if device._commute_pending and device.location
        ]
        if not devices:
            return
        try:
            zones, modes = self._hass_call(self._commute_context)
        except TimeoutError:
            return
        if not zones:
            for device in devices:
                device._commute_pending = False
            return
        for device in devices:
            if self._shutdown:
                return
            device._commute_pending = False
            try:
                device._apply_commute(key, modes.get(device.unique_id), zones)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.debug("Commute update failed for %s: %s", device.name, err)

    def _opt(self, key: str, default):
        return self._config_entry.options.get(
            key, self._config_entry.data.get(key, default)
        )

    def _roll_usage_day(self) -> None:
        day = dt_now().strftime("%Y-%m-%d")
        if self._usage_day is None:
            self._usage_day = day
            return
        if self._usage_day == day:
            return
        self._usage_day = day
        self._locate_count = 0
        self._amap_count = 0
        self._locate_restored = False
        self._amap_restored = False

    def _bump_locate(self) -> None:
        self._roll_usage_day()
        self._locate_count += 1

    def _bump_amap(self) -> None:
        self._roll_usage_day()
        self._amap_count += 1

    def restore_usage(
        self, *, locate: int | None = None, amap: int | None = None, day: str | None
    ) -> None:
        current = dt_now().strftime("%Y-%m-%d")
        if day is None:
            day = current
        self._roll_usage_day()
        if day != current:
            return
        if locate is not None and not self._locate_restored:
            self._locate_restored = True
            self._locate_count += locate
        if amap is not None and not self._amap_restored:
            self._amap_restored = True
            self._amap_count += amap

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

    def _parse_opt_windows(self, key: str, default: str) -> list[tuple[int, int]]:
        return parse_windows(opt_windows_text(self._opt(key, default), default)) or []

    def _load_period_options(self) -> None:
        self._peak_enabled = bool(
            self._opt(CONF_PEAK_ENABLED, DEFAULT_PEAK_ENABLED)
        )
        self._offpeak_enabled = bool(
            self._opt(CONF_OFFPEAK_ENABLED, DEFAULT_OFFPEAK_ENABLED)
        )
        self._peak_windows = self._parse_opt_windows(
            CONF_PEAK_WINDOWS, DEFAULT_PEAK_WINDOWS
        )
        self._offpeak_windows = self._parse_opt_windows(
            CONF_OFFPEAK_WINDOWS, DEFAULT_OFFPEAK_WINDOWS
        )
        self._peak_interval = int(
            self._opt(CONF_PEAK_INTERVAL, DEFAULT_PEAK_INTERVAL)
        )
        self._offpeak_interval = int(
            self._opt(CONF_OFFPEAK_INTERVAL, DEFAULT_OFFPEAK_INTERVAL)
        )
        self._period_weekdays = bool(
            self._opt(CONF_PERIOD_WEEKDAYS, DEFAULT_PERIOD_WEEKDAYS)
        )

    def _weekday_periods(self, weekday: int) -> bool:
        return not self._period_weekdays or weekday < 5

    def _period_interval_cap(self) -> tuple[int, bool]:
        now = dt_now()
        now_min = now.hour * 60 + now.minute
        if not self._weekday_periods(now.weekday()):
            return self._max_interval, False
        if self._peak_enabled and in_windows(now_min, self._peak_windows):
            return self._peak_interval, True
        if self._offpeak_enabled and in_windows(now_min, self._offpeak_windows):
            return self._offpeak_interval, True
        return self._max_interval, False

    def _period_interval(self) -> int:
        value, fixed = self._period_interval_cap()
        if fixed:
            return value
        return random.randint(1, value)

    def _local_interval(
        self, in_zone: bool, battery_level: int | None = None
    ) -> int:
        if in_zone:
            now = dt_now()
            now_min = now.hour * 60 + now.minute
            if (
                self._weekday_periods(now.weekday())
                and self._peak_enabled
                and in_windows(now_min, self._peak_windows)
            ):
                return self._peak_interval
            return self._max_interval
        value, fixed = self._period_interval_cap()
        if battery_level is not None and battery_level <= LOW_BATTERY_LEVEL:
            value *= 2
        if fixed:
            return value
        return random.randint(1, value)

    def _far_interval(self, km: float, battery_level: int | None) -> int:
        if km < 100:
            interval = FAR_INTERVAL_50_100
        elif km < 200:
            interval = FAR_INTERVAL_100_200
        elif km < 300:
            interval = FAR_INTERVAL_200_300
        elif km < 800:
            interval = FAR_INTERVAL_300_800
        elif km < 2000:
            interval = FAR_INTERVAL_800_2000
        else:
            interval = FAR_INTERVAL_2000_PLUS
        if battery_level is not None and battery_level <= LOW_BATTERY_LEVEL:
            interval *= 2
        return random.randint(1, interval)

    def _probe_device_geo(self, device: IcloudDevice) -> tuple[bool | None, float | None]:
        if device.location is None:
            return None, None
        device_lat = device.location.get(DEVICE_LOCATION_LATITUDE)
        device_long = device.location.get(DEVICE_LOCATION_LONGITUDE)
        device_accuracy = device.location.get(DEVICE_LOCATION_HORIZONTAL_ACCURACY)
        if device_lat is None or device_long is None:
            return None, None
        try:
            current_zone = self._hass_call(
                async_active_zone,
                self.hass,
                device_lat,
                device_long,
                device_accuracy or 0,
            )
        except TimeoutError:
            if device._zone_sticky:
                return True, 0.0
            return None, None
        try:
            zone_points = self._hass_call(self._zone_points)
        except TimeoutError:
            if device._zone_sticky:
                return True, 0.0
            zone_points = []
        min_km = None
        nearest_extra_m = None
        for zone_lat, zone_lon, zone_radius in zone_points:
            zone_distance = distance(
                device_lat,
                device_long,
                zone_lat,
                zone_lon,
            )
            if zone_distance is None:
                continue
            km = round(zone_distance / 1000, 1)
            if min_km is None or km < min_km:
                min_km = km
            extra = zone_distance - zone_radius
            if nearest_extra_m is None or extra < nearest_extra_m:
                nearest_extra_m = extra
        if current_zone is not None:
            device._zone_sticky = True
            return True, 0.0
        if device._zone_sticky:
            if nearest_extra_m is None or nearest_extra_m <= HOME_EXIT_BUFFER_M:
                return True, 0.0
            device._zone_sticky = False
        elif nearest_extra_m is not None and nearest_extra_m <= 0:
            device._zone_sticky = True
            return True, 0.0
        return False, min_km

    def _minutes_until_next_boundary(
        self, *, peak_starts_only: bool = False
    ) -> float | None:
        now = dt_now()
        now_min = now.hour * 60 + now.minute
        now_frac = now.second / 60 + now.microsecond / 60000000
        soonest = None

        def _consider(delta: float) -> None:
            nonlocal soonest
            if delta <= 0:
                return
            if soonest is None or delta < soonest:
                soonest = delta

        for day_offset in (0, 1, 2):
            weekday = (now.weekday() + day_offset) % 7
            if self._weekday_periods(weekday):
                if peak_starts_only:
                    if self._peak_enabled:
                        for start, end in self._peak_windows:
                            if start == end:
                                continue
                            _consider(
                                day_offset * 24 * 60 + start - now_min - now_frac
                            )
                else:
                    windows = []
                    if self._peak_enabled:
                        windows.extend(self._peak_windows)
                    if self._offpeak_enabled:
                        windows.extend(self._offpeak_windows)
                    for start, end in windows:
                        if start == end:
                            continue
                        for bound in (start, end):
                            _consider(
                                day_offset * 24 * 60 + bound - now_min - now_frac
                            )
            if day_offset > 0 and self._period_weekdays:
                prev = (now.weekday() + day_offset - 1) % 7
                if self._weekday_periods(prev) != self._weekday_periods(weekday):
                    _consider(day_offset * 24 * 60 - now_min - now_frac)
        return soonest

    def _determine_interval(self) -> int:
        intervals: list[int] = []
        all_in_zone = True
        saw_device = False
        for device in self._devices.values():
            if self._shutdown:
                break
            saw_device = True
            in_zone, km = self._probe_device_geo(device)
            if in_zone is True:
                device._away_far = False
                intervals.append(self._local_interval(True))
                continue
            all_in_zone = False
            if in_zone is None:
                value, fixed = self._period_interval_cap()
                battery_level = device.battery_level
                if battery_level is not None and battery_level <= LOW_BATTERY_LEVEL:
                    value *= 2
                intervals.append(value if fixed else self._max_interval)
                continue
            if km is None:
                intervals.append(
                    self._local_interval(False, device.battery_level)
                )
                continue
            if device._away_far:
                if km < LOCAL_DISTANCE_KM:
                    device._away_far = False
            elif km > FAR_DISTANCE_KM:
                device._away_far = True
            if device._away_far:
                intervals.append(self._far_interval(km, device.battery_level))
            else:
                intervals.append(
                    self._local_interval(False, device.battery_level)
                )
        self._all_in_zone = bool(saw_device and all_in_zone and intervals)
        if not intervals:
            self._all_in_zone = False
            return self._max_interval
        return min(intervals)

    def keep_alive(self, now=None, force_locate: bool = False) -> None:
        """Keep the API alive."""
        if self._shutdown:
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return
        if force_locate:
            if not self._update_lock.acquire(blocking=True, timeout=60):
                raise ServiceValidationError("iCloud account is busy")
        elif not self._update_lock.acquire(blocking=False):
            if not self._reauth_in_progress():
                self._schedule_polling(self._fetch_interval)
            return
        try:
            self._keep_alive_locked(force_locate=force_locate)
        finally:
            self._update_lock.release()

    def _location_stamps(self, api: PyiCloudService) -> tuple[tuple[Any, ...], ...]:
        stamps = []
        tracked = set(self._devices) if self._devices else None
        for device in api.devices:
            info = device.status(["id", "location"])
            device_id = info.get("id")
            if tracked is not None and device_id not in tracked:
                continue
            loc = info.get("location") or {}
            stamps.append(
                (
                    device_id,
                    loc.get("timeStamp"),
                    loc.get("latitude"),
                    loc.get("longitude"),
                )
            )
        return tuple(stamps)

    def _poll_locate_results(self, api: PyiCloudService) -> bool:
        previous = self._location_stamps(api)
        tracked = set(self._devices) if self._devices else None
        for _ in range(5):
            if self._shutdown or self.api is None:
                return False
            time.sleep(4)
            if self._shutdown or self.api is None:
                return False
            api.devices.refresh(locate=False)
            current = self._location_stamps(api)
            if current != previous:
                return True
            locating = False
            for device in api.devices:
                info = device.status(["id", "isLocating"])
                device_id = info.get("id")
                if tracked is not None and device_id not in tracked:
                    continue
                if info.get("isLocating"):
                    locating = True
                    break
            if not locating:
                return True
        return True

    def _keep_alive_locked(self, force_locate: bool = False) -> None:
        if self._shutdown:
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return
        api = self.api
        if api is None:
            if self.hass.data.get(self._reauth_flag_key()):
                if force_locate:
                    raise ServiceValidationError("iCloud account is not available")
                return
            if self._shutdown:
                if force_locate:
                    raise ServiceValidationError("iCloud account is not available")
                return
            if self._reauth_requested:
                self._reauth_requested = False
            try:
                self.setup(schedule_update=False)
            except ConfigEntryAuthFailed:
                if force_locate:
                    raise ServiceValidationError("iCloud account is not available")
                return
            except ConfigEntryNotReady:
                if not self._reauth_in_progress():
                    self._schedule_polling(self._fetch_interval)
                if force_locate:
                    raise ServiceValidationError("iCloud account is not available")
                return
            api = self.api

        if self._shutdown or api is None:
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return

        try:
            api.authenticate()
        except (
            PyiCloudFailedLoginException,
            PyiCloud2FARequiredException,
            PyiCloud2SARequiredException,
            PyiCloudAuthRequiredException,
        ):
            self._require_reauth()
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Authentication failed: %s", err)
            if api.requires_2fa or api.requires_2sa:
                self._require_reauth()
            if force_locate:
                raise ServiceValidationError("iCloud account is not available") from err
            self._schedule_polling(self._fetch_interval)
            return

        if self._shutdown:
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return
        api = self.api
        if api is None:
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return
        if api.requires_2fa or api.requires_2sa:
            self._require_reauth()
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return

        locate_done = False
        try:
            self._query_timestamp = datetime.now(timezone.utc)
            api.devices.refresh(locate=True)
            locate_done = self._poll_locate_results(api)
        except (
            PyiCloudFailedLoginException,
            PyiCloud2FARequiredException,
            PyiCloud2SARequiredException,
            PyiCloudAuthRequiredException,
        ):
            self._require_reauth()
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return
        except Exception as err:  # pylint: disable=broad-except
            if force_locate:
                raise ServiceValidationError(
                    "Failed to refresh iCloud location"
                ) from err
            _LOGGER.debug("Locate refresh failed: %s", err)
        if self._shutdown or self.api is None:
            if force_locate:
                raise ServiceValidationError("iCloud account is not available")
            return
        self._update_devices(accept_inaccurate=force_locate, locate_done=locate_done)

    def get_devices_with_name(self, name: str) -> list[Any]:
        """Get devices by name."""
        name_slug = slugify(name.replace(" ", "", 99))
        if not self._update_lock.acquire(blocking=True, timeout=60):
            raise ServiceValidationError("iCloud account is busy")
        try:
            devices = list(self._devices.values())
        finally:
            self._update_lock.release()
        result = [
            device
            for device in devices
            if slugify(device.name.replace(" ", "", 99)) == name_slug
        ]
        if not result:
            raise ServiceValidationError(f"No device with name {name}")
        return result

    @property
    def username(self) -> str:
        """Return the account username."""
        return self._username

    @property
    def owner_fullname(self) -> str | None:
        """Return the account owner fullname."""
        return self._owner_fullname

    @property
    def family_members_fullname(self) -> dict[str, str]:
        """Return the account family members fullname."""
        return self._family_members_fullname

    @property
    def fetch_interval(self) -> float:
        """Return the account fetch interval."""
        return self._fetch_interval

    @property
    def query_timestamp(self) -> datetime | None:
        return self._query_timestamp

    @property
    def devices(self) -> dict[str, Any]:
        """Return the account devices."""
        return self._devices

    @property
    def signal_device_new(self) -> str:
        """Event specific per iCloud entry to signal new device."""
        return f"{DOMAIN}-{self._username}-device-new"

    @property
    def signal_device_update(self) -> str:
        """Event specific per iCloud entry to signal updates in devices."""
        return f"{DOMAIN}-{self._username}-device-update"


class IcloudDevice:
    """Representation of a iCloud device."""

    _attr_attribution = "Data provided by Apple iCloud"

    def __init__(self, account: IcloudAccount, device: AppleDevice, status) -> None:
        """Initialize the iCloud device."""
        self._account = account

        self._device = device
        self._status = status

        self._name = self._status.get(DEVICE_NAME) or self._status.get(DEVICE_ID, "Unknown")
        self._device_id = self._status.get(DEVICE_ID, "")
        self._device_class = self._status.get(DEVICE_CLASS, "")
        self._device_model = self._status.get(DEVICE_DISPLAY_NAME, "")

        self._battery_level: int | None = None
        self._battery_status = None
        self._location = None
        self._away_far = False
        self._last_lat: float | None = None
        self._last_lon: float | None = None
        self._last_ts: float | None = None
        self._daily_distance = 0.0
        self._daily_steps = 0
        self._steps_date: date | None = None
        self._location_address: str | None = None
        self._location_poi: str | None = None
        self._location_city: str | None = None
        self._location_district: str | None = None
        self._commute_distance: float | None = None
        self._commute_time: int | None = None
        self._commute_info: str | None = None
        self._commute_pending = False
        self._amap_grid: tuple[int, int] | None = None
        self._amap_route_key: tuple[int, int, int, int, str] | None = None
        self._home_entered_at: float | None = None
        self._home_address_done = False
        self._zone_sticky = False
        self._commute_inside = False
        self.send_message = ""
        self.lost_number = ""
        self.lost_message = ""

        self._attrs = {
            ATTR_ACCOUNT_FETCH_INTERVAL: self._account.fetch_interval,
            ATTR_DEVICE_NAME: self._device_model,
            ATTR_DEVICE_STATUS: None,
        }
        owner_id = self._status.get(DEVICE_PERSON_ID)
        if owner_id is not None:
            owner_name = account.family_members_fullname.get(str(owner_id))
            if owner_name:
                self._attrs[ATTR_OWNER_NAME] = owner_name
        elif account.owner_fullname:
            self._attrs[ATTR_OWNER_NAME] = account.owner_fullname

    def update(self, status) -> None:
        """Update the iCloud device."""
        self._status = status

        self._attrs[ATTR_ACCOUNT_FETCH_INTERVAL] = self._account.fetch_interval

        device_status = DEVICE_STATUS_CODES.get(
            str(self._status.get(DEVICE_STATUS)), "error"
        )
        self._attrs[ATTR_DEVICE_STATUS] = device_status

        self._battery_status = self._status.get(DEVICE_BATTERY_STATUS)
        self._attrs[ATTR_BATTERY_STATUS] = self._battery_status
        device_battery_level = self._status.get(DEVICE_BATTERY_LEVEL)
        if (
            self._battery_status is not None
            and str(self._battery_status).lower() != "unknown"
            and device_battery_level is not None
        ):
            self._battery_level = round(device_battery_level * 100)
            self._attrs[ATTR_BATTERY] = self._battery_level
            self._attrs[ATTR_LOW_POWER_MODE] = self._status.get(DEVICE_LOW_POWER_MODE)
        else:
            self._battery_level = None
            self._attrs.pop(ATTR_BATTERY, None)
            self._attrs.pop(ATTR_LOW_POWER_MODE, None)

        location_data = self._status.get(DEVICE_LOCATION) or {}
        if (
            location_data.get(DEVICE_LOCATION_LATITUDE) is not None
            and location_data.get(DEVICE_LOCATION_LONGITUDE) is not None
        ):
            location = location_data
            if self._location is None and not self._account._shutdown:
                dispatcher_send(self._account.hass, self._account.signal_device_new)
            prev = self._location
            self._location = location
            if (
                prev is None
                or prev.get(DEVICE_LOCATION_LATITUDE)
                != location.get(DEVICE_LOCATION_LATITUDE)
                or prev.get(DEVICE_LOCATION_LONGITUDE)
                != location.get(DEVICE_LOCATION_LONGITUDE)
            ):
                self._commute_pending = True
            self._accumulate_steps(location)
            loc_ts = _location_epoch(location)
            if loc_ts is None:
                loc_ts = dt_now().timestamp()
            self._attrs["timestamp"] = int(loc_ts * 1000)
        elif self._location is None and not self._account._shutdown:
            try:
                last = self._account._hass_call(
                    self._account._last_known_location, self._device_id
                )
            except Exception:  # pylint: disable=broad-except
                last = None
            if last is not None:
                self._location = last
                dispatcher_send(self._account.hass, self._account.signal_device_new)

    def _device_unavailable(self) -> bool:
        if self._account._shutdown or self._account._reauth_in_progress():
            return True
        api = self._account.api
        if api is None:
            return True
        return api.requires_2fa or api.requires_2sa

    def _authenticate_device_action(self) -> None:
        api = self._account.api
        if api is None or self._account._shutdown:
            raise ServiceValidationError("iCloud account is not available")
        try:
            api.authenticate()
        except (
            PyiCloudFailedLoginException,
            PyiCloud2FARequiredException,
            PyiCloud2SARequiredException,
            PyiCloudAuthRequiredException,
        ) as err:
            self._account._require_reauth()
            raise ServiceValidationError("iCloud account is not available") from err
        except Exception as err:
            _LOGGER.error("Authentication failed: %s", err)
            if api.requires_2fa or api.requires_2sa:
                self._account._require_reauth()
            raise ServiceValidationError("iCloud account is not available") from err
        api = self._account.api
        if api is None or self._account._shutdown:
            raise ServiceValidationError("iCloud account is not available")
        if api.requires_2fa or api.requires_2sa:
            self._account._require_reauth()
            raise ServiceValidationError("iCloud account is not available")

    def _handle_device_action_error(self, err: Exception, failed_msg: str) -> None:
        api = self._account.api
        need_reauth = isinstance(
            err, (PyiCloud2FARequiredException, PyiCloud2SARequiredException)
        )
        if api is not None and (api.requires_2fa or api.requires_2sa):
            need_reauth = True
        if need_reauth:
            self._account._require_reauth()
            raise ServiceValidationError("iCloud account is not available") from err
        if isinstance(
            err,
            (
                PyiCloudFailedLoginException,
                PyiCloudAuthRequiredException,
                PyiCloudAPIResponseException,
                PyiCloudServiceUnavailable,
            ),
        ):
            raise ServiceValidationError(failed_msg) from err
        raise err

    def play_sound(self) -> None:
        """Play sound on the device."""
        if self._account._shutdown:
            raise ServiceValidationError("iCloud account is not available")
        if not self._account._update_lock.acquire(blocking=True, timeout=60):
            raise ServiceValidationError("iCloud account is busy")
        try:
            if self._device_unavailable():
                raise ServiceValidationError("iCloud account is not available")

            self._authenticate_device_action()
            _LOGGER.debug("Playing sound for %s", self.name)
            try:
                self.device.play_sound()
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.warning("Device action failed for %s: %s", self.name, err)
                self._handle_device_action_error(err, "发送声音失败")
        finally:
            self._account._update_lock.release()

    def display_message(self, message: str, sound: bool = False) -> None:
        """Display a message on the device."""
        if self._account._shutdown:
            raise ServiceValidationError("iCloud account is not available")
        if not self._account._update_lock.acquire(blocking=True, timeout=60):
            raise ServiceValidationError("iCloud account is busy")
        try:
            if self._device_unavailable():
                raise ServiceValidationError("iCloud account is not available")

            self._authenticate_device_action()
            _LOGGER.debug("Displaying message for %s", self.name)
            try:
                self.device.display_message("Find My iPhone Alert", message, sound)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.warning("Device action failed for %s: %s", self.name, err)
                self._handle_device_action_error(err, "发送消息失败")
        finally:
            self._account._update_lock.release()

    def lost_device(self, number: str, message: str) -> None:
        """Make the device in lost state."""
        if self._account._shutdown:
            raise ServiceValidationError("iCloud account is not available")
        if not self._account._update_lock.acquire(blocking=True, timeout=60):
            raise ServiceValidationError("iCloud account is busy")
        try:
            if self._device_unavailable():
                raise ServiceValidationError("iCloud account is not available")

            self._authenticate_device_action()
            if self._status.get(DEVICE_LOST_MODE_CAPABLE):
                _LOGGER.debug("Make device lost for %s", self.name)
                try:
                    self.device.lost_device(number, message)
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.warning("Device action failed for %s: %s", self.name, err)
                    self._handle_device_action_error(err, "设置丢失模式失败")
            else:
                raise ServiceValidationError(
                    f"Lost mode is not available for device {self.name}"
                )
        finally:
            self._account._update_lock.release()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._device_id

    @property
    def name(self) -> str:
        """Return the Apple device name."""
        return self._name

    @property
    def object_slug(self) -> str:
        return device_object_slug(self._name, self._device_id)

    @property
    def device(self) -> AppleDevice:
        """Return the Apple device."""
        return self._device

    @property
    def device_class(self) -> str:
        """Return the Apple device class."""
        return self._device_class

    @property
    def device_model(self) -> str:
        """Return the Apple device model."""
        return self._device_model

    @property
    def battery_level(self) -> int | None:
        """Return the Apple device battery level."""
        return self._battery_level

    @property
    def battery_status(self) -> str | None:
        """Return the Apple device battery status."""
        return self._battery_status

    @property
    def battery_available(self) -> bool:
        if self._battery_status is None or str(self._battery_status).lower() == "unknown":
            return False
        return self._battery_level is not None

    @property
    def location(self) -> dict[str, Any] | None:
        """Return the Apple device location."""
        return self._location

    def _reset_steps_if_new_day(self) -> None:
        today = dt_now().date()
        if self._steps_date != today:
            self._steps_date = today
            self._daily_distance = 0.0
            self._daily_steps = 0

    def _accumulate_steps(self, location: dict[str, Any]) -> None:
        self._reset_steps_if_new_day()
        lat = location.get(DEVICE_LOCATION_LATITUDE)
        lon = location.get(DEVICE_LOCATION_LONGITUDE)
        if lat is None or lon is None:
            return
        lat = float(lat)
        lon = float(lon)
        ts = _location_epoch(location)
        if ts is None:
            ts = dt_now().timestamp()
        try:
            accuracy = float(location.get(DEVICE_LOCATION_HORIZONTAL_ACCURACY) or 0)
        except (TypeError, ValueError):
            accuracy = 0.0
        last_lat = self._last_lat
        last_lon = self._last_lon
        last_ts = self._last_ts
        self._last_lat = lat
        self._last_lon = lon
        self._last_ts = ts
        if last_lat is None or last_lon is None or last_lat == 0 or last_lon == 0:
            return
        dist = _haversine_m(last_lat, last_lon, lat, lon)
        min_dist = max(WALK_MIN_DISTANCE, min(accuracy, 50.0))
        if str(location.get("positionType") or "").lower() == "cell":
            min_dist = max(min_dist, 80.0)
        if dist < min_dist:
            return
        if last_ts is None or ts is None or ts <= last_ts:
            return
        dt = ts - last_ts
        if dt < WALK_MIN_INTERVAL:
            return
        speed = dist / dt
        if speed > WALK_SPEED_MAX:
            return
        if speed >= WALK_SPEED_RUN:
            step_len = RUN_STEP_LENGTH
            cadence = RUN_CADENCE
        else:
            step_len = STEP_LENGTH
            cadence = WALK_CADENCE
        if dt >= 600:
            factor = WALK_PATH_FACTOR_SPARSE
        elif dt >= 180:
            factor = WALK_PATH_FACTOR
        else:
            factor = WALK_PATH_FACTOR_DENSE
        raw_steps = (dist * factor) / step_len
        counted = min(raw_steps, cadence * (dt / 60))
        self._daily_steps += int(counted)
        self._daily_distance += counted * step_len

    def restore_step_state(self, state: Any, attrs: dict[str, Any]) -> None:
        try:
            steps_date = date.fromisoformat(str(attrs.get("steps_date")))
        except (TypeError, ValueError):
            steps_date = None
        today = dt_now().date()
        if steps_date != today:
            self._steps_date = today
            self._daily_distance = 0.0
            self._daily_steps = 0
        else:
            self._steps_date = steps_date
            restored = None
            if state not in (None, "", "unknown", "unavailable"):
                try:
                    restored = int(float(state))
                except (TypeError, ValueError):
                    restored = None
            if restored is None:
                try:
                    restored = int(
                        float(attrs.get("daily_distance") or 0) / STEP_LENGTH
                    )
                except (TypeError, ValueError):
                    restored = 0
            self._daily_steps = restored
            try:
                self._daily_distance = float(
                    attrs.get("daily_distance") or self._daily_steps * STEP_LENGTH
                )
            except (TypeError, ValueError):
                self._daily_distance = self._daily_steps * STEP_LENGTH
        try:
            lat = attrs.get("last_latitude")
            lon = attrs.get("last_longitude")
            self._last_lat = float(lat) if lat is not None else self._last_lat
            self._last_lon = float(lon) if lon is not None else self._last_lon
        except (TypeError, ValueError):
            pass
        try:
            last_ts = attrs.get("last_timestamp")
            self._last_ts = float(last_ts) if last_ts is not None else self._last_ts
        except (TypeError, ValueError):
            pass

    @property
    def daily_steps(self) -> int:
        self._reset_steps_if_new_day()
        return self._daily_steps

    @property
    def daily_distance(self) -> float:
        return self._daily_distance

    @property
    def last_latitude(self) -> float | None:
        return self._last_lat

    @property
    def last_longitude(self) -> float | None:
        return self._last_lon

    @property
    def steps_date(self) -> date | None:
        return self._steps_date

    @property
    def phone_status(self) -> str:
        if self._attrs.get(ATTR_DEVICE_STATUS) == "online":
            return "online"
        return "offline"

    @property
    def last_timestamp(self) -> float | None:
        return self._last_ts

    @property
    def location_timestamp(self) -> datetime | None:
        value = _location_epoch(self._location)
        if value is None:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc)

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
    def commute_distance(self) -> float | None:
        return self._commute_distance

    @property
    def commute_time(self) -> int | None:
        return self._commute_time

    @property
    def commute_time_text(self) -> str | None:
        if self._commute_time is None:
            return None
        return _format_commute_time(self._commute_time)

    @property
    def commute_info(self) -> str | None:
        return self._commute_info

    def restore_location_address(self, state: Any) -> None:
        if state in (None, "", "unknown", "unavailable"):
            return
        text = str(state).strip()
        if text:
            self._location_address = text

    def restore_location_attrs(self, attrs: Any) -> None:
        if not isinstance(attrs, dict):
            return
        poi = _amap_text(attrs.get("poi"))
        city = _amap_text(attrs.get("city"))
        district = _amap_text(attrs.get("district"))
        if poi:
            self._location_poi = poi
        if city:
            self._location_city = city
        if district:
            self._location_district = district

    def restore_commute_distance(self, state: Any) -> None:
        if state in (None, "", "unknown", "unavailable"):
            return
        if isinstance(state, (int, float)) and not isinstance(state, bool):
            self._commute_distance = float(state)
            return
        text = str(state).strip().lower().replace(" ", "")
        text = text.replace("公里", "").removesuffix("km")
        try:
            self._commute_distance = float(text)
        except (TypeError, ValueError):
            return

    def restore_commute_time(self, state: Any) -> None:
        if state in (None, "", "unknown", "unavailable"):
            return
        if isinstance(state, (int, float)) and not isinstance(state, bool):
            self._commute_time = int(state)
            return
        text = str(state).strip()
        days = 0
        hours = 0
        minutes = 0
        zh_day = re.search(r"(\d+)\s*天", text)
        zh_hour = re.search(r"(\d+)\s*小[时時]", text)
        zh_min = re.search(r"(\d+)\s*分[钟鐘]", text)
        en_day = re.search(r"(\d+)\s*d(?:ays?)?", text, re.I)
        en_hour = re.search(r"(\d+)\s*h(?:ours?)?", text, re.I)
        en_min = re.search(r"(\d+)\s*min(?:utes?)?", text, re.I)
        if zh_day or zh_hour or zh_min:
            days = int(zh_day.group(1)) if zh_day else 0
            hours = int(zh_hour.group(1)) if zh_hour else 0
            minutes = int(zh_min.group(1)) if zh_min else 0
        elif en_day or en_hour or en_min:
            days = int(en_day.group(1)) if en_day else 0
            hours = int(en_hour.group(1)) if en_hour else 0
            minutes = int(en_min.group(1)) if en_min else 0
        else:
            try:
                minutes = int(float(text))
            except (TypeError, ValueError):
                return
        self._commute_time = days * 1440 + hours * 60 + minutes

    def restore_commute_info(self, state: Any) -> None:
        if state in (None, "", "unknown", "unavailable"):
            return
        text = str(state).strip()
        if text:
            self._commute_info = text

    def _apply_commute(
        self,
        key: str,
        mode: str | None,
        zones: list[tuple[str, str, float, float, float]],
    ) -> None:
        loc = self._location
        if not loc:
            return
        lat = loc.get(DEVICE_LOCATION_LATITUDE)
        lon = loc.get(DEVICE_LOCATION_LONGITUDE)
        if lat is None or lon is None:
            return
        lat = float(lat)
        lon = float(lon)
        olng, olat = _wgs84_to_gcj02(lon, lat)
        grid = _amap_grid(olng, olat)
        inside = None
        inside_dist = None
        best = None
        best_dist = None
        for zone in zones:
            meters = _haversine_m(lat, lon, zone[2], zone[3])
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

        def _refresh_address() -> bool:
            geo = _amap_regeo(key, olng, olat)
            self._account._bump_amap()
            self._amap_grid = grid
            if geo and geo["address"]:
                self._location_address = geo["address"]
                self._location_poi = geo["poi"]
                self._location_city = geo["city"]
                self._location_district = geo["district"]
                return True
            return False

        if inside is not None:
            self._commute_inside = True
            now_ts = dt_now().timestamp()
            if self._home_entered_at is None:
                self._home_entered_at = now_ts
                self._home_address_done = False
            if (
                not self._home_address_done
                and now_ts - self._home_entered_at < 3600
            ):
                _refresh_address()
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
        dlng, dlat = _wgs84_to_gcj02(best[3], best[2])
        dest_grid = _amap_grid(dlng, dlat)
        route_key = (*grid, *dest_grid, mode)
        if route_key == self._amap_route_key:
            return
        _refresh_address()
        route = _amap_route(key, mode, olng, olat, dlng, dlat)
        self._account._bump_amap()
        self._amap_route_key = route_key
        if route is None:
            return
        distance_km, minutes, info = route
        self._commute_distance = distance_km
        self._commute_time = minutes
        self._commute_info = info or best[1]

    def _ensure_timestamp(self) -> None:
        if "timestamp" in self._attrs:
            return
        loc_ts = _location_epoch(self._location)
        if loc_ts is None:
            if self._location is None:
                return
            loc_ts = dt_now().timestamp()
        self._attrs["timestamp"] = int(loc_ts * 1000)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        self._ensure_timestamp()
        return self._attrs
