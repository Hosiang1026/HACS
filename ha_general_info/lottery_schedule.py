from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable

from homeassistant.util import dt as dt_util

from .const import (
    LOTTERY_DRAW_WEEKDAYS,
    LOTTERY_DRAW_WINDOW_END,
    LOTTERY_DRAW_WINDOW_START,
    LOTTERY_TYPES,
)


def _types(module_types: Iterable[str] | None) -> list[str]:
    return [t for t in (module_types or list(LOTTERY_TYPES)) if t in LOTTERY_DRAW_WEEKDAYS]


def is_draw_day(weekday: int, lottery_type: str) -> bool:
    days = LOTTERY_DRAW_WEEKDAYS.get(lottery_type) or ()
    return weekday in days


def any_draw_today(now: datetime, types: Iterable[str] | None) -> bool:
    wd = now.weekday()
    return any(is_draw_day(wd, t) for t in _types(types))


def in_draw_window(now: datetime) -> bool:
    start_h, start_m = LOTTERY_DRAW_WINDOW_START
    end_h, end_m = LOTTERY_DRAW_WINDOW_END
    start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    return start <= now <= end


def result_is_today(item: dict[str, Any] | None, now: datetime) -> bool:
    if not item:
        return False
    raw = str(item.get("date") or "")
    today = now.date().isoformat()
    return today in raw


def waiting_for_results(
    now: datetime,
    types: Iterable[str] | None,
    data: dict[str, Any] | None,
) -> bool:
    if not any_draw_today(now, types) or not in_draw_window(now):
        return False
    data = data or {}
    for t in _types(types):
        if not is_draw_day(now.weekday(), t):
            continue
        if not result_is_today(data.get(t), now):
            return True
    return False


def minutes_until_next_window(now: datetime, types: Iterable[str] | None) -> int:
    enabled = _types(types)
    if not enabled:
        return 720
    start_h, start_m = LOTTERY_DRAW_WINDOW_START
    for offset in range(0, 8):
        day = now + timedelta(days=offset)
        wd = day.weekday()
        if not any(is_draw_day(wd, t) for t in enabled):
            continue
        start = day.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        if start <= now:
            continue
        return max(5, int((start - now).total_seconds() // 60))
    return 720


def calc_lottery_interval_minutes(
    *,
    types: Iterable[str] | None,
    data: dict[str, Any] | None,
    draw_poll_minutes: int,
    now: datetime | None = None,
) -> int:
    now = now or dt_util.now()
    poll = max(1, int(draw_poll_minutes))
    if waiting_for_results(now, types, data):
        return poll
    if any_draw_today(now, types) and in_draw_window(now):
        return minutes_until_next_window(now, types)
    return minutes_until_next_window(now, types)
