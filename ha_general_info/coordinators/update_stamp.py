from __future__ import annotations

from datetime import datetime

from homeassistant.util import dt as dt_util


def mark_updated(coord) -> None:
    coord.last_update_at = dt_util.utcnow()


def coord_updated_at(coord) -> datetime | None:
    return getattr(coord, "last_update_at", None)


def latest_updated_at(coords) -> datetime | None:
    times = [coord_updated_at(c) for c in coords if c is not None]
    times = [t for t in times if t is not None]
    return max(times) if times else None
