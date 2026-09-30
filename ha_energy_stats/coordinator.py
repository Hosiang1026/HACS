from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import logging
import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BILLING_MODE,
    CONF_DAILY_COST_THRESHOLD,
    CONF_DAILY_EXTRA_MAX,
    CONF_DAILY_EXTRA_MIN,
    CONF_DAILY_RESET,
    CONF_ENERGY_NOTIFY,
    CONF_ENERGY_SENSOR,
    CONF_FLAT_RATE_1,
    CONF_FLAT_RATE_2,
    CONF_FLAT_RATE_3,
    CONF_INIT_MONTHLY_PEAK,
    CONF_INIT_MONTHLY_PEAK_COST,
    CONF_INIT_MONTHLY_VALLEY,
    CONF_INIT_MONTHLY_VALLEY_COST,
    CONF_INIT_YEARLY_PEAK,
    CONF_INIT_YEARLY_PEAK_COST,
    CONF_INIT_YEARLY_VALLEY,
    CONF_INIT_YEARLY_VALLEY_COST,
    CONF_MONTHLY_RESET_DAY,
    CONF_NOTIFY,
    CONF_PEAK_END,
    CONF_PEAK_RATE_1,
    CONF_PEAK_RATE_2,
    CONF_PEAK_RATE_3,
    CONF_PEAK_START,
    CONF_TIER1,
    CONF_TIER2,
    CONF_VALLEY_RATE_1,
    CONF_VALLEY_RATE_2,
    CONF_VALLEY_RATE_3,
    DEFAULT_BILLING_MODE,
    DEFAULT_DAILY_COST_THRESHOLD,
    DEFAULT_DAILY_EXTRA_MAX,
    DEFAULT_DAILY_EXTRA_MIN,
    DEFAULT_DAILY_RESET,
    DEFAULT_ENERGY_NOTIFY,
    DEFAULT_FLAT_RATE_1,
    DEFAULT_FLAT_RATE_2,
    DEFAULT_FLAT_RATE_3,
    DEFAULT_MONTHLY_RESET_DAY,
    DEFAULT_PEAK_END,
    DEFAULT_PEAK_RATE_1,
    DEFAULT_PEAK_RATE_2,
    DEFAULT_PEAK_RATE_3,
    DEFAULT_PEAK_START,
    DEFAULT_TIER1,
    DEFAULT_TIER2,
    DEFAULT_VALLEY_RATE_1,
    DEFAULT_VALLEY_RATE_2,
    DEFAULT_VALLEY_RATE_3,
    DOMAIN,
    MODE_FLAT,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

_PEAK_RATES = (CONF_PEAK_RATE_1, CONF_PEAK_RATE_2, CONF_PEAK_RATE_3)
_VALLEY_RATES = (CONF_VALLEY_RATE_1, CONF_VALLEY_RATE_2, CONF_VALLEY_RATE_3)
_FLAT_RATES = (CONF_FLAT_RATE_1, CONF_FLAT_RATE_2, CONF_FLAT_RATE_3)
_PEAK_DEFAULTS = (DEFAULT_PEAK_RATE_1, DEFAULT_PEAK_RATE_2, DEFAULT_PEAK_RATE_3)
_VALLEY_DEFAULTS = (DEFAULT_VALLEY_RATE_1, DEFAULT_VALLEY_RATE_2, DEFAULT_VALLEY_RATE_3)
_FLAT_DEFAULTS = (DEFAULT_FLAT_RATE_1, DEFAULT_FLAT_RATE_2, DEFAULT_FLAT_RATE_3)

_ENERGY_Q = Decimal("0.000001")
_COST_Q = Decimal("0.000001")
_ENERGY_OUT = Decimal("0.01")
_COST_OUT = Decimal("0.01")
_RATE_OUT = Decimal("0.0001")
_EPS = Decimal("0.000000001")
_ENERGY_KEYS = (
    "daily_peak",
    "daily_valley",
    "monthly_peak",
    "monthly_valley",
    "yearly_peak",
    "yearly_valley",
)
_COST_KEYS = (
    "daily_peak_cost",
    "daily_valley_cost",
    "monthly_peak_cost",
    "monthly_valley_cost",
    "yearly_peak_cost",
    "yearly_valley_cost",
)


