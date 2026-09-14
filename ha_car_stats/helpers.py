from __future__ import annotations

import ast
import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AMAP_KEY,
    CONF_AMAP_PARAMDATA,
    CONF_AMAP_SESSIONID,
    CONF_AMAP_TID,
    CONF_EXPIRE_DAYS,
    CONF_FUEL_GRADE,
    CONF_FUEL_PRICE,
    CONF_FUEL_PRICE_ENTITY,
    CONF_INSURANCE_EXPIRY,
    CONF_MAINT_DAYS,
    CONF_MAINT_KM,
    CONF_NAME,
    CONF_NOTIFY,
    CONF_ANNOUNCE,
    CONF_NOTIFY_ENABLE,
    CONF_NOTIFY_INSPECT,
    CONF_NOTIFY_INSURANCE,
    CONF_NOTIFY_LICENSE,
    CONF_NOTIFY_MAINT,
    CONF_NOTIFY_VIOLATION,
    CONF_NOTIFY_YEARLY,
    CONF_ODOMETER,
    CONF_ODOMETER_ENTITY,
    CONF_OWNERS,
    CONF_PLATE,
    CONF_POLL_ACTIVE,
    CONF_PURCHASE_DATE,
    CONF_INSPECT_EXPIRY,
    CONF_MAINT_DATE,
    CONF_MAINT_ODO,
    CONF_BATTERY_REPLACE_DATE,
    CONF_SF,
    CONF_TANK_CAPACITY,
    CONF_VEHICLE_INDEX,
    DEFAULT_EXPIRE_DAYS,
    DEFAULT_MAINT_DAYS,
    DEFAULT_MAINT_KM,
    DEFAULT_NOTIFY_ENABLE,
    DEFAULT_NOTIFY_INSPECT,
    DEFAULT_NOTIFY_INSURANCE,
    DEFAULT_NOTIFY_LICENSE,
    DEFAULT_NOTIFY_MAINT,
    DEFAULT_NOTIFY_VIOLATION,
    DEFAULT_NOTIFY_YEARLY,
    DEFAULT_POLL_ACTIVE,
    DEFAULT_PRICES,
    DEFAULT_TANK,
    PRICE_KEYS,
)

_PI = 3.1415926535897932384626
_A = 6378245.0
_EE = 0.00669342162296594323


def entry_cfg(entry: ConfigEntry) -> dict[str, Any]:
    return {**entry.data, **entry.options}


def cfg_name(entry: ConfigEntry) -> str:
    return entry_cfg(entry).get(CONF_NAME) or entry.data.get("account_name") or "汽车"


def cfg_12123(entry: ConfigEntry) -> bool:
    return bool(entry.data.get(CONF_SF))


def cfg_amap(entry: ConfigEntry) -> bool:
    return bool(
        entry.data.get(CONF_AMAP_SESSIONID)
        and entry.data.get(CONF_AMAP_TID)
        and entry.data.get(CONF_AMAP_KEY)
        and entry.data.get(CONF_AMAP_PARAMDATA)
    )


def cfg_amap_plate(entry: ConfigEntry) -> str:
    return normalize_plate(entry_cfg(entry).get(CONF_PLATE))


def cfg_owners(entry: ConfigEntry) -> list[str]:
    raw = entry_cfg(entry).get(CONF_OWNERS) or []
    if isinstance(raw, str):
        raw = [raw] if raw.strip() else []
    return [str(o).strip() for o in raw if str(o).strip()]


def cfg_poll_active(entry: ConfigEntry) -> int:
    try:
        return max(int(entry_cfg(entry).get(CONF_POLL_ACTIVE, DEFAULT_POLL_ACTIVE) or DEFAULT_POLL_ACTIVE), 1)
    except (TypeError, ValueError):
        return DEFAULT_POLL_ACTIVE


def normalize_plate(plate: Any) -> str:
    return "".join(str(plate or "").replace("·", "").replace(".", "").split())


def plate_tail_num(plate: Any) -> str:
    for ch in reversed(normalize_plate(plate)):
        if ch.isdigit():
            return ch
    return ""


def _out_of_china(lng: float, lat: float) -> bool:
    return lng < 72.004 or lng > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transformlat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * _PI) + 40.0 * math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * _PI) + 320 * math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transformlng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * _PI) + 40.0 * math.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * _PI) + 300.0 * math.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84togcj02(lng: float, lat: float) -> list[float]:
    if _out_of_china(lng, lat):
        return [lng, lat]
    dlat = _transformlat(lng - 105.0, lat - 35.0)
    dlng = _transformlng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return [lng + dlng, lat + dlat]


def gcj02towgs84(lng: float, lat: float) -> list[float]:
    if _out_of_china(lng, lat):
        return [lng, lat]
    dlat = _transformlat(lng - 105.0, lat - 35.0)
    dlng = _transformlng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return [lng * 2 - (lng + dlng), lat * 2 - (lat + dlat)]


def gcj02_to_bd09(lng: float, lat: float) -> list[float]:
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * _PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * _PI)
    return [z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006]


