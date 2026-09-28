from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
import math
from typing import Any

from aiohttp import ClientTimeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .announce import async_announce, speech_text
from .const import (
    CONF_ACTIVITY_SENSOR,
    CONF_ADDR_SENSOR,
    CONF_AMAP_KEY,
    CONF_ANNOUNCE,
    CONF_BASE_SALARY,
    CONF_CLOCK_IN_END,
    CONF_CLOCK_IN_START,
    CONF_CLOCK_OUT_END,
    CONF_CLOCK_OUT_START,
    CONF_COMMUTE_DISTANCE,
    CONF_COMMUTE_SENSOR,
    CONF_COMMUTE_TIME,
    CONF_COMP_DEDUCT,
    CONF_COMP_THRESHOLD,
    CONF_DAILY_RESET,
    CONF_HOME_ZONES,
    CONF_HOLIDAY_SENSOR,
    CONF_HOLIDAY_WAGE,
    CONF_LUNCH_END,
    CONF_LUNCH_START,
    CONF_MONTHLY_RESET_DAY,
    CONF_NOTIFY,
    CONF_OVER_WAGE,
    CONF_OVERTIME_START,
    CONF_PERSON,
    CONF_STANDARD_HOURS,
    CONF_WORK_NOTIFY,
    CONF_WORK_ZONES,
    DEFAULT_BASE_SALARY,
    DEFAULT_CLOCK_IN_END,
    DEFAULT_CLOCK_IN_START,
    DEFAULT_CLOCK_OUT_END,
    DEFAULT_CLOCK_OUT_START,
    DEFAULT_COMP_DEDUCT,
    DEFAULT_COMP_THRESHOLD,
    DEFAULT_DAILY_RESET,
    DEFAULT_HOLIDAY_WAGE,
    DEFAULT_LUNCH_END,
    DEFAULT_LUNCH_START,
    DEFAULT_MONTHLY_RESET_DAY,
    DEFAULT_OVER_WAGE,
    DEFAULT_OVERTIME_START,
    DEFAULT_STANDARD_HOURS,
    DEFAULT_WORK_NOTIFY,
    DOMAIN,
    ACTIVITY_BIKE,
    ACTIVITY_DRIVE,
    TRAVEL_BICYCLING,
    TRAVEL_DISTANCE_KM,
    TRAVEL_DRIVING,
    HOLIDAY_VALUE,
    STATE_HOLIDAY,
    STATE_LUNCH,
    STATE_OFF,
    STATE_OVERTIME,
    STATE_REST,
    STATE_WORKING,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _parse_time(value: str | None) -> time:
    if not value:
        return time(0, 0, 0)
    parts = str(value).split(":")
    return time(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0)


def _in_window(now_t: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_t <= end
    return now_t >= start or now_t <= end


def _as_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


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


def _fmt_minutes(minutes: int, tr: dict[str, str]) -> str:
    if minutes <= 0:
        return _nget(tr, "zero_minutes", "0m")
    if minutes > 24 * 60:
        days = minutes // (24 * 60)
        rem = minutes % (24 * 60)
        return _nget(
            tr,
            "days_hours_minutes",
            "{days}d {hours}h {minutes}m",
            days=days,
            hours=rem // 60,
            minutes=rem % 60,
        )
    if minutes > 60:
        return _nget(
            tr,
            "hours_minutes",
            "{hours}h {minutes}m",
            hours=minutes // 60,
            minutes=minutes % 60,
        )
    return _nget(tr, "minutes", "{minutes}m", minutes=minutes)


def _fmt_km(km: float, tr: dict[str, str]) -> str:
    if abs(km - round(km)) < 0.05:
        return _nget(tr, "km_int", "{km} km", km=int(round(km)))
    return _nget(tr, "km_float", "{km} km", km=f"{km:.1f}")


_A = 6378245.0
_EE = 0.00669342162296594323


def _wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lon, lat
    x, y = lon - 105.0, lat - 35.0
    dlat = (
        -100.0
        + 2.0 * x
        + 3.0 * y
        + 0.2 * y * y
        + 0.1 * x * y
        + 0.2 * math.sqrt(abs(x))
    )
    dlat += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    dlat += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    dlat += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    dlon = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    dlon += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    dlon += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    dlon += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    rad = lat / 180.0 * math.pi
    magic = 1 - _EE * math.sin(rad) ** 2
    sqrtm = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtm) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrtm * math.cos(rad) * math.pi)
    return lon + dlon, lat + dlat


