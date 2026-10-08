from __future__ import annotations

import re

from homeassistant.const import Platform

DOMAIN = "honor_cloud"
PARALLEL_UPDATES = 1

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BASE_URL = "service_base_url"
CONF_SESSION_KEY = "session_key"
CONF_API_KEY = "api_key"
CONF_AMAP_API_KEY = "amap_api_key"
CONF_AMAP_DAILY_LIMIT = "amap_daily_limit"
CONF_ENABLE_AMAP = "enable_amap"
CONF_COMMUTE_ENABLED = "commute_enabled"
CONF_COMMUTE_ZONES = "commute_zones"
CONF_COMPANY_ZONES = "company_zones"
CONF_ACTIVITY_ENTITY = "activity_entity"

COMMUTE_MODE_DRIVING = "driving"
COMMUTE_MODE_BICYCLING = "bicycling"
ACTIVITY_BIKE = ("在家", "公司")
ACTIVITY_DRIVE = ("外出", "外地")
COMMUTE_BIKE_MAX_KM = 10
HOME_EXIT_BUFFER_M = 500
HOME_UPDATE_INTERVAL_MIN = 10
HOME_UPDATE_INTERVAL_MAX = 120
HOME_UPDATE_INTERVAL = HOME_UPDATE_INTERVAL_MAX
LOW_BATTERY_THRESHOLD = 10
LOW_BATTERY_PERCENT = LOW_BATTERY_THRESHOLD

CONF_INTERVAL = "interval"
CONF_MAX_INTERVAL = "max_interval"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_PEAK_ENABLED = "peak_enabled"
CONF_PEAK_WINDOWS = "peak_windows"
CONF_PEAK_INTERVAL = "peak_interval"
CONF_OFFPEAK_ENABLED = "offpeak_enabled"
CONF_OFFPEAK_WINDOWS = "offpeak_windows"
CONF_OFFPEAK_INTERVAL = "offpeak_interval"
CONF_PERIOD_WEEKDAYS = "period_weekdays"
CONF_DEVICE_FILTER = "device_filter"

DEFAULT_MAX_INTERVAL = 10
DEFAULT_INTERVAL = DEFAULT_MAX_INTERVAL * 60
DEFAULT_UPDATE_INTERVAL = DEFAULT_MAX_INTERVAL
DEFAULT_PEAK_ENABLED = True
DEFAULT_PEAK_WINDOWS = "07:00-09:00,17:00-20:00"
DEFAULT_PEAK_INTERVAL = 10
DEFAULT_OFFPEAK_ENABLED = True
DEFAULT_OFFPEAK_WINDOWS = "20:00-00:00"
DEFAULT_OFFPEAK_INTERVAL = 60
DEFAULT_PERIOD_WEEKDAYS = True
DEFAULT_AMAP_DAILY_LIMIT = 4500
DEFAULT_ENABLE_AMAP = False
DEFAULT_COMMUTE_ENABLED = False
DEFAULT_COMMUTE_ZONES: list[str] = []
DEFAULT_COMPANY_ZONES: list[str] = []
DEFAULT_ACTIVITY_ENTITY: list[str] = []

OPTION_KEYS = frozenset(
    {
        CONF_USERNAME,
        CONF_PASSWORD,
        CONF_INTERVAL,
        CONF_MAX_INTERVAL,
        CONF_UPDATE_INTERVAL,
        CONF_PEAK_ENABLED,
        CONF_PEAK_WINDOWS,
        CONF_PEAK_INTERVAL,
        CONF_OFFPEAK_ENABLED,
        CONF_OFFPEAK_WINDOWS,
        CONF_OFFPEAK_INTERVAL,
        CONF_PERIOD_WEEKDAYS,
        CONF_API_KEY,
        CONF_AMAP_API_KEY,
        CONF_AMAP_DAILY_LIMIT,
        CONF_ENABLE_AMAP,
        CONF_COMMUTE_ENABLED,
        CONF_COMMUTE_ZONES,
        CONF_COMPANY_ZONES,
        CONF_ACTIVITY_ENTITY,
    }
)

_WINDOW_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
TIME_NONE = "none"
TIME_CHOICES = [
    f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)
]
PEAK_RANGE_COUNT = 3
OFFPEAK_RANGE_COUNT = 2