def cfg_vehicle_index(entry: ConfigEntry) -> int:
    try:
        return int(entry_cfg(entry).get(CONF_VEHICLE_INDEX, 1))
    except (TypeError, ValueError):
        return 1


def cfg_odometer_entity(entry: ConfigEntry) -> str | None:
    return entry_cfg(entry).get(CONF_ODOMETER_ENTITY) or None


def cfg_odometer(entry: ConfigEntry) -> float | None:
    raw = entry_cfg(entry).get(CONF_ODOMETER)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def cfg_fuel_price_entity(entry: ConfigEntry) -> str | None:
    return entry_cfg(entry).get(CONF_FUEL_PRICE_ENTITY) or None


def cfg_fuel_price(entry: ConfigEntry) -> float | None:
    raw = entry_cfg(entry).get(CONF_FUEL_PRICE)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def cfg_fuel_grade(entry: ConfigEntry) -> int:
    try:
        return int(entry_cfg(entry).get(CONF_FUEL_GRADE, 92))
    except (TypeError, ValueError):
        return 92


def cfg_tank(entry: ConfigEntry) -> float:
    try:
        return float(entry_cfg(entry).get(CONF_TANK_CAPACITY, DEFAULT_TANK))
    except (TypeError, ValueError):
        return float(DEFAULT_TANK)


def cfg_maint_km(entry: ConfigEntry) -> float:
    try:
        return float(entry_cfg(entry).get(CONF_MAINT_KM, DEFAULT_MAINT_KM))
    except (TypeError, ValueError):
        return float(DEFAULT_MAINT_KM)


def cfg_purchase_date(entry: ConfigEntry) -> date | None:
    return parse_any_date(entry_cfg(entry).get(CONF_PURCHASE_DATE))


def normalize_config_date(value: Any) -> str | None:
    parsed = parse_any_date(value)
    return parsed.isoformat() if parsed else None


normalize_purchase_date = normalize_config_date


def usage_duration(purchase: date | None, today: date | None = None) -> float | None:
    if not purchase:
        return None
    current = today or dt_util.now().date()
    days = (current - purchase).days
    if days < 0:
        return 0.0
    return round(days / 365.25, 1)


