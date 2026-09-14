from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
import math
from typing import Any

from aiohttp import ClientTimeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.const import UnitOfLength
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .localize import tr

from .const import (
    ACTIVITY_AWAY,
    ACTIVITY_BIKE,
    ACTIVITY_COMPANY,
    ACTIVITY_DRIVE,
    ACTIVITY_HOME,
    ACTIVITY_OUT,
    COMMUTE_BIKE_MAX_M,
    CONF_ACTIVITY_SENSOR,
    CONF_ADDR_SENSOR,
    CONF_AMAP_KEY,
    CONF_ANNOUNCE,
    CONF_COMMUTE_DISTANCE,
    CONF_COMMUTE_SENSOR,
    CONF_COMMUTE_TIME,
    CONF_AREA_LAT_MAX,
    CONF_AREA_LAT_MIN,
    CONF_AREA_LON_MAX,
    CONF_AREA_LON_MIN,
    CONF_ARRIVE_END,
    CONF_ARRIVE_START,
    CONF_DAILY_RESET,
    CONF_HOME_ZONES,
    CONF_INDOOR_SENSOR,
    CONF_LEAVE_END,
    CONF_LEAVE_START,
    CONF_NOTIFY,
    CONF_NOTIFY_ARRIVE,
    CONF_NOTIFY_LEAVE,
    CONF_NOTIFY_STATION_ENTER,
    CONF_NOTIFY_STATION_LEAVE,
    CONF_PEOPLE,
    CONF_PERSON,
    CONF_RESET_HOME_DURATION,
    CONF_STATION_ENTER_ZONES,
    CONF_STATION_LEAVE_ZONES,
    CONF_TOTAL_PEOPLE,
    CONF_WORK_ZONES,
    DEFAULT_AREA_LAT_MAX,
    DEFAULT_AREA_LAT_MIN,
    DEFAULT_AREA_LON_MAX,
    DEFAULT_AREA_LON_MIN,
    DEFAULT_ARRIVE_END,
    DEFAULT_ARRIVE_START,
    DEFAULT_DAILY_RESET,
    DEFAULT_LEAVE_END,
    DEFAULT_LEAVE_START,
    DEFAULT_NOTIFY_ARRIVE,
    DEFAULT_NOTIFY_LEAVE,
    DEFAULT_NOTIFY_STATION_ENTER,
    DEFAULT_NOTIFY_STATION_LEAVE,
    DEFAULT_RESET_HOME_DURATION,
    DEFAULT_TOTAL_PEOPLE,
    DOMAIN,
    MODE_BICYCLING,
    MODE_DRIVING,
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


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _notify_items(raw: Any) -> list[Any]:
    if not raw:
        return []
    if isinstance(raw, (str, dict)):
        return [raw]
    return list(raw)


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


def _meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(
        math.radians(lon2 - lon1) / 2
    ) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(a)))


