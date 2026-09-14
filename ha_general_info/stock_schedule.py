from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_STOCK_ACTIVE_INTERVAL,
    DEFAULT_STOCK_PEAK_INTERVAL,
    STOCK_ACTIVE_WINDOWS,
    STOCK_PEAK_WINDOWS,
    STOCK_SESSION_END,
    STOCK_SESSION_START,
)


def _mins(hour: int, minute: int) -> int:
    return hour * 60 + minute


def _in_windows(
    cur: int, windows: tuple[tuple[tuple[int, int], tuple[int, int]], ...]
) -> bool:
    for (sh, sm), (eh, em) in windows:
        if _mins(sh, sm) <= cur <= _mins(eh, em):
            return True
    return False


def _minutes_until_next_open(now: datetime) -> int:
    cur = _mins(now.hour, now.minute)
    open_m = _mins(*STOCK_SESSION_START)
    for day in range(0, 8):
        day_dt = now + timedelta(days=day)
        if day_dt.weekday() >= 5:
            continue
        start = day * 24 * 60 + open_m
        delta = start - cur
        if delta > 0:
            return max(5, delta)
    return 24 * 60


def in_watch_session(now: datetime | None = None) -> bool:
    """投资者通常关注的交易时段（含开盘尾盘与盘中，不含午休）。"""
    now = now or dt_util.now()
    if now.weekday() >= 5:
        return False
    cur = _mins(now.hour, now.minute)
    return _in_windows(cur, STOCK_PEAK_WINDOWS) or _in_windows(cur, STOCK_ACTIVE_WINDOWS)


def calc_stock_interval_minutes(
    *,
    peak_minutes: int | None = None,
    active_minutes: int | None = None,
    trading_only: bool = True,
    now: datetime | None = None,
) -> int:
    now = now or dt_util.now()
    peak = max(1, int(peak_minutes or DEFAULT_STOCK_PEAK_INTERVAL))
    active = max(peak, int(active_minutes or DEFAULT_STOCK_ACTIVE_INTERVAL))
    cur = _mins(now.hour, now.minute)
    open_m = _mins(*STOCK_SESSION_START)
    close_m = _mins(*STOCK_SESSION_END)

    if now.weekday() >= 5:
        return _minutes_until_next_open(now)

    if _in_windows(cur, STOCK_PEAK_WINDOWS):
        return peak

    if _in_windows(cur, STOCK_ACTIVE_WINDOWS):
        return active

    if cur < open_m:
        return max(1, open_m - cur)

    lunch_end = _mins(13, 0)
    if _mins(11, 30) <= cur < lunch_end:
        return max(1, lunch_end - cur)

    if cur > close_m:
        if trading_only:
            return _minutes_until_next_open(now)
        return max(active * 6, 60)

    return active
