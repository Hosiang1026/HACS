from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from .const import NEWS_UPDATE_SLOTS


def minutes_until_next_slot(now: datetime | None = None) -> int:
    now = now or dt_util.now()
    cur = now.hour * 60 + now.minute
    candidates: list[int] = []
    for day in (0, 1):
        for hour, minute in NEWS_UPDATE_SLOTS:
            start = day * 24 * 60 + hour * 60 + minute
            delta = start - cur
            if delta > 0:
                candidates.append(delta)
    return max(5, min(candidates)) if candidates else 720


def calc_news_interval_minutes(
    *,
    fixed_minutes: int | None = None,
    now: datetime | None = None,
) -> int:
    fixed = int(fixed_minutes or 0)
    if fixed > 0:
        return max(5, fixed)
    return minutes_until_next_slot(now)
