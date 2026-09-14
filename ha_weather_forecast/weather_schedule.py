from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_WEATHER_IDLE_INTERVAL,
    DEFAULT_WEATHER_INTERVAL,
    WEATHER_PEAK_WINDOWS,
)


def in_peak_window(now: datetime) -> bool:
    minutes = now.hour * 60 + now.minute
    for (sh, sm), (eh, em) in WEATHER_PEAK_WINDOWS:
        if sh * 60 + sm <= minutes <= eh * 60 + em:
            return True
    return False


def minutes_until_next_peak(now: datetime) -> int:
    cur = now.hour * 60 + now.minute
    candidates: list[int] = []
    for day in (0, 1):
        for (sh, sm), _end in WEATHER_PEAK_WINDOWS:
            start = day * 24 * 60 + sh * 60 + sm
            delta = start - cur
            if delta > 0:
                candidates.append(delta)
    return max(5, min(candidates)) if candidates else 60


def calc_weather_interval_minutes(
    *,
    peak_minutes: int | None = None,
    idle_minutes: int | None = None,
    now: datetime | None = None,
) -> int:
    now = now or dt_util.now()
    peak = max(1, int(peak_minutes or DEFAULT_WEATHER_INTERVAL))
    idle = max(peak, int(idle_minutes or DEFAULT_WEATHER_IDLE_INTERVAL))
    if in_peak_window(now):
        return peak
    until = minutes_until_next_peak(now)
    return min(idle, until)