def _coord(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def person_switch_id(person: dict[str, Any]) -> str:
    slug = slugify(person.get("name") or "")
    if slug:
        return f"{slug}_home"
    tracker = person.get(CONF_PERSON) or ""
    if "." in tracker:
        return f"{tracker.split('.', 1)[1]}_home"
    return "home"


def person_activity_id(person: dict[str, Any]) -> str:
    slug = slugify(person.get("name") or "")
    if slug:
        return f"{slug}_activity"
    tracker = person.get(CONF_PERSON) or ""
    if "." in tracker:
        return f"{tracker.split('.', 1)[1]}_activity"
    return "activity"


def _fmt_minutes(hass: HomeAssistant, minutes: int) -> str:
    if minutes > 24 * 60:
        days = minutes // (24 * 60)
        rem = minutes % (24 * 60)
        return tr(
            hass,
            "days_hours_minutes",
            days=days,
            hours=rem // 60,
            minutes=rem % 60,
        )
    if minutes > 60:
        return tr(hass, "hours_minutes", hours=minutes // 60, minutes=minutes % 60)
    return tr(hass, "minutes", minutes=minutes)


def person_duration_id(person: dict[str, Any]) -> str:
    slug = slugify(person.get("name") or "")
    if slug:
        return f"{slug}_home_duration"
    tracker = person.get(CONF_PERSON) or ""
    if "." in tracker:
        return f"{tracker.split('.', 1)[1]}_home_duration"
    return "home_duration"


class HomeTimeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            update_interval=timedelta(seconds=60),
        )
        self.entry = entry
        self.store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._data: dict[str, Any] = {"away": {}, "home_duration": {}}
        self._geo_cache: dict[str, dict[str, Any]] = {}
        self._unsub: list[Any] = []

    @property
    def household_name(self) -> str:
        return self.entry.data.get("name", self.entry.title)

    @property
    def people(self) -> list[dict[str, Any]]:
        return list(self.cfg(CONF_PEOPLE, []) or [])

    def cfg(self, key: str, default: Any = None) -> Any:
        if key in self.entry.options:
            return self.entry.options[key]
        return self.entry.data.get(key, default)

    def person_cfg(
        self, person: dict[str, Any] | None, key: str, default: Any = None
    ) -> Any:
        if person and key in person and person[key] not in (None, ""):
            return person[key]
        return self.cfg(key, default)

    async def async_setup(self) -> None:
        stored = await self.store.async_load()
        if stored:
            self._data.update(stored)
        valid = {p.get(CONF_PERSON) for p in self.people if p.get(CONF_PERSON)}
        away = {
            k: v
            for k, v in dict(self._data.get("away") or {}).items()
            if k in valid
        }
        for tracker in valid:
            away.setdefault(tracker, False)
        self._data["away"] = away
        duration = {
            k: v
            for k, v in dict(self._data.get("home_duration") or {}).items()
            if k in valid
        }
        self._data["home_duration"] = duration
        self._sync_away()
        self._maybe_reset_duration()
        self._sync_home_sessions()
        entities = [p[CONF_PERSON] for p in self.people if p.get(CONF_PERSON)]
        entities.extend(_as_list(self.cfg(CONF_INDOOR_SENSOR)))
        if entities:
            self._unsub.append(
                async_track_state_change_event(self.hass, entities, self._on_state)
            )
        await self.async_config_entry_first_refresh()

    async def async_shutdown(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        await self.store.async_save(self._data)

    async def _save(self) -> None:
        await self.store.async_save(self._data)
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        if self._maybe_reset_duration():
            await self.store.async_save(self._data)
        return self._computed()

    def _zone_names(self, zone_ids: list[str]) -> set[str]:
        names: set[str] = set()
        for zid in zone_ids:
            names.add(zid.split(".", 1)[-1])
            state = self.hass.states.get(zid)
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

    def _in_zones(self, tracker_id: str, zone_ids: list[str]) -> bool:
        if not zone_ids:
            return False
        state = self.hass.states.get(tracker_id)
        if not state or state.state in ("unknown", "unavailable"):
            return False
        return state.state in self._zone_names(zone_ids)

    def _outside_area(
        self, tracker_id: str, person: dict[str, Any] | None = None
    ) -> bool:
        state = self.hass.states.get(tracker_id)
        if not state:
            return False
        lat = _coord(state.attributes.get("latitude"))
        lon = _coord(state.attributes.get("longitude"))
        if lat is None or lon is None:
            return False
        if person is None:
            person = self._person_by_tracker(tracker_id)
        lat_min = float(
            self.person_cfg(person, CONF_AREA_LAT_MIN, DEFAULT_AREA_LAT_MIN)
        )
        lat_max = float(
            self.person_cfg(person, CONF_AREA_LAT_MAX, DEFAULT_AREA_LAT_MAX)
        )
        lon_min = float(
            self.person_cfg(person, CONF_AREA_LON_MIN, DEFAULT_AREA_LON_MIN)
        )
        lon_max = float(
            self.person_cfg(person, CONF_AREA_LON_MAX, DEFAULT_AREA_LON_MAX)
        )
        return not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max)

    def _activity(self, tracker_id: str, person: dict[str, Any]) -> str:
        if self._in_zones(tracker_id, _as_list(person.get(CONF_HOME_ZONES))):
            return ACTIVITY_HOME
        if self._in_zones(tracker_id, _as_list(person.get(CONF_WORK_ZONES))):
            return ACTIVITY_COMPANY
        if self._outside_area(tracker_id, person):
            return ACTIVITY_AWAY
        return ACTIVITY_OUT

    def _indoor_count(self) -> int | None:
        entity_ids = _as_list(self.cfg(CONF_INDOOR_SENSOR))
        if not entity_ids:
            return None
        total = 0
        found = False
        for entity_id in entity_ids:
            state = self.hass.states.get(entity_id)
            if not state or state.state in ("unknown", "unavailable"):
                continue
            try:
                total += int(float(state.state))
                found = True
            except (TypeError, ValueError):
                continue
        return total if found else None

    def _person_by_tracker(self, tracker_id: str) -> dict[str, Any] | None:
        for person in self.people:
            if person.get(CONF_PERSON) == tracker_id:
                return person
        return None

    def _computed(self) -> dict[str, Any]:
        home = 0
        comp = 0
        outside = 0
        activity: dict[str, str] = {}
        for person in self.people:
            tracker = person.get(CONF_PERSON)
            if not tracker:
                continue
            home_zones = _as_list(person.get(CONF_HOME_ZONES))
            work_zones = _as_list(person.get(CONF_WORK_ZONES))
            if self._in_zones(tracker, home_zones):
                home += 1
            if self._in_zones(tracker, work_zones):
                comp += 1
            if self._outside_area(tracker, person):
                outside += 1
            activity[tracker] = self._activity(tracker, person)
        waidi = max(0, outside - comp)
        indoor = self._indoor_count()
        if indoor is not None:
            home = indoor
        total = int(self.cfg(CONF_TOTAL_PEOPLE, DEFAULT_TOTAL_PEOPLE))
        durations = {
            p[CONF_PERSON]: self._calc_duration(p[CONF_PERSON])
            for p in self.people
            if p.get(CONF_PERSON)
        }
        return {
            **self._data,
            "home_count": home,
            "comp_count": comp,
            "waidi_count": waidi,
            "out_count": abs(total - home - waidi - comp),
            "activity": activity,
            "home_durations": durations,
        }

    @callback
    def _on_state(self, event: Event) -> None:
        self.hass.async_create_task(self._async_on_state(event))

    def _zone_label(self, zone_state: str, zone_ids: list[str]) -> str:
        for zid in zone_ids:
            state = self.hass.states.get(zid)
            if not state:
                continue
            aliases = {
                zid.split(".", 1)[-1],
                state.name,
                state.state,
                state.attributes.get("friendly_name"),
                state.attributes.get("name"),
            }
            if zone_state in {n for n in aliases if n}:
                return state.name or zone_state
        return zone_state

    def _zone_crossed(
        self, event: Event, zone_ids: list[str]
    ) -> tuple[bool | None, str]:
        if not zone_ids:
            return None, ""
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if new is None or new.state in ("unknown", "unavailable"):
            return None, ""
        names = self._zone_names(zone_ids)
        was_in = (
            old is not None
            and old.state not in ("unknown", "unavailable")
            and old.state in names
        )
        now_in = new.state in names
        if was_in == now_in:
            return None, ""
        label = self._zone_label(new.state if now_in else old.state, zone_ids)
        return now_in, label

    async def _async_on_state(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        person = self._person_by_tracker(entity_id) if entity_id else None
        if person:
            enter_in, enter_label = self._zone_crossed(
                event,
                _as_list(
                    self.person_cfg(person, CONF_STATION_ENTER_ZONES)
                ),
            )
            if enter_in is True:
                await self._async_notify_station(entity_id, True, enter_label)
            leave_in, leave_label = self._zone_crossed(
                event,
                _as_list(
                    self.person_cfg(person, CONF_STATION_LEAVE_ZONES)
                ),
            )
            if leave_in is False:
                await self._async_notify_station(entity_id, False, leave_label)
            home_zones = _as_list(person.get(CONF_HOME_ZONES))
            if home_zones:
                home_in, _ = self._zone_crossed(event, home_zones)
                if home_in is not None:
                    await self.async_set_away(entity_id, not home_in, notify=True)
                    return
        await self.async_request_refresh()

    def is_away(self, tracker_id: str) -> bool:
        return bool((self.data or self._data).get("away", {}).get(tracker_id))

    def activity(self, tracker_id: str) -> str:
        return (self.data or {}).get("activity", {}).get(tracker_id, ACTIVITY_OUT)

    def home_duration(self, tracker_id: str) -> float:
        return float((self.data or {}).get("home_durations", {}).get(tracker_id, 0))

    def _duration_rec(self, tracker_id: str) -> dict[str, Any]:
        durations = dict(self._data.get("home_duration") or {})
        rec = dict(durations.get(tracker_id) or {})
        rec.setdefault("elapsed", 0.0)
        rec.setdefault("start", None)
        rec.setdefault("reset_date", None)
        durations[tracker_id] = rec
        self._data["home_duration"] = durations
        return rec

    def _calc_duration(self, tracker_id: str) -> float:
        rec = (self._data.get("home_duration") or {}).get(tracker_id) or {}
        elapsed = float(rec.get("elapsed") or 0)
        start = rec.get("start")
        if start:
            start_dt = dt_util.parse_datetime(start)
            if start_dt is not None:
                elapsed += (dt_util.now() - dt_util.as_local(start_dt)).total_seconds()
        return round(max(elapsed, 0) / 3600, 2)

    def _start_home_session(self, tracker_id: str) -> None:
        rec = self._duration_rec(tracker_id)
        if rec.get("start"):
            return
        rec["elapsed"] = 0.0
        rec["start"] = dt_util.now().isoformat()

    def _end_home_session(self, tracker_id: str) -> None:
        rec = self._duration_rec(tracker_id)
        person = self._person_by_tracker(tracker_id)
        daily = bool(
            self.person_cfg(
                person, CONF_RESET_HOME_DURATION, DEFAULT_RESET_HOME_DURATION
            )
        )
        if daily:
            rec["elapsed"] = 0.0
            rec["start"] = None
            return
        start = rec.get("start")
        if not start:
            return
        start_dt = dt_util.parse_datetime(start)
        if start_dt is not None:
            rec["elapsed"] = float(rec.get("elapsed") or 0) + max(
                (dt_util.now() - dt_util.as_local(start_dt)).total_seconds(), 0
            )
        rec["start"] = None

    def _maybe_reset_duration(self) -> bool:
        now = dt_util.now()
        today = now.date().isoformat()
        now_t = now.time().replace(microsecond=0)
        changed = False
        for person in self.people:
            tracker = person.get(CONF_PERSON)
            if not tracker:
                continue
            if not bool(
                self.person_cfg(
                    person, CONF_RESET_HOME_DURATION, DEFAULT_RESET_HOME_DURATION
                )
            ):
                continue
            rec = self._duration_rec(tracker)
            if rec.get("reset_date") == today:
                continue
            reset_t = _parse_time(
                self.person_cfg(person, CONF_DAILY_RESET, DEFAULT_DAILY_RESET)
            )
            last = rec.get("reset_date")
            days_gap = 1
            if last:
                try:
                    last_date = datetime.strptime(last, "%Y-%m-%d").date()
                    days_gap = (now.date() - last_date).days
                except (TypeError, ValueError):
                    days_gap = 1
            if now_t < reset_t and days_gap <= 1:
                continue
            state = self.hass.states.get(tracker)
            if state and state.state not in ("unknown", "unavailable"):
                in_home = self._in_zones(
                    tracker, _as_list(person.get(CONF_HOME_ZONES))
                )
            else:
                in_home = bool(rec.get("start"))
            rec["elapsed"] = 0.0
            rec["start"] = dt_util.now().isoformat() if in_home else None
            rec["reset_date"] = today
            changed = True
        return changed

    def _sync_away(self) -> None:
        away = dict(self._data.get("away") or {})
        for person in self.people:
            tracker = person.get(CONF_PERSON)
            home_zones = _as_list(person.get(CONF_HOME_ZONES))
            if not tracker or not home_zones:
                continue
            state = self.hass.states.get(tracker)
            if not state or state.state in ("unknown", "unavailable"):
                continue
            away[tracker] = not self._in_zones(tracker, home_zones)
        self._data["away"] = away

    def _sync_home_sessions(self) -> None:
        for person in self.people:
            tracker = person.get(CONF_PERSON)
            if not tracker or not person.get(CONF_HOME_ZONES):
                continue
            state = self.hass.states.get(tracker)
            if not state or state.state in ("unknown", "unavailable"):
                continue
            in_home = self._in_zones(tracker, _as_list(person.get(CONF_HOME_ZONES)))
            rec = self._duration_rec(tracker)
            if in_home and not rec.get("start"):
                self._start_home_session(tracker)
            elif not in_home and rec.get("start"):
                self._end_home_session(tracker)

    def _entity_state(self, entity_id: str | None) -> str:
        if not entity_id:
            return "unknown"
        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            return "unknown"
        return state.state

    def _has_commute_entities(self, person: dict[str, Any]) -> bool:
        return any(
            _as_list(person.get(k))
            for k in (CONF_COMMUTE_SENSOR, CONF_COMMUTE_DISTANCE, CONF_COMMUTE_TIME)
        )

    async def _async_clear_commute(self, person: dict[str, Any]) -> None:
        no_commute = tr(self.hass, "no_commute")
        zero_time = tr(self.hass, "zero_minutes")
        for eid in _as_list(person.get(CONF_COMMUTE_SENSOR)):
            await self._async_write_state(
                eid, no_commute, kind="info", icon="mdi:briefcase-clock"
            )
        await self._async_write_state(
            person.get(CONF_COMMUTE_DISTANCE),
            0,
            kind="distance",
            icon="mdi:map-marker-distance",
            unit=UnitOfLength.KILOMETERS,
        )
        await self._async_write_state(
            person.get(CONF_COMMUTE_TIME),
            zero_time,
            kind="time",
            icon="mdi:car-clock",
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

    async def _async_write_state(
        self,
        entity_id: str | None,
        value: Any,
        *,
        kind: str | None = None,
        icon: str | None = None,
        unit: str | None = None,
    ) -> None:
        if not entity_id or value is None:
            return
        domain = entity_id.split(".", 1)[0]
        try:
            entity = self._sensor_entity(entity_id)
            device = self._restore_device(entity, kind)
            if device is not None:
                if kind == "address":
                    device.restore_location_address(value)
                elif kind == "distance":
                    device.restore_commute_distance(value)
                elif kind == "time":
                    device.restore_commute_time(value)
                elif kind == "info":
                    device.restore_commute_info(value)
                entity.async_write_ha_state()
                return
            if domain in ("input_text", "text"):
                await self.hass.services.async_call(
                    domain,
                    "set_value",
                    {"entity_id": entity_id, "value": str(value)},
                    blocking=False,
                )
                return
            if domain == "input_number":
                await self.hass.services.async_call(
                    "input_number",
                    "set_value",
                    {"entity_id": entity_id, "value": float(value)},
                    blocking=False,
                )
                return
            state = self.hass.states.get(entity_id)
            attrs = dict(state.attributes) if state else {}
            if icon:
                attrs["icon"] = icon
            if unit:
                attrs["unit_of_measurement"] = unit
            self.hass.states.async_set(entity_id, value, attrs)
        except Exception:
            _LOGGER.exception("更新实体失败 %s", entity_id)

    def _lonlat(self, entity_id: str | None) -> tuple[float, float] | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if not state:
            return None
        lat = _coord(state.attributes.get("latitude"))
        lon = _coord(state.attributes.get("longitude"))
        if lat is None or lon is None:
            return None
        return lon, lat

    def _home_zones_lonlat(self, person: dict[str, Any]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for zid in _as_list(person.get(CONF_HOME_ZONES)):
            coords = self._lonlat(zid)
            if coords:
                out.append(coords)
        return out

    def _nearest_home_lonlat(
        self, person: dict[str, Any], olon: float, olat: float
    ) -> tuple[float, float] | None:
        nearest: tuple[float, float] | None = None
        best = float("inf")
        for lon, lat in self._home_zones_lonlat(person):
            d = _meters(olon, olat, lon, lat)
            if d < best:
                best = d
                nearest = (lon, lat)
        return nearest

    def _near_any_home(
        self, person: dict[str, Any], olon: float, olat: float, radius_m: float = 400
    ) -> bool:
        return any(
            _meters(olon, olat, lon, lat) < radius_m
            for lon, lat in self._home_zones_lonlat(person)
        )

    async def _amap_json(self, url: str, params: dict[str, Any]) -> dict[str, Any] | None:
        key = self.cfg(CONF_AMAP_KEY)
        if not key:
            return None
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                url,
                params={**params, "key": key, "output": "json"},
                timeout=ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except Exception:
            _LOGGER.exception("高德请求失败")
            return None
        if not isinstance(data, dict) or str(data.get("status")) != "1":
            return None
        return data

    async def _amap_regeo(self, lon: float, lat: float) -> str | None:
        data = await self._amap_json(
            "https://restapi.amap.com/v3/geocode/regeo",
            {"location": f"{lon:.6f},{lat:.6f}"},
        )
        if not data:
            return None
        addr = (data.get("regeocode") or {}).get("formatted_address")
        if not addr or isinstance(addr, list):
            return None
        return str(addr)

    def _amap_path(self, data: dict[str, Any] | None) -> tuple[float | None, int | None]:
        route = (data or {}).get("route")
        if isinstance(route, list):
            route = route[0] if route else None
        if not isinstance(route, dict):
            return None, None
        paths = _amap_items(route.get("paths"))
        path = paths[0] if paths else None
        if not path:
            return None, None
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
        distance = _amap_num(path.get("distance"))
        if distance is None:
            total = 0.0
            found = False
            for step in _amap_items(path.get("steps")):
                meters = _amap_num(step.get("step_distance"))
                if meters is None:
                    meters = _amap_num(step.get("distance"))
                if meters is not None:
                    total += meters
                    found = True
            distance = total if found else None
        if distance is None or duration is None:
            return None, None
        return distance, int(duration)

    async def _amap_drive(
        self, olon: float, olat: float, dlon: float, dlat: float
    ) -> tuple[float | None, int | None]:
        return self._amap_path(
            await self._amap_json(
                "https://restapi.amap.com/v5/direction/driving",
                {
                    "origin": f"{olon:.6f},{olat:.6f}",
                    "destination": f"{dlon:.6f},{dlat:.6f}",
                    "show_fields": "cost",
                },
            )
        )

    async def _amap_bike(
        self, olon: float, olat: float, dlon: float, dlat: float
    ) -> tuple[float | None, int | None]:
        return self._amap_path(
            await self._amap_json(
                "https://restapi.amap.com/v5/direction/electrobike",
                {
                    "origin": f"{olon:.6f},{olat:.6f}",
                    "destination": f"{dlon:.6f},{dlat:.6f}",
                    "show_fields": "cost",
                },
            )
        )

    def _commute_modes(self, person: dict[str, Any], meters: float) -> list[str]:
        if meters > COMMUTE_BIKE_MAX_M:
            return [MODE_DRIVING]
        eid = person.get(CONF_ACTIVITY_SENSOR)
        if eid:
            state = self._entity_state(eid)
            if state in ACTIVITY_BIKE:
                return [MODE_BICYCLING]
            if state in ACTIVITY_DRIVE:
                return [MODE_DRIVING]
        return [MODE_BICYCLING]

    async def _async_update_geo(self, tracker_id: str) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "addr": "unknown",
            "commute": tr(self.hass, "no_commute"),
            "distance": None,
            "time": tr(self.hass, "zero_minutes"),
        }
        person = self._person_by_tracker(tracker_id)
        if not person:
            return rec
        at_home = self._in_zones(tracker_id, _as_list(person.get(CONF_HOME_ZONES)))
        coords = self._lonlat(tracker_id)
        near_home = at_home
        if coords and not at_home:
            near_home = self._near_any_home(person, coords[0], coords[1])
        if near_home:
            rec["distance"] = 0
            rec["time"] = tr(self.hass, "zero_minutes")
            rec["commute"] = tr(self.hass, "no_commute")
            if coords and self.cfg(CONF_AMAP_KEY):
                lon, lat = _wgs84_to_gcj02(*coords)
                addr = await self._amap_regeo(lon, lat)
                if addr:
                    rec["addr"] = addr
            if rec["addr"] == "unknown":
                rec["addr"] = self._entity_state(person.get(CONF_ADDR_SENSOR))
            else:
                await self._async_write_state(
                    person.get(CONF_ADDR_SENSOR),
                    rec["addr"],
                    kind="address",
                    icon="mdi:map-marker",
                )
            await self._async_clear_commute(person)
            if coords and self.cfg(CONF_AMAP_KEY):
                self._geo_cache[tracker_id] = {
                    "lon": coords[0],
                    "lat": coords[1],
                    "rec": dict(rec),
                }
            return rec
        if coords and self.cfg(CONF_AMAP_KEY):
            prev = self._geo_cache.get(tracker_id)
            if (
                prev
                and _meters(coords[0], coords[1], prev["lon"], prev["lat"]) < 400
            ):
                return dict(prev["rec"])
            lon, lat = _wgs84_to_gcj02(*coords)
            addr = await self._amap_regeo(lon, lat)
            if addr:
                rec["addr"] = addr
            dest = self._nearest_home_lonlat(person, coords[0], coords[1])
            if dest:
                dlon, dlat = _wgs84_to_gcj02(*dest)
                parts: list[str] = []
                modes = self._commute_modes(person, _meters(lon, lat, dlon, dlat))
                prefix = len(modes) > 1
                for mode in modes:
                    if mode == MODE_DRIVING:
                        meters, seconds = await self._amap_drive(
                            lon, lat, dlon, dlat
                        )
                        label = tr(self.hass, "driving")
                    else:
                        meters, seconds = await self._amap_bike(
                            lon, lat, dlon, dlat
                        )
                        label = tr(self.hass, "bicycling")
                    if meters is None or seconds is None or seconds < 60:
                        continue
                    km = int(meters / 10) / 100
                    minutes = seconds // 60
                    time_s = _fmt_minutes(self.hass, minutes)
                    if rec["distance"] is None:
                        rec["distance"] = km
                        rec["minutes"] = minutes
                        rec["time"] = time_s
                    key = "commute_home_mode" if prefix else "commute_home"
                    parts.append(
                        tr(self.hass, key, mode=label, km=km, time=time_s)
                    )
                if parts:
                    rec["commute"] = "\n".join(parts)
        if rec["addr"] == "unknown":
            rec["addr"] = self._entity_state(person.get(CONF_ADDR_SENSOR))
        else:
            await self._async_write_state(
                person.get(CONF_ADDR_SENSOR),
                rec["addr"],
                kind="address",
                icon="mdi:map-marker",
            )
        if rec["distance"] is None:
            eids = _as_list(person.get(CONF_COMMUTE_SENSOR))
            if eids:
                rec["commute"] = self._entity_state(eids[0])
            rec["time"] = self._entity_state(person.get(CONF_COMMUTE_TIME))
            if rec["time"] == "unknown":
                rec["time"] = tr(self.hass, "zero_minutes")
        else:
            for eid in _as_list(person.get(CONF_COMMUTE_SENSOR)):
                await self._async_write_state(
                    eid, rec["commute"], kind="info", icon="mdi:briefcase-clock"
                )
            await self._async_write_state(
                person.get(CONF_COMMUTE_DISTANCE),
                rec["distance"],
                kind="distance",
                icon="mdi:map-marker-distance",
                unit=UnitOfLength.KILOMETERS,
            )
            await self._async_write_state(
                person.get(CONF_COMMUTE_TIME),
                rec["time"],
                kind="time",
                icon="mdi:car-clock",
            )
        if coords and self.cfg(CONF_AMAP_KEY):
            self._geo_cache[tracker_id] = {
                "lon": coords[0],
                "lat": coords[1],
                "rec": dict(rec),
            }
        return rec

    def _notify_commute(self, geo: dict[str, Any]) -> str:
        commute = geo.get("commute") or ""
        if not commute or commute in (tr(self.hass, "no_commute"), "unknown"):
            return ""
        commute = str(commute).replace("\\n", "\n")
        return commute if commute.endswith("\n") else f"{commute}\n"

    async def _async_send_notify(
        self, title: str, message: str, person: dict[str, Any] | None = None
    ) -> None:
        message = str(message).replace("\\n", "\n").strip()
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
                _LOGGER.exception("通知动作执行失败")

    async def _async_announce(
        self, message: str, person: dict[str, Any] | None = None
    ) -> None:
        players = _as_list(self.cfg(CONF_ANNOUNCE))
        if not players or not message:
            return
        for eid in players:
            if not isinstance(eid, str) or "." not in eid:
                continue
            domain = eid.split(".", 1)[0]
            try:
                if domain in ("text", "input_text"):
                    await self.hass.services.async_call(
                        domain, "set_value", {"entity_id": eid, "value": message}, blocking=False
                    )
                elif domain == "media_player":
                    if self.hass.services.has_service("xiaomi_miot", "intelligent_speaker"):
                        await self.hass.services.async_call(
                            "xiaomi_miot",
                            "intelligent_speaker",
                            {"entity_id": eid, "text": message, "execute": False, "silent": False},
                            blocking=False,
                        )
                    elif self.hass.services.has_service("tts", "speak"):
                        tts_ids = self.hass.states.async_entity_ids("tts")
                        if not tts_ids:
                            continue
                        await self.hass.services.async_call(
                            "tts",
                            "speak",
                            {"media_player_entity_id": eid, "message": message},
                            target={"entity_id": tts_ids[0]},
                            blocking=False,
                        )
            except Exception:
                _LOGGER.exception("播报失败")

    async def _async_notify(
        self,
        tracker_id: str,
        arrive: bool,
        geo: dict[str, Any] | None = None,
    ) -> None:
        person = self._person_by_tracker(tracker_id)
        if not person:
            return
        if arrive and not self.person_cfg(
            person, CONF_NOTIFY_ARRIVE, DEFAULT_NOTIFY_ARRIVE
        ):
            return
        if not arrive and not self.person_cfg(
            person, CONF_NOTIFY_LEAVE, DEFAULT_NOTIFY_LEAVE
        ):
            return
        now_t = dt_util.now().time().replace(microsecond=0)
        if arrive:
            start = _parse_time(
                self.person_cfg(person, CONF_ARRIVE_START, DEFAULT_ARRIVE_START)
            )
            end = _parse_time(
                self.person_cfg(person, CONF_ARRIVE_END, DEFAULT_ARRIVE_END)
            )
        else:
            start = _parse_time(
                self.person_cfg(person, CONF_LEAVE_START, DEFAULT_LEAVE_START)
            )
            end = _parse_time(
                self.person_cfg(person, CONF_LEAVE_END, DEFAULT_LEAVE_END)
            )
        if not _in_window(now_t, start, end):
            return
        if geo is None:
            geo = await self._async_update_geo(tracker_id)
        name = person.get("name") or tr(self.hass, "person")
        addr = geo.get("addr") or "unknown"
        commute = self._notify_commute(geo)
        now_s = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
        if arrive:
            title = tr(self.hass, "arrive_title", name=name)
            message = tr(
                self.hass,
                "arrive_message",
                addr=addr,
                now=now_s,
            )
        else:
            title = tr(self.hass, "leave_title", name=name)
            message = tr(
                self.hass, "leave_message", addr=addr, commute=commute, now=now_s
            )
        await self._async_send_notify(title, message, person)
        await self._async_announce(message.strip(), person)

    async def _async_notify_station(
        self, tracker_id: str, enter: bool, station: str
    ) -> None:
        person = self._person_by_tracker(tracker_id)
        if not person:
            return
        if enter and not self.person_cfg(
            person, CONF_NOTIFY_STATION_ENTER, DEFAULT_NOTIFY_STATION_ENTER
        ):
            return
        if not enter and not self.person_cfg(
            person, CONF_NOTIFY_STATION_LEAVE, DEFAULT_NOTIFY_STATION_LEAVE
        ):
            return
        geo = await self._async_update_geo(tracker_id)
        name = person.get("name") or tr(self.hass, "person")
        addr = geo.get("addr") or "unknown"
        commute = self._notify_commute(geo)
        now_s = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
        if enter:
            title = tr(self.hass, "station_enter_title", name=name)
        else:
            title = tr(self.hass, "station_leave_title", name=name)
        message = tr(
            self.hass,
            "station_message",
            station=station,
            addr=addr,
            commute=commute,
            now=now_s,
        )
        await self._async_send_notify(title, message, person)
        await self._async_announce(message.strip(), person)

    async def async_set_away(self, tracker_id: str, on: bool, *, notify: bool = False) -> None:
        was_away = bool((self._data.get("away") or {}).get(tracker_id))
        away = dict(self._data.get("away") or {})
        away[tracker_id] = on
        self._data["away"] = away
        person = self._person_by_tracker(tracker_id)
        state = self.hass.states.get(tracker_id)
        if (
            person
            and state
            and state.state not in ("unknown", "unavailable")
        ):
            if self._in_zones(tracker_id, _as_list(person.get(CONF_HOME_ZONES))):
                self._start_home_session(tracker_id)
            else:
                self._end_home_session(tracker_id)
        await self._save()
        geo = None
        if person and self._has_commute_entities(person) and was_away != on:
            geo = await self._async_update_geo(tracker_id)
        if notify and on and not was_away:
            await self._async_notify(tracker_id, False, geo=geo)
        elif notify and not on and was_away:
            await self._async_notify(tracker_id, True, geo=geo)