def _amap_num(value: Any) -> float | None:
    if value is None or value == [] or value == "" or isinstance(value, (bool, dict, list)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _amap_items(value: Any) -> list[Any]:
    if not value:
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _amap_first_path(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data or str(data.get("status")) != "1":
        return None
    route = data.get("route")
    if isinstance(route, list):
        route = route[0] if route else None
    if not isinstance(route, dict):
        return None
    paths = _amap_items(route.get("paths"))
    return paths[0] if paths else None


def _amap_path_meters_seconds(path: dict[str, Any]) -> tuple[float | None, int | None]:
    cost = path.get("cost") if isinstance(path.get("cost"), dict) else None
    duration = _amap_num((cost or {}).get("duration"))
    if duration is None:
        duration = _amap_num(path.get("duration"))
    if duration is None:
        total = 0.0
        found = False
        for step in _amap_items(path.get("steps")):
            sc = step.get("cost") if isinstance(step.get("cost"), dict) else None
            sec = _amap_num((sc or {}).get("duration"))
            if sec is None:
                sec = _amap_num(step.get("duration"))
            if sec is not None:
                total += sec
                found = True
        duration = total if found else None
    meters = _amap_num(path.get("distance"))
    if meters is None:
        total = 0.0
        found = False
        for step in _amap_items(path.get("steps")):
            step_m = _amap_num(step.get("step_distance"))
            if step_m is None:
                step_m = _amap_num(step.get("distance"))
            if step_m is not None:
                total += step_m
                found = True
        meters = total if found else None
    if meters is None:
        return None, None
    return meters, int(duration) if duration is not None else None


def _estimate_minutes(km: float, mode: str) -> int:
    if km <= 0:
        return 0
    speed = 40.0 if mode == TRAVEL_DRIVING else 15.0
    return max(int(km / speed * 60), 1)


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _latlon(state) -> tuple[float, float] | None:
    if not state:
        return None
    lat = state.attributes.get("latitude")
    lon = state.attributes.get("longitude")
    if lat is None or lon is None:
        return None
    return float(lon), float(lat)


def _seconds_between(start: time, end: time) -> float:
    s = datetime.combine(datetime.today(), start)
    e = datetime.combine(datetime.today(), end)
    diff = (e - s).total_seconds()
    if diff < 0:
        diff += 86400
    return diff


_HOUSEHOLD_CFG = {CONF_NOTIFY, CONF_AMAP_KEY, CONF_ANNOUNCE, CONF_HOLIDAY_SENSOR}


class WorkTimeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, person: dict[str, Any]
    ) -> None:
        self.entry = entry
        self.person = person
        name = person.get("name") or entry.title
        super().__init__(
            hass,
            _LOGGER,
            name=f"{entry.title} work {name}",
            update_interval=timedelta(seconds=60),
        )
        tracker = person.get(CONF_PERSON) or "unknown"
        slug = slugify(str(tracker).split(".", 1)[-1])
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.work.{slug}")
        self._data: dict[str, Any] = {
            "start_time": "00:00:00",
            "end_time": "00:00:00",
            "is_working": False,
            "comp_time": 0.0,
            "month_salary": 0.0,
            "last_reset_date": None,
            "last_month": None,
            "comp_accrued": False,
            "salary_accrued": False,
        }
        self._unsub: list[Any] = []
        self._amap_origin: tuple[float, float] | None = None
        self._amap_dest: tuple[float, float] | None = None
        self._amap_mode: str | None = None
        self._amap_loc: dict[str, Any] | None = None

    @property
    def person_id(self) -> str:
        return self.person.get(CONF_PERSON) or ""

    @property
    def person_name(self) -> str:
        return self.person.get("name") or self.entry.title

    @property
    def entity_prefix(self) -> str:
        slug = slugify(self.person_name or "")
        if slug:
            return slug
        person = self.cfg(CONF_PERSON) or ""
        if "." in person:
            return person.split(".", 1)[1]
        return slugify(self.entry.entry_id)[:8]

    def cfg(self, key: str, default: Any = None) -> Any:
        if key in _HOUSEHOLD_CFG:
            opts = self.entry.options
            if key in opts and opts[key] not in (None, ""):
                return opts[key]
            if (
                key == CONF_HOLIDAY_SENSOR
                and key in self.person
                and self.person[key] not in (None, "")
            ):
                return self.person[key]
            return default
        if key in self.person and self.person[key] not in (None, ""):
            return self.person[key]
        return default

    def update_person(self, person: dict[str, Any]) -> None:
        self.person = person

    async def async_setup(self) -> None:
        stored = await self.store.async_load()
        if stored:
            self._data.update(stored)
        await self._maybe_reset()
        tracker = self.cfg(CONF_PERSON)
        if tracker:
            self._unsub.append(
                async_track_state_change_event(self.hass, [tracker], self._on_tracker)
            )
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
        await self._sync_presence()

    async def _sync_presence(self) -> None:
        tracker = self.cfg(CONF_PERSON)
        if not tracker:
            return
        state = self.hass.states.get(tracker)
        if not state or state.state in ("unknown", "unavailable"):
            return
        in_company = self._in_company(state.state)
        working = bool(self._data.get("is_working"))
        if in_company and not working:
            await self.async_clock_in()
        elif not in_company and working:
            await self.async_clock_out()

    async def async_shutdown(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        await self.store.async_save(self._data)

    async def _save(self) -> None:
        await self.store.async_save(self._data)
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        if await self._maybe_reset():
            await self.store.async_save(self._data)
        return self._computed()

    def _computed(self) -> dict[str, Any]:
        duration = self._calc_duration()
        std = float(self.cfg(CONF_STANDARD_HOURS, DEFAULT_STANDARD_HOURS))
        overtime = round(max(duration - std, 0), 2)
        return {
            **self._data,
            "duration": duration,
            "work_time": round(min(duration, std), 2),
            "over_time": overtime,
            "work_state": self._calc_state(duration, overtime),
        }

    def _zone_names(self) -> set[str]:
        names: set[str] = set()
        for zid in _as_list(self.cfg(CONF_WORK_ZONES, [])):
            state = self.hass.states.get(zid)
            names.add(zid.split(".", 1)[-1])
            if not state:
                continue
            names.add(state.name)
            fn = state.attributes.get("friendly_name")
            if fn:
                names.add(fn)
            zn = state.attributes.get("name")
            if zn:
                names.add(zn)
        names.discard("")
        names.discard("unknown")
        names.discard("unavailable")
        return names

    def _in_company(self, tracker_state: str | None) -> bool:
        if not tracker_state:
            return False
        return tracker_state in self._zone_names()

    def _home_zone_names(self) -> set[str]:
        names: set[str] = set()
        for zid in _as_list(self.cfg(CONF_HOME_ZONES, [])):
            state = self.hass.states.get(zid)
            names.add(zid.split(".", 1)[-1])
            if not state:
                continue
            names.add(state.name)
            fn = state.attributes.get("friendly_name")
            if fn:
                names.add(fn)
            zn = state.attributes.get("name")
            if zn:
                names.add(zn)
        names.discard("")
        names.discard("unknown")
        names.discard("unavailable")
        return names

    def _in_home(self) -> bool:
        tracker = self.cfg(CONF_PERSON)
        zones = _as_list(self.cfg(CONF_HOME_ZONES, []))
        if not tracker or not zones:
            return False
        state = self.hass.states.get(tracker)
        if not state or state.state in ("unknown", "unavailable"):
            return False
        return state.state in self._home_zone_names()

    def _home_zones_lnglat(self) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for zid in _as_list(self.cfg(CONF_HOME_ZONES, [])):
            loc = _latlon(self.hass.states.get(zid))
            if loc:
                out.append(loc)
        return out

    def _home_lnglat(
        self, origin: tuple[float, float] | None = None
    ) -> tuple[float, float] | None:
        zones = self._home_zones_lnglat()
        if not zones:
            loc = _latlon(self.hass.states.get("zone.home"))
            if loc:
                zones = [loc]
            else:
                lat = self.hass.config.latitude
                lon = self.hass.config.longitude
                if lat is not None and lon is not None:
                    zones = [(float(lon), float(lat))]
        if not zones:
            return None
        if origin is None:
            return zones[0]
        return min(
            zones,
            key=lambda z: _haversine_km(origin[0], origin[1], z[0], z[1]),
        )

    def _near_home(self, origin: tuple[float, float]) -> bool:
        return any(
            _haversine_km(origin[0], origin[1], z[0], z[1]) <= 0.4
            for z in self._home_zones_lnglat()
        )

    def _is_at_home(self, origin: tuple[float, float] | None) -> bool:
        if self._in_home():
            return True
        if origin is not None and self._near_home(origin):
            return True
        return False

    def _is_holiday(self) -> bool:
        entity_id = self.cfg(CONF_HOLIDAY_SENSOR)
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return state.state in (HOLIDAY_VALUE, STATE_HOLIDAY)

    def _calc_duration(self) -> float:
        start_s = self._data.get("start_time") or "00:00:00"
        end_s = self._data.get("end_time") or "00:00:00"
        if start_s in ("unknown", "00:00:00"):
            return 0.0
        start = _parse_time(start_s)
        if end_s in ("unknown", "00:00:00"):
            end = dt_util.now().time().replace(microsecond=0)
        else:
            end = _parse_time(end_s)
        lunch_start = _parse_time(self.cfg(CONF_LUNCH_START, DEFAULT_LUNCH_START))
        lunch_end = _parse_time(self.cfg(CONF_LUNCH_END, DEFAULT_LUNCH_END))
        diff = _seconds_between(start, end)
        today = dt_util.now().date()
        ws = datetime.combine(today, start)
        we = datetime.combine(today, end)
        if we < ws:
            we += timedelta(days=1)
        ls = datetime.combine(today, lunch_start)
        le = datetime.combine(today, lunch_end)
        ov_s = max(ws, ls)
        ov_e = min(we, le)
        lunch_ov = (ov_e - ov_s).total_seconds() if ov_e > ov_s else 0
        return round(max(diff - lunch_ov, 0) / 3600, 2)

    def _calc_state(self, duration: float, overtime: float) -> str:
        if self._is_holiday():
            return STATE_HOLIDAY
        if duration == 0:
            return STATE_REST
        if not self._data.get("is_working"):
            return STATE_OFF
        now_t = dt_util.now().time().replace(microsecond=0)
        lunch_start = _parse_time(self.cfg(CONF_LUNCH_START, DEFAULT_LUNCH_START))
        lunch_end = _parse_time(self.cfg(CONF_LUNCH_END, DEFAULT_LUNCH_END))
        ot_start = _parse_time(self.cfg(CONF_OVERTIME_START, DEFAULT_OVERTIME_START))
        end_s = self._data.get("end_time") or "00:00:00"
        if lunch_start <= now_t < lunch_end:
            return STATE_LUNCH
        if overtime > 0 and now_t >= ot_start and end_s in ("unknown", "00:00:00"):
            return STATE_OVERTIME
        return STATE_WORKING

    def _accrue(self) -> None:
        duration = self._calc_duration()
        std = float(self.cfg(CONF_STANDARD_HOURS, DEFAULT_STANDARD_HOURS))
        overtime = max(duration - std, 0)
        threshold = float(self.cfg(CONF_COMP_THRESHOLD, DEFAULT_COMP_THRESHOLD))
        deduct = float(self.cfg(CONF_COMP_DEDUCT, DEFAULT_COMP_DEDUCT))
        if not self._data.get("comp_accrued") and overtime > threshold:
            self._data["comp_time"] = round(
                float(self._data.get("comp_time", 0)) + max(overtime - deduct, 0), 2
            )
            self._data["comp_accrued"] = True
        if not self._data.get("salary_accrued"):
            if self._is_holiday():
                pay = duration * float(self.cfg(CONF_HOLIDAY_WAGE, DEFAULT_HOLIDAY_WAGE))
            else:
                pay = self._base_salary() + overtime * float(
                    self.cfg(CONF_OVER_WAGE, DEFAULT_OVER_WAGE)
                )
            self._data["month_salary"] = round(
                float(self._data.get("month_salary", 0)) + pay, 2
            )
            self._data["salary_accrued"] = True

    def _do_daily_reset(self) -> None:
        now = dt_util.now()
        if self._data.get("is_working"):
            self._data["end_time"] = now.strftime("%H:%M:%S")
            self._accrue()
            self._data["start_time"] = now.strftime("%H:%M:%S")
            self._data["end_time"] = "00:00:00"
            self._data["comp_accrued"] = False
            self._data["salary_accrued"] = False
            return
        self._data["start_time"] = "00:00:00"
        self._data["end_time"] = "00:00:00"
        self._data["is_working"] = False
        self._data["comp_accrued"] = False
        self._data["salary_accrued"] = False

    def _base_salary(self) -> float:
        return float(self.cfg(CONF_BASE_SALARY, DEFAULT_BASE_SALARY))

    def _do_monthly_reset(self) -> None:
        self._data["comp_time"] = 0.0
        self._data["month_salary"] = 0.0

    async def _maybe_reset(self) -> bool:
        now = dt_util.now()
        today = now.date().isoformat()
        month_key = now.strftime("%Y-%m")
        changed = False
        last = self._data.get("last_reset_date")
        if last is None:
            self._data["last_reset_date"] = today
            self._data["last_month"] = month_key
            return True
        reset_day = int(self.cfg(CONF_MONTHLY_RESET_DAY, DEFAULT_MONTHLY_RESET_DAY))
        if self._data.get("last_month") != month_key and now.day >= reset_day:
            self._do_monthly_reset()
            self._data["last_month"] = month_key
            changed = True
        if last != today:
            reset_t = _parse_time(self.cfg(CONF_DAILY_RESET, DEFAULT_DAILY_RESET))
            try:
                last_date = datetime.strptime(last, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                last_date = now.date()
            days_gap = (now.date() - last_date).days
            past_reset = now.time().replace(microsecond=0) >= reset_t
            if past_reset or days_gap > 1:
                self._do_daily_reset()
                self._data["last_reset_date"] = today
                changed = True
        return changed

    @callback
    def _on_reset(self, now: datetime) -> None:
        self.hass.async_create_task(self._async_on_reset(now))

    async def _async_on_reset(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self._data.get("last_reset_date") == today:
            return
        reset_day = int(self.cfg(CONF_MONTHLY_RESET_DAY, DEFAULT_MONTHLY_RESET_DAY))
        month_key = now.strftime("%Y-%m")
        if self._data.get("last_month") != month_key and now.day >= reset_day:
            self._do_monthly_reset()
            self._data["last_month"] = month_key
        self._do_daily_reset()
        self._data["last_reset_date"] = today
        await self._save()

    async def _on_tracker(self, event: Event) -> None:
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if new is None or new.state in ("unknown", "unavailable"):
            return
        if old is not None and old.state in ("unknown", "unavailable"):
            return
        was_in = old is not None and self._in_company(old.state)
        now_in = self._in_company(new.state)
        if now_in and not was_in:
            await self.async_clock_in()
        elif was_in and not now_in:
            await self.async_clock_out()

    async def async_clock_in(self) -> None:
        if self._data.get("is_working"):
            return
        now = dt_util.now()
        if not _in_window(
            now.time().replace(microsecond=0),
            _parse_time(self.cfg(CONF_CLOCK_IN_START, DEFAULT_CLOCK_IN_START)),
            _parse_time(self.cfg(CONF_CLOCK_IN_END, DEFAULT_CLOCK_IN_END)),
        ):
            return
        self._data["is_working"] = True
        self._data["start_time"] = now.strftime("%H:%M:%S")
        self._data["end_time"] = "00:00:00"
        await self._save()
        await self._after_clock(True)

    async def async_clock_out(self, *, force: bool = False) -> None:
        if not self._data.get("is_working"):
            return
        now = dt_util.now()
        if not force and not _in_window(
            now.time().replace(microsecond=0),
            _parse_time(self.cfg(CONF_CLOCK_OUT_START, DEFAULT_CLOCK_OUT_START)),
            _parse_time(self.cfg(CONF_CLOCK_OUT_END, DEFAULT_CLOCK_OUT_END)),
        ):
            return
        self._data["is_working"] = False
        self._data["end_time"] = now.strftime("%H:%M:%S")
        self._accrue()
        await self._save()
        await self._after_clock(False)

    async def async_set_working(self, on: bool) -> None:
        was = bool(self._data.get("is_working"))
        now = dt_util.now()
        if on:
            self._data["is_working"] = True
            if not was or self._data.get("start_time") in (None, "unknown", "00:00:00"):
                self._data["start_time"] = now.strftime("%H:%M:%S")
            self._data["end_time"] = "00:00:00"
        else:
            self._data["is_working"] = False
            if self._data.get("end_time") in (None, "unknown", "00:00:00"):
                self._data["end_time"] = now.strftime("%H:%M:%S")
            self._accrue()
        await self._save()
        if was != on:
            await self._after_clock(on)

    async def _after_clock(self, clock_in: bool) -> None:
        notify_on = self.cfg(CONF_WORK_NOTIFY, DEFAULT_WORK_NOTIFY)
        has_loc = any(
            self.cfg(k)
            for k in (
                CONF_ADDR_SENSOR,
                CONF_COMMUTE_SENSOR,
                CONF_COMMUTE_DISTANCE,
                CONF_COMMUTE_TIME,
            )
        )
        if not notify_on and not has_loc:
            return
        loc = await self._refresh_location()
        if not notify_on:
            return
        tr = await async_get_translations(
            self.hass, self.hass.config.language, "common", {DOMAIN}
        )
        unknown = _nget(tr, "unknown", "unknown")
        title = _nget(
            tr,
            "clock_in_title" if clock_in else "clock_out_title",
            "{name} clock-in" if clock_in else "{name} clock-out",
            name=self.person_name,
        )
        now_s = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
        dist = _fmt_km(loc["distance"], tr) if loc["distance"] is not None else unknown
        time_s = (
            _fmt_minutes(loc["time"], tr) if loc["time"] is not None else unknown
        )
        if clock_in:
            message = _nget(
                tr,
                "clock_in_message",
                "Distance from home: {dist}\nTravel time: {time}\nLocation: {addr}\nTime: {now}",
                dist=dist,
                time=time_s,
                addr=loc["addr"],
                now=now_s,
            )
        else:
            data = self._computed()
            message = _nget(
                tr,
                "clock_out_message",
                "Overtime: {over_time} h\nComp time: {comp_time} h\nLocation: {addr}\nTime: {now}",
                over_time=data["over_time"],
                comp_time=data["comp_time"],
                addr=loc["addr"],
                now=now_s,
            )
        body = message.replace("\\n", "\n").strip()
        await self._send_notify(title, body)
        await self._broadcast(speech_text(title, body))

    def _person_lnglat(self) -> tuple[float, float] | None:
        eid = self.cfg(CONF_PERSON)
        if not eid:
            return None
        state = self.hass.states.get(eid)
        loc = _latlon(state)
        if loc:
            return loc
        if not state:
            return None
        source = state.attributes.get("source")
        trackers = state.attributes.get("device_trackers") or []
        ids = []
        if isinstance(source, str):
            ids.append(source)
        if isinstance(trackers, str):
            ids.append(trackers)
        else:
            ids.extend(trackers)
        for tid in ids:
            if isinstance(tid, str) and "." in tid:
                loc = _latlon(self.hass.states.get(tid))
                if loc:
                    return loc
        return None

    def _travel_mode(
        self, origin: tuple[float, float], dest: tuple[float, float]
    ) -> str:
        km = _haversine_km(origin[0], origin[1], dest[0], dest[1])
        if km > TRAVEL_DISTANCE_KM:
            return TRAVEL_DRIVING
        eid = self.cfg(CONF_ACTIVITY_SENSOR)
        if eid:
            state = self.hass.states.get(eid)
            val = state.state if state else None
            if val in ACTIVITY_BIKE:
                return TRAVEL_BICYCLING
            if val in ACTIVITY_DRIVE:
                return TRAVEL_DRIVING
        return TRAVEL_BICYCLING

    async def _amap_get(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, params=params, timeout=ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                return data if isinstance(data, dict) else None
        except Exception:
            _LOGGER.warning("amap request failed: %s", url)
            return None

    async def _amap_route(
        self,
        key: str,
        mode: str,
        src: tuple[float, float],
        dst: tuple[float, float],
    ) -> tuple[float, int] | None:
        endpoint = (
            "https://restapi.amap.com/v5/direction/driving"
            if mode == TRAVEL_DRIVING
            else "https://restapi.amap.com/v5/direction/electrobike"
        )
        route = await self._amap_get(
            endpoint,
            {
                "key": key,
                "origin": f"{src[0]:.6f},{src[1]:.6f}",
                "destination": f"{dst[0]:.6f},{dst[1]:.6f}",
                "show_fields": "cost",
            },
        )
        path = _amap_first_path(route)
        if not path:
            return None
        meters, seconds = _amap_path_meters_seconds(path)
        if meters is None or meters <= 0:
            return None
        if seconds is None or seconds <= 0:
            seconds = _estimate_minutes(meters / 1000.0, mode) * 60
        return meters, seconds

    async def _refresh_location(self) -> dict[str, Any]:
        tr = await async_get_translations(
            self.hass, self.hass.config.language, "common", {DOMAIN}
        )
        unknown = _nget(tr, "unknown", "unknown")
        no_commute = _nget(tr, "no_commute", "no commute")
        origin = self._person_lnglat()
        if self._is_at_home(origin):
            loc = {
                "addr": unknown,
                "distance": 0,
                "time": 0,
                "commute": no_commute,
            }
            key = self.cfg(CONF_AMAP_KEY)
            if key and origin:
                src = _wgs84_to_gcj02(*origin)
                regeo = await self._amap_get(
                    "https://restapi.amap.com/v3/geocode/regeo",
                    {"key": key, "location": f"{src[0]:.6f},{src[1]:.6f}"},
                )
                if regeo and str(regeo.get("status")) == "1":
                    addr = (regeo.get("regeocode") or {}).get("formatted_address")
                    if addr and not isinstance(addr, list):
                        loc["addr"] = addr
            self._amap_origin = origin
            self._amap_dest = self._home_lnglat(origin)
            self._amap_mode = None
            self._amap_loc = loc
            await self._write_loc(loc)
            return loc
        loc = {"addr": unknown, "distance": None, "time": None, "commute": unknown}
        key = self.cfg(CONF_AMAP_KEY)
        if not key or not origin:
            await self._write_loc(loc)
            return loc
        dest = self._home_lnglat(origin)
        mode = self._travel_mode(origin, dest) if dest else None
        if (
            self._amap_loc is not None
            and self._amap_origin is not None
            and _haversine_km(
                origin[0], origin[1], self._amap_origin[0], self._amap_origin[1]
            )
            <= 0.4
            and dest == self._amap_dest
            and mode == self._amap_mode
        ):
            await self._write_loc(self._amap_loc)
            return self._amap_loc
        src = _wgs84_to_gcj02(*origin)
        regeo = await self._amap_get(
            "https://restapi.amap.com/v3/geocode/regeo",
            {"key": key, "location": f"{src[0]:.6f},{src[1]:.6f}"},
        )
        if regeo and str(regeo.get("status")) == "1":
            addr = (regeo.get("regeocode") or {}).get("formatted_address")
            if addr and not isinstance(addr, list):
                loc["addr"] = addr
        if dest:
            dst = _wgs84_to_gcj02(*dest)
            route_mode = mode or TRAVEL_DRIVING
            result = await self._amap_route(key, route_mode, src, dst)
            if result:
                meters, seconds = result
                km = int(meters / 10) / 100
                if km <= 0:
                    km = round(meters / 1000.0, 2)
                minutes = max(int(seconds / 60), 0)
            else:
                km = round(_haversine_km(origin[0], origin[1], dest[0], dest[1]) * 1.3, 1)
                minutes = _estimate_minutes(km, route_mode)
            if km > 0:
                loc["distance"] = km
                loc["time"] = minutes
                loc["commute"] = _nget(
                    tr,
                    "commute",
                    "Home distance: {dist} Travel time: {time}",
                    dist=_fmt_km(km, tr),
                    time=_fmt_minutes(minutes, tr),
                )
                mode = route_mode
        if loc["addr"] != unknown and loc["distance"] is not None:
            self._amap_origin = origin
            self._amap_dest = dest
            self._amap_mode = mode
            self._amap_loc = loc
        await self._write_loc(loc)
        return loc

    def _first_entity(self, key: str) -> str | None:
        val = self.cfg(key)
        items = _as_list(val)
        return items[0] if items else None

    async def _write_loc(self, loc: dict[str, Any]) -> None:
        await self._write_entity(
            self._first_entity(CONF_ADDR_SENSOR), loc["addr"] or "unknown", "address"
        )
        await self._write_entity(
            self._first_entity(CONF_COMMUTE_SENSOR), loc["commute"] or "unknown", "info"
        )
        dist = loc["distance"]
        await self._write_entity(
            self._first_entity(CONF_COMMUTE_DISTANCE),
            dist if dist is not None else "unknown",
            "distance",
        )
        mins = loc["time"]
        if mins is not None:
            tr = await async_get_translations(
                self.hass, self.hass.config.language, "common", {DOMAIN}
            )
            time_val = _fmt_minutes(mins, tr)
        else:
            time_val = "unknown"
        await self._write_entity(
            self._first_entity(CONF_COMMUTE_TIME),
            time_val,
            "time",
        )

    def _sensor_entity(self, entity_id: str):
        domain = entity_id.split(".", 1)[0]
        store = self.hass.data.get("entity_components")
        candidates = []
        if isinstance(store, dict):
            candidates.append(store.get(domain))
        candidates.append(self.hass.data.get(domain))
        for component in candidates:
            if component is None:
                continue
            getter = getattr(component, "get_entity", None)
            if getter:
                entity = getter(entity_id)
                if entity:
                    return entity
            entities = getattr(component, "entities", None)
            get_item = getattr(entities, "get", None) if entities is not None else None
            if get_item:
                entity = get_item(entity_id)
                if entity:
                    return entity
        platforms = self.hass.data.get("entity_platform") or {}
        if isinstance(platforms, dict):
            for plat_list in platforms.values():
                if not isinstance(plat_list, (list, tuple)):
                    continue
                for platform in plat_list:
                    entities = getattr(platform, "entities", None)
                    if isinstance(entities, dict) and entity_id in entities:
                        return entities[entity_id]
        return None

    def _restore_device(self, entity, kind: str | None):
        device = getattr(entity, "_device", None) if entity else None
        if device is None or isinstance(device, str) or not kind:
            return None
        names = {
            "address": "restore_location_address",
            "distance": "restore_commute_distance",
            "time": "restore_commute_time",
            "info": "restore_commute_info",
        }
        name = names.get(kind)
        if name and hasattr(device, name):
            return device
        return None

    async def _write_entity(
        self, entity_id: str | None, value: Any, kind: str | None = None
    ) -> None:
        if not entity_id or not isinstance(entity_id, str):
            return
        if value in (None, ""):
            value = "unknown"
        try:
            entity = self._sensor_entity(entity_id)
            device = self._restore_device(entity, kind)
            if device is not None:
                if value == "unknown":
                    if kind == "address":
                        device._location_address = None
                    elif kind == "distance":
                        device._commute_distance = None
                    elif kind == "time":
                        device._commute_time = None
                    elif kind == "info":
                        device._commute_info = None
                elif kind == "address":
                    device.restore_location_address(value)
                elif kind == "distance":
                    device.restore_commute_distance(value)
                elif kind == "time":
                    device.restore_commute_time(value)
                elif kind == "info":
                    device.restore_commute_info(value)
                entity.async_write_ha_state()
                return
            domain = entity_id.split(".", 1)[0]
            if domain in ("input_text", "text"):
                await self.hass.services.async_call(
                    domain, "set_value", {"entity_id": entity_id, "value": str(value)}, blocking=False
                )
                return
            if domain == "input_number":
                if value == "unknown":
                    return
                await self.hass.services.async_call(
                    domain, "set_value", {"entity_id": entity_id, "value": float(value)}, blocking=False
                )
                return
            old = self.hass.states.get(entity_id)
            attrs = dict(old.attributes) if old else {}
            self.hass.states.async_set(entity_id, value, attrs)
        except Exception:
            _LOGGER.exception("write entity failed: %s", entity_id)

    async def _send_notify(self, title: str, message: str) -> None:
        raw = self.cfg(CONF_NOTIFY)
        if not raw:
            return
        message = str(message).replace("\\n", "\n").strip()
        if isinstance(raw, (str, dict)):
            items = [raw]
        else:
            items = list(raw)
        for item in items:
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
            data["message"] = message
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
                        {"entity_id": action, "title": title, "message": message},
                        blocking=False,
                    )
            except Exception:
                _LOGGER.exception("notify failed: %s", action)

    async def _broadcast(self, text: str) -> None:
        await async_announce(self.hass, self.cfg(CONF_ANNOUNCE), text)

    async def async_set_start_time(self, value: str) -> None:
        self._data["start_time"] = value
        await self._save()

    async def async_set_end_time(self, value: str) -> None:
        self._data["end_time"] = value
        await self._save()

    async def async_set_comp_time(self, value: float) -> None:
        self._data["comp_time"] = round(value, 2)
        await self._save()

    async def async_set_month_salary(self, value: float) -> None:
        self._data["month_salary"] = round(value, 2)
        await self._save()
