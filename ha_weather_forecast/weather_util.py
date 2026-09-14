from __future__ import annotations

import re
from typing import Any

_WIND_CN: dict[str, float] = {
    "北": 0,
    "东北": 45,
    "东": 90,
    "东南": 135,
    "南": 180,
    "西南": 225,
    "西": 270,
    "西北": 315,
    "北风": 0,
    "东北风": 45,
    "东风": 90,
    "东南风": 135,
    "南风": 180,
    "西南风": 225,
    "西风": 270,
    "西北风": 315,
    "N": 0,
    "NE": 45,
    "E": 90,
    "SE": 135,
    "S": 180,
    "SW": 225,
    "W": 270,
    "NW": 315,
    "NNE": 22.5,
    "ENE": 67.5,
    "ESE": 112.5,
    "SSE": 157.5,
    "SSW": 202.5,
    "WSW": 247.5,
    "WNW": 292.5,
    "NNW": 337.5,
}

_BEAUFORT_KMH = (0, 5, 11, 19, 28, 38, 49, 61, 74, 88, 102, 117, 133)


def to_float(val: Any) -> float | None:
    try:
        if val in (None, ""):
            return None
        if isinstance(val, str):
            m = re.search(r"-?\d+(?:\.\d+)?", val.replace(",", ""))
            if not m:
                return None
            return float(m.group(0))
        return float(val)
    except (TypeError, ValueError):
        return None


def wind_bearing(val: Any) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val) % 360
    s = str(val).strip()
    if re.search(r"[\u4e00-\u9fff]", s) or s.upper() in _WIND_CN:
        for key in sorted(_WIND_CN, key=len, reverse=True):
            if key in s or s.upper() == key:
                return _WIND_CN[key]
        return None
    num = to_float(s)
    if num is None:
        return None
    return num % 360


def wind_speed_kmh(val: Any, *, assume_ms: bool = False) -> float | None:
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        speed = float(val)
        return round(speed * 3.6, 1) if assume_ms else round(speed, 1)
    s = str(val).strip()
    num = to_float(s)
    if num is None:
        return None
    if "级" in s:
        idx = max(0, min(int(num), len(_BEAUFORT_KMH) - 1))
        return float(_BEAUFORT_KMH[idx])
    lower = s.lower()
    if "m/s" in lower or "mps" in lower:
        return round(num * 3.6, 1)
    if assume_ms and "km" not in lower:
        return round(num * 3.6, 1)
    return round(num, 1)


def visibility_km(val: Any) -> float | None:
    num = to_float(val)
    if num is None:
        return None
    s = str(val).lower() if val is not None else ""
    if "m" in s and "km" not in s:
        return round(num / 1000.0, 2)
    return round(num, 2)


def day_precip(day: dict[str, Any]) -> float | None:
    for key in ("precip", "precipitation", "precipitation_amount"):
        val = to_float(day.get(key))
        if val is not None:
            return val
    return None


def day_precip_prob(day: dict[str, Any]) -> float | None:
    for key in ("pop", "precip_prob", "precipitation_probability"):
        val = to_float(day.get(key))
        if val is not None:
            return val
    return None


def parse_forecast_datetime(fi: Any, now: Any) -> Any:
    from datetime import datetime

    from homeassistant.util import dt as dt_util

    dfi = str(fi or "")
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", dfi):
            when = dt_util.as_local(datetime.fromisoformat(dfi[:10]))
            return when.replace(hour=0, minute=0, second=0, microsecond=0)
        parsed = datetime.strptime(dfi, "%m/%d")
        when = now.replace(
            month=parsed.month,
            day=parsed.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        delta = (when.date() - now.date()).days
        if delta < -180:
            when = when.replace(year=when.year + 1)
        elif delta > 180:
            when = when.replace(year=when.year - 1)
        return when
    except (TypeError, ValueError):
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