def _dec(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _q_energy(value: Any) -> Decimal:
    return _dec(value).quantize(_ENERGY_Q, rounding=ROUND_HALF_UP)


def _q_cost(value: Any) -> Decimal:
    return _dec(value).quantize(_COST_Q, rounding=ROUND_HALF_UP)


def _store_energy(value: Any) -> str:
    return format(_q_energy(value), "f")


def _store_cost(value: Any) -> str:
    return format(_q_cost(value), "f")


def _out_energy(value: Any) -> float:
    return float(_dec(value).quantize(_ENERGY_OUT, rounding=ROUND_HALF_UP))


def _out_cost(value: Any) -> float:
    return float(_dec(value).quantize(_COST_OUT, rounding=ROUND_HALF_UP))


def _out_rate(value: Any) -> float:
    return float(_dec(value).quantize(_RATE_OUT, rounding=ROUND_HALF_UP))


def _out_sum(left: float, right: float) -> float:
    return float((_dec(str(left)) + _dec(str(right))).quantize(_ENERGY_OUT, rounding=ROUND_HALF_UP))


def _read_meter(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _item_month(item: dict[str, Any] | None) -> str:
    raw = str((item or {}).get("date") or (item or {}).get("day") or (item or {}).get("month") or "")
    return raw[:7]


def _parse_time(value: str | None) -> time:
    if not value:
        return time(0, 0, 0)
    try:
        parts = str(value).split(":")
        return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)
    except (TypeError, ValueError, IndexError):
        return time(0, 0, 0)


def _prev_day(iso: str) -> str:
    try:
        y, m, d = (int(p) for p in str(iso).split("-")[:3])
        return (datetime(y, m, d) - timedelta(days=1)).date().isoformat()
    except (TypeError, ValueError):
        return iso[:10] if iso else iso


def _as_day(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    return text


def _as_month(value: Any) -> str:
    text = str(value or "")
    return text[:7] if len(text) >= 7 else text


def _as_year(value: Any, fallback: int) -> int:
    if value in (None, ""):
        return fallback
    try:
        return int(str(value)[:4])
    except (TypeError, ValueError):
        return fallback


def _nget(tr: dict[str, str], key: str, default: str, **kwargs: Any) -> str:
    val = (
        tr.get(f"component.{DOMAIN}.common.{key}")
        or tr.get(f"component.{DOMAIN}.{key}")
        or default
    )
    val = val.replace("\\n", "\n")
    if kwargs:
        try:
            return val.format(**kwargs)
        except (KeyError, ValueError, IndexError):
            return val
    return val


def _notify_items(raw: Any) -> list:
    if not raw:
        return []
    if isinstance(raw, (str, dict)):
        return [raw]
    return list(raw)


def _empty_bucket() -> dict[str, str]:
    return {
        "daily_peak": "0",
        "daily_valley": "0",
        "daily_peak_cost": "0",
        "daily_valley_cost": "0",
        "monthly_peak": "0",
        "monthly_valley": "0",
        "monthly_peak_cost": "0",
        "monthly_valley_cost": "0",
        "yearly_peak": "0",
        "yearly_valley": "0",
        "yearly_peak_cost": "0",
        "yearly_valley_cost": "0",
    }


class EnergyStatsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=60),
        )
        self.entry = entry
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        now = dt_util.now()
        day, ym, year, _ = self._period_keys(now)
        self._data: dict[str, Any] = {
            **_empty_bucket(),
            "last_energy": None,
            "last_reset_date": day,
            "last_month": ym,
            "last_year": year,
            "history": [],
            "daily_history": [],
            "yearly_history": [],
            "pending_month": None,
            "source_sensor": None,
            "extra_applied_date": None,
            "extra_applied_sec": 0,
            "extra_value_date": None,
            "extra_today": None,
        }
        self._unsub: list[Any] = []
        self._reset_lock = asyncio.Lock()
        self._pending_notify: list[tuple[str, dict[str, Any], datetime]] = []
        self._active = True

    @property
    def device_name(self) -> str:
        return self.entry.data.get("name", self.entry.title)

    def cfg(self, key: str, default: Any = None) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    async def async_setup(self) -> None:
        stored = await self.store.async_load()
        if stored:
            self._data.update(stored)
        else:
            self._apply_init()
        sensor = self.cfg(CONF_ENERGY_SENSOR)
        prev_source = self._data.get("source_sensor")
        source_changed = False
        if prev_source is None:
            self._data["source_sensor"] = sensor
            source_changed = True
        elif prev_source != sensor:
            self._data["source_sensor"] = sensor
            self._data["last_energy"] = None
            source_changed = True
        self._normalize_store()
        if not stored or source_changed:
            await self.store.async_save(self._data)
        if await self._maybe_reset(notify=True):
            self._normalize_store()
            await self.store.async_save(self._data)
        if sensor:
            self._unsub.append(
                async_track_state_change_event(self.hass, [sensor], self._on_energy)
            )
            await self._async_apply_state(self.hass.states.get(sensor))
        reset = _parse_time(self.cfg(CONF_DAILY_RESET, DEFAULT_DAILY_RESET))
        self._unsub.append(
            async_track_time_change(
                self.hass,
                self._on_reset,
                hour=reset.hour,
                minute=reset.minute,
                second=reset.second,
            )
        )
        await self.async_config_entry_first_refresh()

    def _apply_init(self) -> None:
        mapping = {
            "monthly_peak": CONF_INIT_MONTHLY_PEAK,
            "monthly_valley": CONF_INIT_MONTHLY_VALLEY,
            "monthly_peak_cost": CONF_INIT_MONTHLY_PEAK_COST,
            "monthly_valley_cost": CONF_INIT_MONTHLY_VALLEY_COST,
            "yearly_peak": CONF_INIT_YEARLY_PEAK,
            "yearly_valley": CONF_INIT_YEARLY_VALLEY,
            "yearly_peak_cost": CONF_INIT_YEARLY_PEAK_COST,
            "yearly_valley_cost": CONF_INIT_YEARLY_VALLEY_COST,
        }
        for dest, key in mapping.items():
            raw = self.cfg(key, 0) or 0
            self._data[dest] = (
                _store_cost(raw) if dest.endswith("_cost") else _store_energy(raw)
            )

    async def async_shutdown(self) -> None:
        self._active = False
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        async with self._reset_lock:
            self._normalize_store()
            await self.store.async_save(self._data)

    def _normalize_store(self) -> None:
        for key in _ENERGY_KEYS:
            self._data[key] = _store_energy(self._data.get(key, 0))
        for key in _COST_KEYS:
            self._data[key] = _store_cost(self._data.get(key, 0))
        last = _read_meter(self._data.get("last_energy"))
        self._data["last_energy"] = format(last, "f") if last is not None else None
        day = _as_day(self._data.get("last_reset_date"))
        if day:
            self._data["last_reset_date"] = day
        extra_day = _as_day(self._data.get("extra_applied_date"))
        self._data["extra_applied_date"] = extra_day
        try:
            self._data["extra_applied_sec"] = max(
                0, min(int(self._data.get("extra_applied_sec") or 0), 86400)
            )
        except (TypeError, ValueError):
            self._data["extra_applied_sec"] = 0
        self._data["extra_value_date"] = _as_day(self._data.get("extra_value_date"))
        if self._data.get("extra_today") not in (None, ""):
            self._data["extra_today"] = format(_q_energy(self._data.get("extra_today")), "f")
        else:
            self._data["extra_today"] = None
        if self._data.get("last_month"):
            self._data["last_month"] = _as_month(self._data.get("last_month"))
        if self._data.get("last_year") not in (None, ""):
            self._data["last_year"] = _as_year(self._data.get("last_year"), 0) or self._data.get("last_year")
        cleaned = []
        for item in self._data.get("yearly_history") or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row.pop("months", None)
            cleaned.append(row)
        self._data["yearly_history"] = cleaned
        bill_ym = str(self._data.get("last_month") or "")
        if bill_ym:
            self._data["daily_history"] = [
                d
                for d in (self._data.get("daily_history") or [])
                if isinstance(d, dict) and _item_month(d) == bill_ym
            ]
        year_s = str(self._data.get("last_year") or "")
        if year_s:
            self._data["history"] = [
                h
                for h in (self._data.get("history") or [])
                if isinstance(h, dict) and str(h.get("month", "")).startswith(year_s)
            ]

    async def _save(self) -> None:
        self._normalize_store()
        await self.store.async_save(self._data)
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        if self._active and await self._maybe_reset(notify=True) and self._active:
            self._normalize_store()
            await self.store.async_save(self._data)
        return self._computed()

    def _computed(self) -> dict[str, Any]:
        dp = _dec(self._data.get("daily_peak", 0))
        dv = _dec(self._data.get("daily_valley", 0))
        dpc = _dec(self._data.get("daily_peak_cost", 0))
        dvc = _dec(self._data.get("daily_valley_cost", 0))
        mp = _dec(self._data.get("monthly_peak", 0))
        mv = _dec(self._data.get("monthly_valley", 0))
        mpc = _dec(self._data.get("monthly_peak_cost", 0))
        mvc = _dec(self._data.get("monthly_valley_cost", 0))
        yp = _dec(self._data.get("yearly_peak", 0))
        yv = _dec(self._data.get("yearly_valley", 0))
        ypc = _dec(self._data.get("yearly_peak_cost", 0))
        yvc = _dec(self._data.get("yearly_valley_cost", 0))
        ye = yp + yv
        tier = self._tier_of(ye)
        pr = self._rate(tier, True)
        vr = self._rate(tier, False)
        today, _, year_i, _ = self._period_keys()
        year = str(_as_year(self._data.get("last_year"), year_i))
        ym = _as_month(self._data.get("last_month") or today)
        history = [
            self._coerce_month(h)
            for h in (self._data.get("history") or [])
            if str((h or {}).get("month", "")).startswith(year)
        ]
        pending = self._data.get("pending_month")
        if isinstance(pending, dict) and str(pending.get("month", "")).startswith(year):
            p_ym = str(pending.get("month") or "")
            if p_ym and p_ym != ym:
                history = [h for h in history if h.get("month") != p_ym] + [
                    self._coerce_month(pending)
                ]
        cur_month = self._month_entry(ym, mp, mv, mpc, mvc)
        history = [h for h in history if h.get("month") != ym] + [cur_month]
        history.sort(key=lambda h: str(h.get("month", "")))
        days = [
            self._coerce_day(d)
            for d in (self._data.get("daily_history") or [])
            if _as_day((d or {}).get("date") or (d or {}).get("day")) != today
            and _item_month(d) == ym
        ]
        days.sort(key=lambda d: str(d.get("date") or d.get("day") or ""))
        days.append(self._day_entry(today, dp, dv, dpc, dvc))
        years = [
            self._coerce_year(y)
            for y in (self._data.get("yearly_history") or [])
            if str((y or {}).get("year", "")) != year
        ]
        years.append(self._year_entry(year, yp, yv, ypc, yvc))
        years.sort(key=lambda y: str(y.get("year", "")))
        dp_o, dv_o = _out_energy(dp), _out_energy(dv)
        dpc_o, dvc_o = _out_cost(dpc), _out_cost(dvc)
        mp_o, mv_o = _out_energy(mp), _out_energy(mv)
        mpc_o, mvc_o = _out_cost(mpc), _out_cost(mvc)
        yp_o, yv_o = _out_energy(yp), _out_energy(yv)
        ypc_o, yvc_o = _out_cost(ypc), _out_cost(yvc)
        return {
            "daily_peak": dp_o,
            "daily_valley": dv_o,
            "daily_energy": _out_sum(dp_o, dv_o),
            "daily_peak_cost": dpc_o,
            "daily_valley_cost": dvc_o,
            "daily_cost": _out_sum(dpc_o, dvc_o),
            "monthly_peak": mp_o,
            "monthly_valley": mv_o,
            "monthly_energy": _out_sum(mp_o, mv_o),
            "monthly_peak_cost": mpc_o,
            "monthly_valley_cost": mvc_o,
            "monthly_cost": _out_sum(mpc_o, mvc_o),
            "yearly_peak": yp_o,
            "yearly_valley": yv_o,
            "yearly_energy": _out_sum(yp_o, yv_o),
            "yearly_peak_cost": ypc_o,
            "yearly_valley_cost": yvc_o,
            "yearly_cost": _out_sum(ypc_o, yvc_o),
            "tier": tier,
            "peak_rate": _out_rate(pr),
            "valley_rate": _out_rate(vr),
            "realtime_rate": _out_rate(pr if self._is_peak() else vr),
            "history": history,
            "history_count": len(history),
            "daily_history": days,
            "daily_history_count": len(days),
            "yearly_history": years,
            "yearly_history_count": len(years),
        }

    def _tier_of(self, energy: Decimal) -> int:
        t1 = _dec(self.cfg(CONF_TIER1, DEFAULT_TIER1))
        t2 = _dec(self.cfg(CONF_TIER2, DEFAULT_TIER2))
        if energy <= t1:
            return 1
        if energy <= t2:
            return 2
        return 3

    def _room(self, energy: Decimal, tier: int) -> Decimal:
        t1 = _dec(self.cfg(CONF_TIER1, DEFAULT_TIER1))
        t2 = _dec(self.cfg(CONF_TIER2, DEFAULT_TIER2))
        if tier == 1:
            return max(t1 - energy, Decimal("0"))
        if tier == 2:
            return max(t2 - energy, Decimal("0"))
        return Decimal("1000000000")

    def _rate(self, tier: int, peak: bool) -> Decimal:
        idx = max(min(tier, 3), 1) - 1
        if self.cfg(CONF_BILLING_MODE, DEFAULT_BILLING_MODE) == MODE_FLAT:
            return _dec(self.cfg(_FLAT_RATES[idx], _FLAT_DEFAULTS[idx]))
        if peak:
            return _dec(self.cfg(_PEAK_RATES[idx], _PEAK_DEFAULTS[idx]))
        return _dec(self.cfg(_VALLEY_RATES[idx], _VALLEY_DEFAULTS[idx]))

    def _yearly_energy(self) -> Decimal:
        return _dec(self._data.get("yearly_peak", 0)) + _dec(
            self._data.get("yearly_valley", 0)
        )

    def _period_day(self, now: datetime | None = None) -> str:
        now = now or dt_util.now()
        reset = _parse_time(self.cfg(CONF_DAILY_RESET, DEFAULT_DAILY_RESET))
        t = now.time().replace(microsecond=0)
        d = now.date()
        if t < reset:
            d = d - timedelta(days=1)
        return d.isoformat()

    def _period_keys(
        self, now: datetime | None = None
    ) -> tuple[str, str, int, int]:
        day = self._period_day(now)
        y, m, d = (int(p) for p in day.split("-"))
        return day, f"{y:04d}-{m:02d}", y, d

    def _is_peak(self, now: datetime | None = None) -> bool:
        now = now or dt_util.now()
        t = now.time().replace(microsecond=0)
        start = _parse_time(self.cfg(CONF_PEAK_START, DEFAULT_PEAK_START))
        end = _parse_time(self.cfg(CONF_PEAK_END, DEFAULT_PEAK_END))
        if start <= end:
            return start <= t < end
        return t >= start or t < end

    def _billing_start(self, today: str, now: datetime | None = None) -> datetime:
        now = now or dt_util.now()
        y, m, d = (int(p) for p in today.split("-"))
        reset = _parse_time(self.cfg(CONF_DAILY_RESET, DEFAULT_DAILY_RESET))
        return now.replace(
            year=y,
            month=m,
            day=d,
            hour=reset.hour,
            minute=reset.minute,
            second=reset.second,
            microsecond=0,
        )

    def _billing_elapsed_sec(self, today: str, now: datetime | None = None) -> int:
        now = now or dt_util.now()
        start = self._billing_start(today, now)
        return max(0, min(int((now - start).total_seconds()), 86400))

    @staticmethod
    def _overlap_sec(a0: int, a1: int, b0: int, b1: int) -> int:
        return max(0, min(a1, b1) - max(a0, b0))

    def _count_peak_seconds(self, t0: datetime, t1: datetime) -> int:
        if t1 <= t0:
            return 0
        peak_start = _parse_time(self.cfg(CONF_PEAK_START, DEFAULT_PEAK_START))
        peak_end = _parse_time(self.cfg(CONF_PEAK_END, DEFAULT_PEAK_END))
        ps = peak_start.hour * 3600 + peak_start.minute * 60 + peak_start.second
        pe = peak_end.hour * 3600 + peak_end.minute * 60 + peak_end.second
        total = 0
        cur = t0
        while cur < t1:
            day_start = cur.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            ws = cur
            we = min(t1, day_end)
            a0 = int((ws - day_start).total_seconds())
            a1 = int((we - day_start).total_seconds())
            if peak_start <= peak_end:
                total += self._overlap_sec(a0, a1, ps, pe)
            else:
                total += self._overlap_sec(a0, a1, ps, 86400)
                total += self._overlap_sec(a0, a1, 0, pe)
            cur = we
        return total

    def _extra_range(self) -> tuple[Decimal, Decimal]:
        lo = _q_energy(self.cfg(CONF_DAILY_EXTRA_MIN, DEFAULT_DAILY_EXTRA_MIN) or 0)
        hi = _q_energy(self.cfg(CONF_DAILY_EXTRA_MAX, DEFAULT_DAILY_EXTRA_MAX) or 0)
        if hi < lo:
            return hi, lo
        return lo, hi

    def _daily_extra_value(self, today: str) -> Decimal:
        if (
            _as_day(self._data.get("extra_value_date")) == today
            and self._data.get("extra_today") not in (None, "")
        ):
            return _q_energy(self._data.get("extra_today"))
        lo, hi = self._extra_range()
        if hi <= _EPS:
            val = Decimal("0")
        elif lo == hi:
            val = lo
        else:
            val = _q_energy(Decimal(str(random.uniform(float(lo), float(hi)))))
        self._data["extra_value_date"] = today
        self._data["extra_today"] = format(val, "f")
        return val

    def _apply_daily_extra(self, today: str) -> bool:
        now = dt_util.now()
        applied_day = _as_day(self._data.get("extra_applied_date"))
        if applied_day != today:
            self._data["extra_applied_date"] = today
            self._data["extra_applied_sec"] = 0
            applied_sec = 0
            changed_day = True
        else:
            changed_day = False
            try:
                applied_sec = max(0, min(int(self._data.get("extra_applied_sec") or 0), 86400))
            except (TypeError, ValueError):
                applied_sec = 0
        target_sec = self._billing_elapsed_sec(today, now)
        _, hi = self._extra_range()
        if hi <= _EPS:
            if target_sec > applied_sec:
                self._data["extra_applied_sec"] = target_sec
            return changed_day
        if target_sec <= applied_sec:
            return False
        had_value = (
            _as_day(self._data.get("extra_value_date")) == today
            and self._data.get("extra_today") not in (None, "")
        )
        extra = self._daily_extra_value(today)
        if not had_value and applied_sec > 0:
            self._data["extra_applied_sec"] = target_sec
            return True
        self._data["extra_applied_sec"] = target_sec
        if extra <= _EPS:
            return True
        start = self._billing_start(today, now)
        t0 = start + timedelta(seconds=applied_sec)
        t1 = start + timedelta(seconds=target_sec)
        peak_secs = self._count_peak_seconds(t0, t1)
        valley_secs = (target_sec - applied_sec) - peak_secs
        rate = extra / Decimal(86400)
        peak_part = _q_energy(rate * Decimal(peak_secs))
        valley_part = _q_energy(rate * Decimal(max(valley_secs, 0)))
        if peak_part > _EPS:
            self._apply_delta(peak_part, True)
        if valley_part > _EPS:
            self._apply_delta(valley_part, False)
        return True

    def _apply_delta(self, delta: Decimal, is_peak: bool) -> None:
        remain = _q_energy(delta)
        kind = "peak" if is_peak else "valley"
        guard = 0
        while remain > _EPS and guard < 8:
            guard += 1
            yearly = self._yearly_energy()
            tier = self._tier_of(yearly)
            room = self._room(yearly, tier)
            if room <= _EPS:
                if tier < 3:
                    tier += 1
                    room = self._room(yearly, tier)
                else:
                    room = remain
            chunk = min(remain, room)
            if chunk <= _EPS:
                chunk = remain
            chunk = _q_energy(chunk)
            cost = _q_cost(chunk * self._rate(tier, is_peak))
            self._data[f"daily_{kind}"] = _store_energy(
                _dec(self._data.get(f"daily_{kind}", 0)) + chunk
            )
            self._data[f"daily_{kind}_cost"] = _store_cost(
                _dec(self._data.get(f"daily_{kind}_cost", 0)) + cost
            )
            self._data[f"monthly_{kind}"] = _store_energy(
                _dec(self._data.get(f"monthly_{kind}", 0)) + chunk
            )
            self._data[f"monthly_{kind}_cost"] = _store_cost(
                _dec(self._data.get(f"monthly_{kind}_cost", 0)) + cost
            )
            self._data[f"yearly_{kind}"] = _store_energy(
                _dec(self._data.get(f"yearly_{kind}", 0)) + chunk
            )
            self._data[f"yearly_{kind}_cost"] = _store_cost(
                _dec(self._data.get(f"yearly_{kind}_cost", 0)) + cost
            )
            remain = _q_energy(remain - chunk)

    def _to_kwh(self, value: Decimal, unit: str | None) -> Decimal:
        u = (unit or "").strip().lower().replace(" ", "")
        if u in ("wh", "w·h", "w.h"):
            return value / Decimal("1000")
        if u in ("mwh", "mw·h", "mw.h"):
            return value * Decimal("1000")
        return value

    def _parse_energy(self, state) -> Decimal | None:
        if state is None or state.state in ("unknown", "unavailable", "", "none"):
            return None
        try:
            return Decimal(str(state.state))
        except (InvalidOperation, ValueError, TypeError):
            return None

    async def _async_apply_state(self, state) -> None:
        if not self._active:
            return
        value = self._parse_energy(state)
        if value is None:
            return
        async with self._reset_lock:
            settled = self._maybe_reset_locked(True)
            last_d = _read_meter(self._data.get("last_energy"))
            applied = False
            if last_d is None:
                self._data["last_energy"] = format(value, "f")
                applied = True
            else:
                delta_raw = value - last_d
                self._data["last_energy"] = format(value, "f")
                if delta_raw < 0:
                    applied = True
                elif delta_raw > 0:
                    delta = self._to_kwh(
                        delta_raw, state.attributes.get("unit_of_measurement")
                    )
                    if delta > 0:
                        self._apply_delta(delta, self._is_peak())
                        applied = True
            pending = self._pending_notify
            self._pending_notify = []
        for period, snap, when in pending:
            await self._notify_period(period, snap, when)
        if self._active and (settled or applied):
            await self._save()

    @callback
    def _on_energy(self, event: Event) -> None:
        self.hass.async_create_task(
            self._async_apply_state(event.data.get("new_state"))
        )

    def _coerce_day(self, item: dict[str, Any] | None) -> dict[str, Any]:
        item = item or {}
        peak = _dec(item.get("peak", 0))
        valley = _dec(item.get("valley", 0))
        peak_cost = _dec(item.get("peak_cost", 0))
        valley_cost = _dec(item.get("valley_cost", 0))
        energy = _dec(item.get("energy") or item.get("dayElePq") or 0)
        cost = _dec(item.get("cost") or item.get("dayEleCost") or 0)
        if peak == 0 and valley == 0 and energy:
            peak = energy
        if peak_cost == 0 and valley_cost == 0 and cost:
            peak_cost = cost
        return self._day_entry(
            str(item.get("date") or item.get("day") or ""),
            peak,
            valley,
            peak_cost,
            valley_cost,
        )

    def _coerce_month(self, item: dict[str, Any] | None) -> dict[str, Any]:
        item = item or {}
        peak = _dec(item.get("peak", 0))
        valley = _dec(item.get("valley", 0))
        peak_cost = _dec(item.get("peak_cost", 0))
        valley_cost = _dec(item.get("valley_cost", 0))
        energy = _dec(item.get("energy") or item.get("monthEleNum") or 0)
        cost = _dec(item.get("cost") or item.get("monthEleCost") or 0)
        if peak == 0 and valley == 0 and energy:
            peak = energy
        if peak_cost == 0 and valley_cost == 0 and cost:
            peak_cost = cost
        return self._month_entry(
            str(item.get("month") or ""),
            peak,
            valley,
            peak_cost,
            valley_cost,
        )

    def _day_entry(
        self,         date_s: str, peak: Any, valley: Any, peak_cost: Any, valley_cost: Any
    ) -> dict[str, Any]:
        date_s = _as_day(date_s) or str(date_s)
        peak_d = _dec(peak)
        valley_d = _dec(valley)
        peak_cost_d = _dec(peak_cost)
        valley_cost_d = _dec(valley_cost)
        peak_o = _out_energy(peak_d)
        valley_o = _out_energy(valley_d)
        peak_cost_o = _out_cost(peak_cost_d)
        valley_cost_o = _out_cost(valley_cost_d)
        energy = _out_sum(peak_o, valley_o)
        cost = _out_sum(peak_cost_o, valley_cost_o)
        return {
            "date": date_s,
            "day": date_s,
            "peak": peak_o,
            "valley": valley_o,
            "energy": energy,
            "dayElePq": energy,
            "peak_cost": peak_cost_o,
            "valley_cost": valley_cost_o,
            "cost": cost,
            "dayEleCost": cost,
        }

    def _month_entry(
        self,         ym: str, peak: Any, valley: Any, peak_cost: Any, valley_cost: Any
    ) -> dict[str, Any]:
        ym = _as_month(ym)
        peak_d = _dec(peak)
        valley_d = _dec(valley)
        peak_cost_d = _dec(peak_cost)
        valley_cost_d = _dec(valley_cost)
        peak_o = _out_energy(peak_d)
        valley_o = _out_energy(valley_d)
        peak_cost_o = _out_cost(peak_cost_d)
        valley_cost_o = _out_cost(valley_cost_d)
        energy = _out_sum(peak_o, valley_o)
        cost = _out_sum(peak_cost_o, valley_cost_o)
        return {
            "month": ym,
            "endDate": f"{ym}-01",
            "peak": peak_o,
            "valley": valley_o,
            "energy": energy,
            "monthEleNum": energy,
            "peak_cost": peak_cost_o,
            "valley_cost": valley_cost_o,
            "cost": cost,
            "monthEleCost": cost,
        }

    def _coerce_year(self, item: dict[str, Any] | None) -> dict[str, Any]:
        item = item or {}
        peak = _dec(item.get("peak", 0))
        valley = _dec(item.get("valley", 0))
        peak_cost = _dec(item.get("peak_cost", 0))
        valley_cost = _dec(item.get("valley_cost", 0))
        energy = _dec(item.get("energy") or item.get("yearEleNum") or 0)
        cost = _dec(item.get("cost") or item.get("yearEleCost") or 0)
        if peak == 0 and valley == 0 and energy:
            peak = energy
        if peak_cost == 0 and valley_cost == 0 and cost:
            peak_cost = cost
        return self._year_entry(
            str(item.get("year") or ""),
            peak,
            valley,
            peak_cost,
            valley_cost,
        )

    def _year_entry(
        self,
        year: str,
        peak: Any,
        valley: Any,
        peak_cost: Any,
        valley_cost: Any,
    ) -> dict[str, Any]:
        peak_d = _dec(peak)
        valley_d = _dec(valley)
        peak_cost_d = _dec(peak_cost)
        valley_cost_d = _dec(valley_cost)
        peak_o = _out_energy(peak_d)
        valley_o = _out_energy(valley_d)
        peak_cost_o = _out_cost(peak_cost_d)
        valley_cost_o = _out_cost(valley_cost_d)
        energy = _out_sum(peak_o, valley_o)
        cost = _out_sum(peak_cost_o, valley_cost_o)
        return {
            "year": str(year),
            "peak": peak_o,
            "valley": valley_o,
            "energy": energy,
            "yearEleNum": energy,
            "peak_cost": peak_cost_o,
            "valley_cost": valley_cost_o,
            "cost": cost,
            "yearEleCost": cost,
        }

    def _snapshot(self, prefix: str) -> dict[str, float]:
        peak_o = _out_energy(_dec(self._data.get(f"{prefix}_peak", 0)))
        valley_o = _out_energy(_dec(self._data.get(f"{prefix}_valley", 0)))
        peak_cost_o = _out_cost(_dec(self._data.get(f"{prefix}_peak_cost", 0)))
        valley_cost_o = _out_cost(_dec(self._data.get(f"{prefix}_valley_cost", 0)))
        return {
            "peak": peak_o,
            "valley": valley_o,
            "energy": _out_sum(peak_o, valley_o),
            "peak_cost": peak_cost_o,
            "valley_cost": valley_cost_o,
            "cost": _out_sum(peak_cost_o, valley_cost_o),
        }

    def _reset_prefix(self, prefix: str) -> None:
        self._data[f"{prefix}_peak"] = "0"
        self._data[f"{prefix}_valley"] = "0"
        self._data[f"{prefix}_peak_cost"] = "0"
        self._data[f"{prefix}_valley_cost"] = "0"

    def _stash_month(self) -> dict[str, Any]:
        snap = self._snapshot("monthly")
        ym = _as_month(self._data.get("last_month") or self._period_keys()[1])
        entry = self._month_entry(
            ym, snap["peak"], snap["valley"], snap["peak_cost"], snap["valley_cost"]
        )
        self._data["daily_history"] = [
            d for d in (self._data.get("daily_history") or []) if _item_month(d) != ym
        ]
        self._reset_prefix("monthly")
        self._data["pending_month"] = entry
        return entry

    def _commit_pending_month(self) -> dict[str, Any] | None:
        entry = self._data.get("pending_month")
        self._data["pending_month"] = None
        if not isinstance(entry, dict) or not entry.get("month"):
            return None
        ym = str(entry.get("month"))
        history = [
            h for h in (self._data.get("history") or []) if h.get("month") != ym
        ]
        history.append(entry)
        history.sort(key=lambda h: str(h.get("month", "")))
        self._data["history"] = history
        return entry

    def _close_year(self) -> dict[str, Any]:
        year = str(_as_year(self._data.get("last_year"), self._period_keys()[2]))
        yp = _dec(self._data.get("yearly_peak"))
        yv = _dec(self._data.get("yearly_valley"))
        ypc = _dec(self._data.get("yearly_peak_cost"))
        yvc = _dec(self._data.get("yearly_valley_cost"))
        lm = _as_month(self._data.get("last_month") or "")
        carry = bool(lm and not lm.startswith(year))
        if carry:
            mp = _dec(self._data.get("monthly_peak"))
            mv = _dec(self._data.get("monthly_valley"))
            mpc = _dec(self._data.get("monthly_peak_cost"))
            mvc = _dec(self._data.get("monthly_valley_cost"))
            yp = max(yp - mp, Decimal("0"))
            yv = max(yv - mv, Decimal("0"))
            ypc = max(ypc - mpc, Decimal("0"))
            yvc = max(yvc - mvc, Decimal("0"))
        entry = self._year_entry(year, yp, yv, ypc, yvc)
        years = [
            y
            for y in (self._data.get("yearly_history") or [])
            if str((y or {}).get("year", "")) != year
        ]
        years.append(entry)
        years.sort(key=lambda y: str(y.get("year", "")))
        self._data["yearly_history"] = years
        if carry:
            self._data["yearly_peak"] = _store_energy(self._data.get("monthly_peak"))
            self._data["yearly_valley"] = _store_energy(self._data.get("monthly_valley"))
            self._data["yearly_peak_cost"] = _store_cost(
                self._data.get("monthly_peak_cost")
            )
            self._data["yearly_valley_cost"] = _store_cost(
                self._data.get("monthly_valley_cost")
            )
        else:
            self._reset_prefix("yearly")
        self._data["history"] = []
        return entry

    async def _maybe_reset(self, notify: bool = False) -> bool:
        async with self._reset_lock:
            changed = self._maybe_reset_locked(notify)
            pending = self._pending_notify
            self._pending_notify = []
        for period, snap, when in pending:
            await self._notify_period(period, snap, when)
        return changed

    def _maybe_reset_locked(self, notify: bool) -> bool:
        now = dt_util.now()
        today, month_key, year, day_n = self._period_keys(now)
        changed = False
        last = _as_day(self._data.get("last_reset_date"))
        if last is None:
            if not self._data.get("last_month"):
                self._data["last_month"] = month_key
            if self._data.get("last_year") in (None, ""):
                self._data["last_year"] = year
            if _as_month(self._data.get("last_month") or month_key) != month_key:
                last = _prev_day(today)
            else:
                self._data["last_reset_date"] = today
                last = today
                changed = True
        last_year = _as_year(self._data.get("last_year"), year)
        year_changed = last_year != year
        if last != today:
            daily_snap = self._snapshot("daily")
            entry = self._day_entry(
                last,
                daily_snap["peak"],
                daily_snap["valley"],
                daily_snap["peak_cost"],
                daily_snap["valley_cost"],
            )
            days = [
                d
                for d in (self._data.get("daily_history") or [])
                if _as_day(d.get("date") or d.get("day")) != last
            ]
            days.append(entry)
            keep = _as_month(self._data.get("last_month") or today)
            days = [d for d in days if _item_month(d) == keep]
            days.sort(key=lambda d: str(d.get("date") or d.get("day") or ""))
            self._data["daily_history"] = days
            self._reset_prefix("daily")
            self._data["last_reset_date"] = today
            changed = True
            if notify:
                self._pending_notify.append(("daily", daily_snap, now))
        reset_day = int(
            float(self.cfg(CONF_MONTHLY_RESET_DAY, DEFAULT_MONTHLY_RESET_DAY) or DEFAULT_MONTHLY_RESET_DAY)
        )
        last_month = _as_month(self._data.get("last_month") or month_key)
        if last_month != month_key:
            old_pending = self._data.get("pending_month")
            if isinstance(old_pending, dict) and old_pending.get("month"):
                self._commit_pending_month()
                if notify:
                    self._pending_notify.append(("monthly", old_pending, now))
            self._stash_month()
            self._data["last_month"] = month_key
            changed = True
        pending = self._data.get("pending_month")
        if isinstance(pending, dict) and pending.get("month") and (
            day_n >= reset_day or year_changed
        ):
            monthly_snap = self._commit_pending_month()
            changed = True
            if notify and monthly_snap:
                self._pending_notify.append(("monthly", monthly_snap, now))
        if year_changed:
            yearly_snap = self._close_year()
            self._data["last_year"] = year
            changed = True
            if notify:
                self._pending_notify.append(("yearly", yearly_snap, now))
        if self._apply_daily_extra(today):
            changed = True
        return changed

    @callback
    def _on_reset(self, now: datetime) -> None:
        self.hass.async_create_task(self._async_on_reset())

    async def _async_on_reset(self) -> None:
        if not self._active:
            return
        if await self._maybe_reset(notify=True) and self._active:
            await self._save()

    async def _notify_period(
        self, period: str, snap: dict[str, Any], now: datetime
    ) -> None:
        if not self.cfg(CONF_ENERGY_NOTIFY, DEFAULT_ENERGY_NOTIFY):
            return
        if period == "daily":
            threshold = float(
                self.cfg(CONF_DAILY_COST_THRESHOLD, DEFAULT_DAILY_COST_THRESHOLD) or 0
            )
            if float(snap.get("cost", 0) or 0) <= threshold:
                return
        tr = await async_get_translations(
            self.hass, self.hass.config.language, "common", [DOMAIN]
        )
        title = _nget(
            tr,
            f"{period}_title",
            {"daily": "今日电费通知", "monthly": "本月电费通知", "yearly": "本年电费通知"}[
                period
            ],
        )
        message = _nget(
            tr,
            "energy_message",
            "高峰电量：{peak}kWh\n低谷电量：{valley}kWh\n总计电量：{energy}kWh\n应付电费：{cost}¥",
            peak=snap.get("peak", 0),
            valley=snap.get("valley", 0),
            energy=snap.get("energy", 0),
            cost=snap.get("cost", 0),
        )
        await self._send_notify(title, message)

    async def _send_notify(self, title: str, message: str) -> None:
        message = str(message).replace("\\n", "\n").strip()
        stamp = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
        notify_message = f"{message}\n\n本通知 By 狂欢马克思\n通知时间: {stamp}"
        for item in _notify_items(self.cfg(CONF_NOTIFY)):
            action = None
            data: dict[str, Any] = {}
            target = None
            if isinstance(item, str):
                action = item
            elif isinstance(item, dict):
                action = item.get("action") or item.get("service")
                data = dict(item.get("data") or {})
                target = item.get("target")
            if not action or "." not in action:
                continue
            data["title"] = title
            data["message"] = notify_message
            domain, service = action.split(".", 1)
            try:
                if self.hass.services.has_service(domain, service):
                    await self.hass.services.async_call(
                        domain, service, data, target=target, blocking=False
                    )
                elif domain == "notify" and self.hass.states.get(action):
                    await self.hass.services.async_call(
                        "notify",
                        "send_message",
                        {"entity_id": action, "title": title, "message": notify_message},
                        blocking=False,
                    )
            except Exception:
                _LOGGER.exception("notify failed: %s", action)
