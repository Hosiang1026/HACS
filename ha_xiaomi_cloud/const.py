"""Const file for ha_xiaomi_cloud."""
import re

from homeassistant.const import Platform

DOMAIN = "ha_xiaomi_cloud"
INTEGRATION_MANUFACTURER = "狂欢马克思"
INTEGRATION_HUB_SUFFIX = "_hub"

# 小米 API 中 google = GCJ-02，与高德地图一致
COORDINATE_GCJ02 = "google"

CONF_PASS_TOKEN = "pass_token"
CONF_USER_ID = "user_id"
CONF_DEVICE_ID = "device_id"
CONF_VERIFY_CODE = "verify_code"

FLAG_PHONE = 4
FLAG_EMAIL = 8

CONF_AMAP_KEY = "amap_key"
CONF_AMAP_ENABLED = "amap_enabled"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_MAX_INTERVAL = "max_interval"
CONF_PEAK_ENABLED = "peak_enabled"
CONF_PEAK_WINDOWS = "peak_windows"
CONF_PEAK_INTERVAL = "peak_interval"
CONF_OFFPEAK_ENABLED = "offpeak_enabled"
CONF_OFFPEAK_WINDOWS = "offpeak_windows"
CONF_OFFPEAK_INTERVAL = "offpeak_interval"
CONF_PERIOD_WEEKDAYS = "period_weekdays"
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
LOW_BATTERY_THRESHOLD = 10
LOW_BATTERY_INTERVAL = 60
# 高德个人开发者免费额度约 5000 次/日，预留余量
AMAP_DAILY_LIMIT = 4500

DEFAULT_AMAP_ENABLED = False
DEFAULT_UPDATE_INTERVAL = 10
DEFAULT_MAX_INTERVAL = 10
DEFAULT_PEAK_ENABLED = True
DEFAULT_PEAK_WINDOWS = "07:00-09:00,17:00-20:00"
DEFAULT_PEAK_INTERVAL = 10
DEFAULT_OFFPEAK_ENABLED = True
DEFAULT_OFFPEAK_WINDOWS = "20:00-00:00"
DEFAULT_OFFPEAK_INTERVAL = 60
DEFAULT_PERIOD_WEEKDAYS = True
DEFAULT_COMMUTE_ENABLED = False
DEFAULT_COMMUTE_ZONES: list[str] = []
DEFAULT_COMPANY_ZONES: list[str] = []
DEFAULT_ACTIVITY_ENTITY: list[str] = []

OPTION_KEYS = frozenset(
    {
        CONF_UPDATE_INTERVAL,
        CONF_MAX_INTERVAL,
        CONF_PEAK_ENABLED,
        CONF_PEAK_WINDOWS,
        CONF_PEAK_INTERVAL,
        CONF_OFFPEAK_ENABLED,
        CONF_OFFPEAK_WINDOWS,
        CONF_OFFPEAK_INTERVAL,
        CONF_PERIOD_WEEKDAYS,
        CONF_COMMUTE_ENABLED,
        CONF_COMMUTE_ZONES,
        CONF_COMPANY_ZONES,
        CONF_ACTIVITY_ENTITY,
        CONF_AMAP_ENABLED,
        CONF_AMAP_KEY,
    }
)


def default_options() -> dict:
    return {
        CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
        CONF_MAX_INTERVAL: DEFAULT_MAX_INTERVAL,
        CONF_PEAK_ENABLED: DEFAULT_PEAK_ENABLED,
        CONF_PEAK_WINDOWS: DEFAULT_PEAK_WINDOWS,
        CONF_PEAK_INTERVAL: DEFAULT_PEAK_INTERVAL,
        CONF_OFFPEAK_ENABLED: DEFAULT_OFFPEAK_ENABLED,
        CONF_OFFPEAK_WINDOWS: DEFAULT_OFFPEAK_WINDOWS,
        CONF_OFFPEAK_INTERVAL: DEFAULT_OFFPEAK_INTERVAL,
        CONF_PERIOD_WEEKDAYS: DEFAULT_PERIOD_WEEKDAYS,
        CONF_COMMUTE_ENABLED: DEFAULT_COMMUTE_ENABLED,
        CONF_COMMUTE_ZONES: list(DEFAULT_COMMUTE_ZONES),
        CONF_COMPANY_ZONES: list(DEFAULT_COMPANY_ZONES),
        CONF_ACTIVITY_ENTITY: list(DEFAULT_ACTIVITY_ENTITY),
        CONF_AMAP_ENABLED: DEFAULT_AMAP_ENABLED,
        CONF_AMAP_KEY: "",
    }


PLATFORMS = [Platform.BUTTON, Platform.DEVICE_TRACKER, Platform.SENSOR, Platform.TEXT]

_WINDOW_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
TIME_NONE = "none"
TIME_CHOICES = [
    f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)
]
PEAK_RANGE_COUNT = 3
OFFPEAK_RANGE_COUNT = 2


def activity_entities(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


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
