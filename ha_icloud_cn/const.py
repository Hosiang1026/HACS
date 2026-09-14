"""iCloud component constants."""
import re

from homeassistant.const import Platform

DOMAIN = "ha_icloud_cn"
INTEGRATION_MANUFACTURER = "狂欢马克思"
INTEGRATION_HUB_SUFFIX = "_hub"

CONF_WITH_FAMILY = "with_family"
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
CONF_AMAP_KEY = "amap_key"
CONF_ACTIVITY_ENTITY = "activity_entity"

COMMUTE_MODE_DRIVING = "driving"
COMMUTE_MODE_BICYCLING = "bicycling"
ACTIVITY_BIKE = ("在家", "公司")
ACTIVITY_DRIVE = ("外出", "外地")
COMMUTE_BIKE_MAX_KM = 10

DEFAULT_WITH_FAMILY = False
DEFAULT_COMMUTE_ENABLED = False
DEFAULT_COMMUTE_ZONES: list[str] = []
DEFAULT_ACTIVITY_ENTITY: list[str] = []


def activity_entities(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


DEFAULT_MAX_INTERVAL = 120
DEFAULT_PEAK_ENABLED = True
DEFAULT_PEAK_WINDOWS = "07:00-09:00,17:00-20:00"
DEFAULT_PEAK_INTERVAL = 10
DEFAULT_OFFPEAK_ENABLED = True
DEFAULT_OFFPEAK_WINDOWS = "20:00-00:00"
DEFAULT_OFFPEAK_INTERVAL = 60
DEFAULT_PERIOD_WEEKDAYS = True
LOCAL_DISTANCE_KM = 30
FAR_DISTANCE_KM = 50
HOME_EXIT_BUFFER_M = 200
FAR_INTERVAL_50_100 = 120
FAR_INTERVAL_100_200 = 180
FAR_INTERVAL_200_300 = 240
FAR_INTERVAL_300_800 = 300
FAR_INTERVAL_800_2000 = 360
FAR_INTERVAL_2000_PLUS = 720
LOW_BATTERY_LEVEL = 20

_WINDOW_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")
HOUR_SLOTS = [f"{hour:02d}:00-{(hour + 1) % 24:02d}:00" for hour in range(24)]
TIME_NONE = "none"
TIME_CHOICES = [
    f"{hour:02d}:{minute:02d}" for hour in range(24) for minute in (0, 30)
]
PEAK_RANGE_COUNT = 3
OFFPEAK_RANGE_COUNT = 2


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


def windows_to_slots(windows: list[tuple[int, int]]) -> list[str]:
    slots: list[str] = []
    seen: set[str] = set()
    for start, end in windows:
        if start == end:
            continue
        if start < end:
            minute = start - start % 60
            while minute < end:
                slot = f"{minute // 60:02d}:00-{(minute // 60 + 1) % 24:02d}:00"
                if slot not in seen:
                    seen.add(slot)
                    slots.append(slot)
                minute += 60
            continue
        minute = start - start % 60
        for _ in range(24):
            hour = minute // 60
            slot = f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"
            if slot not in seen:
                seen.add(slot)
                slots.append(slot)
            minute = (minute + 60) % (24 * 60)
            end_aligned = end - end % 60
            if minute == end_aligned:
                break
    return slots


def windows_text_to_slots(text: str) -> list[str]:
    windows = parse_windows(text)
    if not windows:
        return []
    return windows_to_slots(windows)


def slots_to_windows_text(slots: list[str]) -> str:
    hours: list[int] = []
    for slot in slots:
        try:
            hour = int(str(slot).split(":", 1)[0])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= hour <= 23:
            hours.append(hour)
    if not hours:
        return ""
    hours = sorted(set(hours))
    if hours == list(range(24)):
        return "00:00-12:00,12:00-00:00"
    ranges: list[tuple[int, int]] = []
    start = prev = hours[0]
    for hour in hours[1:]:
        if hour == prev + 1:
            prev = hour
        else:
            ranges.append((start, prev + 1))
            start = prev = hour
    ranges.append((start, prev + 1))
    if len(ranges) >= 2 and ranges[0][0] == 0 and ranges[-1][1] == 24:
        first = ranges.pop(0)
        last = ranges.pop()
        ranges.append((last[0], first[1]))
    return ",".join(f"{begin:02d}:00-{end % 24:02d}:00" for begin, end in ranges)


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
        return slots_to_windows_text(raw)
    return str(raw or "")

# to store the cookie
STORAGE_KEY = DOMAIN
STORAGE_VERSION = 2

PLATFORMS = [Platform.BUTTON, Platform.DEVICE_TRACKER, Platform.SENSOR, Platform.TEXT]

# pyicloud.AppleDevice status
DEVICE_BATTERY_LEVEL = "batteryLevel"
DEVICE_BATTERY_STATUS = "batteryStatus"
DEVICE_CLASS = "deviceClass"
DEVICE_DISPLAY_NAME = "deviceDisplayName"
DEVICE_ID = "id"
DEVICE_LOCATION = "location"
DEVICE_LOCATION_HORIZONTAL_ACCURACY = "horizontalAccuracy"
DEVICE_LOCATION_LATITUDE = "latitude"
DEVICE_LOCATION_LONGITUDE = "longitude"
DEVICE_LOCATION_TIMESTAMP = "timeStamp"
STEP_LENGTH = 0.65
RUN_STEP_LENGTH = 0.85
WALK_PATH_FACTOR = 1.25
WALK_PATH_FACTOR_SPARSE = 1.4
WALK_PATH_FACTOR_DENSE = 1.12
WALK_SPEED_MAX = 4.5
WALK_SPEED_RUN = 2.2
WALK_MIN_DISTANCE = 15
WALK_MIN_INTERVAL = 20
WALK_CADENCE = 125
RUN_CADENCE = 170
DEVICE_LOST_MODE_CAPABLE = "lostModeCapable"
DEVICE_LOW_POWER_MODE = "lowPowerMode"
DEVICE_NAME = "name"
DEVICE_PERSON_ID = "prsId"
DEVICE_RAW_DEVICE_MODEL = "rawDeviceModel"
DEVICE_STATUS = "deviceStatus"

DEVICE_STATUS_SET = [
    "features",
    "maxMsgChar",
    "darkWake",
    "fmlyShare",
    DEVICE_STATUS,
    "remoteLock",
    "activationLocked",
    DEVICE_CLASS,
    DEVICE_ID,
    "deviceModel",
    DEVICE_RAW_DEVICE_MODEL,
    "passcodeLength",
    "canWipeAfterLock",
    "trackingInfo",
    DEVICE_LOCATION,
    "msg",
    DEVICE_BATTERY_LEVEL,
    "remoteWipe",
    "thisDevice",
    "snd",
    DEVICE_PERSON_ID,
    "wipeInProgress",
    DEVICE_LOW_POWER_MODE,
    "lostModeEnabled",
    "isLocating",
    DEVICE_LOST_MODE_CAPABLE,
    "mesg",
    DEVICE_NAME,
    DEVICE_BATTERY_STATUS,
    "lockedTimestamp",
    "lostTimestamp",
    "locationCapable",
    DEVICE_DISPLAY_NAME,
    "lostDevice",
    "deviceColor",
    "wipedTimestamp",
    "modelDisplayName",
    "locationEnabled",
    "isMac",
    "locFoundEnabled",
]

DEVICE_STATUS_CODES = {
    "200": "online",
    "201": "offline",
    "203": "pending",
    "204": "unregistered",
}