def default_locate_options() -> dict:
    return {
        CONF_MAX_INTERVAL: DEFAULT_MAX_INTERVAL,
        CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
        CONF_INTERVAL: DEFAULT_INTERVAL,
        CONF_PEAK_ENABLED: DEFAULT_PEAK_ENABLED,
        CONF_PEAK_WINDOWS: DEFAULT_PEAK_WINDOWS,
        CONF_PEAK_INTERVAL: DEFAULT_PEAK_INTERVAL,
        CONF_OFFPEAK_ENABLED: DEFAULT_OFFPEAK_ENABLED,
        CONF_OFFPEAK_WINDOWS: DEFAULT_OFFPEAK_WINDOWS,
        CONF_OFFPEAK_INTERVAL: DEFAULT_OFFPEAK_INTERVAL,
        CONF_PERIOD_WEEKDAYS: DEFAULT_PERIOD_WEEKDAYS,
    }


def parse_windows(text: str) -> list[tuple[int, int]] | None:
    text = (text or "").strip()
    if not text:
        return []
    result: list[tuple[int, int]] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        match = _WINDOW_RE.match(part)
        if not match:
            return None
        hour1, minute1, hour2, minute2 = (int(v) for v in match.groups())
        if hour1 > 23 or hour2 > 23 or minute1 > 59 or minute2 > 59:
            return None
        result.append((hour1 * 60 + minute1, hour2 * 60 + minute2))
    return result


def in_windows(now_min: int, windows: list[tuple[int, int]]) -> bool:
    for start, end in windows:
        if start == end:
            continue
        if start < end:
            if start <= now_min < end:
                return True
        elif now_min >= start or now_min < end:
            return True
    return False


def _fmt_hm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def windows_text_to_pairs(text: str, count: int) -> list[tuple[str, str]]:
    windows = parse_windows(text or "") or []
    pairs = [(_fmt_hm(start), _fmt_hm(end)) for start, end in windows[:count]]
    while len(pairs) < count:
        pairs.append((TIME_NONE, TIME_NONE))
    return pairs


def pairs_to_windows_text(pairs: list[tuple[str, str]]) -> str | None:
    parts: list[str] = []
    for start, end in pairs:
        start = "" if start in (None, "", TIME_NONE) else str(start)
        end = "" if end in (None, "", TIME_NONE) else str(end)
        if not start and not end:
            continue
        if not start or not end or start == end:
            return None
        parts.append(f"{start}-{end}")
    text = ",".join(parts)
    if parse_windows(text) is None:
        return None
    return text


def opt_windows_text(raw, default_text: str = "") -> str:
    if raw is None:
        raw = default_text
    if isinstance(raw, list):
        return ",".join(str(item) for item in raw if item)
    return str(raw or "")


def resolve_max_interval_minutes(options: dict, data: dict | None = None) -> int:
    data = data or {}
    raw = options.get(CONF_MAX_INTERVAL, data.get(CONF_MAX_INTERVAL))
    if raw is None:
        raw = options.get(CONF_UPDATE_INTERVAL, data.get(CONF_UPDATE_INTERVAL))
    if raw is None:
        legacy = options.get(CONF_INTERVAL, data.get(CONF_INTERVAL, DEFAULT_INTERVAL))
        try:
            value = int(legacy)
        except (TypeError, ValueError):
            return DEFAULT_MAX_INTERVAL
        if value >= 60:
            return max(1, value // 60)
        return max(1, value)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_INTERVAL


PLATFORMS = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.TEXT,
]

API_STATUS = "/status"
API_LOGIN = "/login"
API_SYNC = "/sync"

ATTR_ACCURACY = "accuracy"
ATTR_BATTERY = "battery"
ATTR_ADDRESS = "address"
ATTR_GCJ02_LAT = "gcj02_lat"
ATTR_GCJ02_LNG = "gcj02_lng"
ATTR_RAW = "raw"
ATTR_DEVICE_NAME = "device_name"
ATTR_LAST_UPDATE = "last_update"

DEVICE_CLASS_BATTERY = "battery"
DEVICE_CLASS_TIMESTAMP = "timestamp"

ICON_DEVICE_TRACKER = "mdi:cellphone"
ICON_BATTERY = "mdi:battery"
ICON_SYNC = "mdi:sync"
ICON_LOGIN = "mdi:login"
ICON_CLOCK = "mdi:clock"
ICON_COUNTER = "mdi:counter"