def cfg_maint_days(entry: ConfigEntry) -> int:
    try:
        return int(entry_cfg(entry).get(CONF_MAINT_DAYS, DEFAULT_MAINT_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_MAINT_DAYS


def cfg_insurance_expiry(entry: ConfigEntry) -> date | None:
    return parse_any_date(entry_cfg(entry).get(CONF_INSURANCE_EXPIRY))


def cfg_inspect_expiry(entry: ConfigEntry) -> date | None:
    return parse_any_date(entry_cfg(entry).get(CONF_INSPECT_EXPIRY))


def cfg_maint_date(entry: ConfigEntry) -> date | None:
    return parse_any_date(entry_cfg(entry).get(CONF_MAINT_DATE))


def cfg_battery_replace_date(entry: ConfigEntry) -> date | None:
    return parse_any_date(entry_cfg(entry).get(CONF_BATTERY_REPLACE_DATE))


def cfg_maint_odo(entry: ConfigEntry) -> float:
    try:
        return float(entry_cfg(entry).get(CONF_MAINT_ODO, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def compute_maint_remaining(
    maint_date: date | None,
    maint_odo: float,
    interval_km: float,
    interval_days: int,
    current_odo: float,
) -> tuple[float | None, int | None]:
    if not maint_date:
        return None, None
    km_until = round(maint_odo + interval_km - current_odo, 1)
    due_date = maint_date + timedelta(days=interval_days)
    days_by_cycle = days_until(due_date)
    if days_by_cycle is None:
        days_by_cycle = interval_days
    return km_until, days_by_cycle


def _parse_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        price = float(value)
        return price if math.isfinite(price) and 0 < price <= 50 else None
    text = str(value).strip()
    if not text or text.lower() in ("unknown", "unavailable", "none", "null", "nan", "未知", "暂无", "--"):
        return None
    try:
        price = float(text)
    except (TypeError, ValueError):
        match = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
        if not match:
            return None
        try:
            price = float(match.group(1))
        except (TypeError, ValueError):
            return None
    return price if math.isfinite(price) and 0 < price <= 50 else None


def resolve_fuel_price(hass: HomeAssistant, entry: ConfigEntry) -> float:
    grade = cfg_fuel_grade(entry)
    fallback = float(DEFAULT_PRICES.get(grade, 7.50))
    default = _parse_price(cfg_fuel_price(entry)) or fallback
    entity_id = cfg_fuel_price_entity(entry)
    if not entity_id:
        return default
    state = hass.states.get(entity_id)
    if not state:
        return default
    for key in PRICE_KEYS.get(grade, ()):
        if key not in state.attributes:
            continue
        price = _parse_price(state.attributes.get(key))
        if price is not None:
            return price
    return _parse_price(state.state) or default


def resolve_odometer(hass: HomeAssistant, entry: ConfigEntry, fallback: float) -> float:
    entity_id = cfg_odometer_entity(entry)
    if entity_id:
        state = hass.states.get(entity_id)
        if state and state.state not in ("unknown", "unavailable", ""):
            try:
                return float(state.state)
            except (TypeError, ValueError):
                pass
    if fallback and float(fallback) > 0:
        return float(fallback)
    configured = cfg_odometer(entry)
    if configured is not None:
        return float(configured)
    return float(fallback or 0)


def parse_any_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return dt_util.as_local(value).date()
    if isinstance(value, date):
        return value
    if isinstance(value, dict):
        try:
            return date(int(value["year"]), int(value["month"]), int(value["day"]))
        except (KeyError, TypeError, ValueError):
            return None
    text = str(value).strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = ast.literal_eval(text)
            if isinstance(obj, dict):
                return date(int(obj["year"]), int(obj["month"]), int(obj["day"]))
        except (ValueError, SyntaxError, KeyError, TypeError):
            pass
    if not text or text in ("未知", "unknown", "unavailable"):
        return None
    parsed = dt_util.parse_datetime(text)
    if parsed:
        return dt_util.as_local(parsed).date()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text[:16], fmt).date()
        except ValueError:
            continue
    if len(text) >= 8 and text[:8].isdigit():
        try:
            return datetime.strptime(text[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def days_until(value: Any) -> int | None:
    d = parse_any_date(value)
    if not d:
        return None
    return (d - dt_util.now().date()).days


def same_month(ts: str, now: datetime) -> bool:
    try:
        t = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return False
    return t.year == now.year and t.month == now.month


def fmt_duration(seconds: int) -> str:
    seconds = max(int(seconds or 0), 0)
    minutes_total = seconds // 60
    if minutes_total < 24 * 60:
        hours = minutes_total // 60
        minutes = minutes_total % 60
        return f"{hours:02d}:{minutes:02d}"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    if days >= 365:
        years = days // 365
        days = days % 365
        return f"{years:04d}:{days:02d}:{hours:02d}:{minutes:02d}"
    if days >= 100:
        return f"{days:03d}:{hours:02d}:{minutes:02d}"
    return f"{days:02d}:{hours:02d}:{minutes:02d}"


def cfg_notify_enable(entry: ConfigEntry) -> bool:
    return bool(entry_cfg(entry).get(CONF_NOTIFY_ENABLE, DEFAULT_NOTIFY_ENABLE))


def _cfg_notify_flag(entry: ConfigEntry, key: str, default: bool) -> bool:
    cfg = entry_cfg(entry)
    if key in cfg:
        return bool(cfg.get(key))
    if cfg.get(CONF_NOTIFY_ENABLE) is True:
        return True
    return default


def cfg_notify_violation(entry: ConfigEntry) -> bool:
    return cfg_12123(entry) and _cfg_notify_flag(entry, CONF_NOTIFY_VIOLATION, DEFAULT_NOTIFY_VIOLATION)


def cfg_notify_yearly(entry: ConfigEntry) -> bool:
    return _cfg_notify_flag(entry, CONF_NOTIFY_YEARLY, DEFAULT_NOTIFY_YEARLY)


def cfg_notify_maint(entry: ConfigEntry) -> bool:
    return _cfg_notify_flag(entry, CONF_NOTIFY_MAINT, DEFAULT_NOTIFY_MAINT)


def cfg_notify_insurance(entry: ConfigEntry) -> bool:
    return _cfg_notify_flag(entry, CONF_NOTIFY_INSURANCE, DEFAULT_NOTIFY_INSURANCE)


def cfg_notify_inspect(entry: ConfigEntry) -> bool:
    return _cfg_notify_flag(entry, CONF_NOTIFY_INSPECT, DEFAULT_NOTIFY_INSPECT)


def cfg_notify_license(entry: ConfigEntry) -> bool:
    return cfg_12123(entry) and _cfg_notify_flag(entry, CONF_NOTIFY_LICENSE, DEFAULT_NOTIFY_LICENSE)


def cfg_notify_actions(entry: ConfigEntry) -> Any:
    return entry_cfg(entry).get(CONF_NOTIFY)


def cfg_announce(entry: ConfigEntry) -> list[str]:
    raw = entry_cfg(entry).get(CONF_ANNOUNCE)
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return [item for item in raw if isinstance(item, str) and item]


def cfg_expire_days(entry: ConfigEntry) -> int:
    try:
        return int(entry_cfg(entry).get(CONF_EXPIRE_DAYS, DEFAULT_EXPIRE_DAYS))
    except (TypeError, ValueError):
        return DEFAULT_EXPIRE_DAYS


def in_year(ts: str, year: int) -> bool:
    try:
        return datetime.fromisoformat(ts).year == year
    except (TypeError, ValueError):
        return False


def same_year(ts: str, now: datetime) -> bool:
    try:
        t = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return False
    return t.year == now.year


def consumption_rating(value: float) -> str:
    if value <= 0:
        return "未知"
    if value <= 9.0:
        return "优秀"
    if value <= 11.0:
        return "良好"
    if value <= 13.0:
        return "正常"
    if value <= 15.0:
        return "偏高"
    return "费油"
