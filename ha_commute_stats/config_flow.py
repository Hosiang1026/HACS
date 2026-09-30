from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    Selector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .localize import tr
from .const import (
    CONF_ACTIVITY_SENSOR,
    CONF_ADDR_SENSOR,
    CONF_AMAP_KEY,
    CONF_ANNOUNCE,
    CONF_AREA_LAT_MAX,
    CONF_AREA_LAT_MIN,
    CONF_AREA_LON_MAX,
    CONF_AREA_LON_MIN,
    CONF_ARRIVE_END,
    CONF_ARRIVE_START,
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
    CONF_HOLIDAY_SENSOR,
    CONF_HOLIDAY_WAGE,
    CONF_HOME_ZONES,
    CONF_HOMETOWN_ZONE,
    CONF_INDOOR_SENSOR,
    CONF_LEAVE_END,
    CONF_LEAVE_START,
    CONF_LUNCH_END,
    CONF_LUNCH_START,
    CONF_MONTHLY_RESET_DAY,
    CONF_NOTIFY,
    CONF_NOTIFY_ARRIVE,
    CONF_NOTIFY_ARRIVE_ANNOUNCE,
    CONF_NOTIFY_ARRIVE_NOTIFY,
    CONF_NOTIFY_LEAVE,
    CONF_NOTIFY_LEAVE_ANNOUNCE,
    CONF_NOTIFY_LEAVE_NOTIFY,
    CONF_NOTIFY_STATION_ENTER,
    CONF_NOTIFY_STATION_ENTER_ANNOUNCE,
    CONF_NOTIFY_STATION_ENTER_NOTIFY,
    CONF_NOTIFY_STATION_LEAVE,
    CONF_NOTIFY_STATION_LEAVE_ANNOUNCE,
    CONF_NOTIFY_STATION_LEAVE_NOTIFY,
    CONF_OVER_WAGE,
    CONF_OVERTIME_START,
    CONF_PEOPLE,
    CONF_PERSON,
    CONF_PERSON_NAME,
    CONF_RESET_HOME_DURATION,
    CONF_STANDARD_HOURS,
    CONF_STATION_ENTER_ZONES,
    CONF_STATION_LEAVE_ZONES,
    CONF_TOTAL_PEOPLE,
    CONF_WORK_ENABLED,
    CONF_WORK_NOTIFY,
    CONF_WORK_NOTIFY_ANNOUNCE,
    CONF_WORK_NOTIFY_NOTIFY,
    CONF_WORK_ZONES,
    DEFAULT_AREA_LAT_MAX,
    DEFAULT_AREA_LAT_MIN,
    DEFAULT_AREA_LON_MAX,
    DEFAULT_AREA_LON_MIN,
    DEFAULT_ARRIVE_END,
    DEFAULT_ARRIVE_START,
    DEFAULT_BASE_SALARY,
    DEFAULT_CLOCK_IN_END,
    DEFAULT_CLOCK_IN_START,
    DEFAULT_CLOCK_OUT_END,
    DEFAULT_CLOCK_OUT_START,
    DEFAULT_COMP_DEDUCT,
    DEFAULT_COMP_THRESHOLD,
    DEFAULT_DAILY_RESET,
    DEFAULT_HOLIDAY_WAGE,
    DEFAULT_LEAVE_END,
    DEFAULT_LEAVE_START,
    DEFAULT_LUNCH_END,
    DEFAULT_LUNCH_START,
    DEFAULT_MONTHLY_RESET_DAY,
    DEFAULT_NOTIFY_ARRIVE,
    DEFAULT_NOTIFY_LEAVE,
    DEFAULT_NOTIFY_STATION_ENTER,
    DEFAULT_NOTIFY_STATION_LEAVE,
    DEFAULT_OVER_WAGE,
    DEFAULT_OVERTIME_START,
    DEFAULT_RESET_HOME_DURATION,
    DEFAULT_STANDARD_HOURS,
    DEFAULT_TOTAL_PEOPLE,
    DEFAULT_WORK_ENABLED,
    DEFAULT_WORK_NOTIFY,
    DOMAIN,
    HOME_RULE_KEYS,
    WORK_RULE_KEYS,
)

_AREA_SECTION = "city_area"
_LAT_ROW = "lat_row"
_LON_ROW = "lon_row"
_ARRIVE_ROW = "arrive_row"
_LEAVE_ROW = "leave_row"


def _field_list(schema: vol.Schema) -> Any:
    try:
        from probatio import to_field_list
    except ImportError:
        import voluptuous_serialize

        return voluptuous_serialize.convert(
            schema, custom_serializer=cv.custom_serializer
        )
    return to_field_list(schema, custom_serializer=cv.custom_serializer)


class _FormGrid(Selector):
    selector_type = "grid"
    CONFIG_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)

    def __init__(self, fields: dict, column_min_width: str = "120px") -> None:
        self.config: dict[str, Any] = {}
        self._fields = fields
        self._column_min_width = column_min_width
        self._inner = vol.Schema(fields)

    def __call__(self, data: Any) -> Any:
        return self._inner(data)

    def serialize(self) -> dict[str, Any]:
        return {
            "type": "grid",
            "flatten": False,
            "column_min_width": self._column_min_width,
            "schema": _field_list(vol.Schema(self._fields)),
        }


def _get(src: dict, key: str, default: Any) -> Any:
    if key in src and src[key] not in (None, ""):
        return src[key]
    return default


def _holiday_sensor_fallback(src: dict[str, Any]) -> str | None:
    holiday = _get(src, CONF_HOLIDAY_SENSOR, None)
    if holiday:
        return holiday
    for person in src.get(CONF_PEOPLE) or []:
        val = person.get(CONF_HOLIDAY_SENSOR)
        if val not in (None, ""):
            return val
    return None


def _notify_values(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        action = raw.get("action") or raw.get("service")
        return [action] if action else []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            out.append(item)
        elif isinstance(item, dict):
            action = item.get("action") or item.get("service")
            if action:
                out.append(action)
    return out


def _notify_options(hass: HomeAssistant | None, current: Any = None) -> list[str]:
    names: set[str] = set(_notify_values(current))
    if hass:
        for name in hass.services.async_services().get("notify", {}):
            if name != "send_message":
                names.add(f"notify.{name}")
        names.update(hass.states.async_entity_ids("notify"))
    return sorted(names)


def _announce_values(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    return [item for item in raw if item]


def _stored_or_legacy(src: dict[str, Any], key: str, legacy: str) -> Any:
    if key in src and src[key] not in (None, ""):
        return src[key]
    return src.get(legacy)


def _notify_selector(hass: HomeAssistant | None, current: Any) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=_notify_options(hass, current),
            multiple=True,
            custom_value=True,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _announce_selector() -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(multiple=True))


def _channel_fields(
    notify_key: str,
    announce_key: str,
    hass: HomeAssistant | None,
    defaults: dict[str, Any],
) -> dict[Any, Any]:
    return {
        vol.Optional(notify_key): _notify_selector(
            hass, _stored_or_legacy(defaults, notify_key, CONF_NOTIFY)
        ),
        vol.Optional(announce_key): _announce_selector(),
    }


def _channel_suggested(
    merged: dict[str, Any], notify_key: str, announce_key: str
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    notify = _notify_values(_stored_or_legacy(merged, notify_key, CONF_NOTIFY))
    if notify:
        values[notify_key] = notify
    announce = _announce_values(_stored_or_legacy(merged, announce_key, CONF_ANNOUNCE))
    if announce:
        values[announce_key] = announce
    return values


def _channel_saved(
    src: dict[str, Any], notify_key: str, announce_key: str
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if notify_key in src:
        out[notify_key] = _notify_values(src.get(notify_key))
    if announce_key in src:
        out[announce_key] = _announce_values(src.get(announce_key))
    return out


_HOME_CHANNELS = (
    (CONF_NOTIFY_ARRIVE, CONF_NOTIFY_ARRIVE_NOTIFY, CONF_NOTIFY_ARRIVE_ANNOUNCE),
    (CONF_NOTIFY_LEAVE, CONF_NOTIFY_LEAVE_NOTIFY, CONF_NOTIFY_LEAVE_ANNOUNCE),
    (
        CONF_NOTIFY_STATION_ENTER,
        CONF_NOTIFY_STATION_ENTER_NOTIFY,
        CONF_NOTIFY_STATION_ENTER_ANNOUNCE,
    ),
    (
        CONF_NOTIFY_STATION_LEAVE,
        CONF_NOTIFY_STATION_LEAVE_NOTIFY,
        CONF_NOTIFY_STATION_LEAVE_ANNOUNCE,
    ),
)
_WORK_CHANNELS = (
    (CONF_WORK_NOTIFY, CONF_WORK_NOTIFY_NOTIFY, CONF_WORK_NOTIFY_ANNOUNCE),
)


def _channel_errors(
    src: dict[str, Any], channels: tuple[tuple[str, str, str], ...]
) -> dict[str, str]:
    errors: dict[str, str] = {}
    for enabled, notify_key, announce_key in channels:
        if not src.get(enabled):
            continue
        if _notify_values(src.get(notify_key)) or _announce_values(src.get(announce_key)):
            continue
        errors[notify_key] = "notify_or_announce"
        errors[announce_key] = "notify_or_announce"
    return errors


def _coord_box(min_v: float, max_v: float) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=min_v, max=max_v, step=0.01, mode=NumberSelectorMode.BOX)
    )


def _area_fields() -> dict[Any, Any]:
    return {
        vol.Required(_LAT_ROW): _FormGrid(
            {
                vol.Required(CONF_AREA_LAT_MIN): _coord_box(-90, 90),
                vol.Required(CONF_AREA_LAT_MAX): _coord_box(-90, 90),
            }
        ),
        vol.Required(_LON_ROW): _FormGrid(
            {
                vol.Required(CONF_AREA_LON_MIN): _coord_box(-180, 180),
                vol.Required(CONF_AREA_LON_MAX): _coord_box(-180, 180),
            }
        ),
    }


def _area_values(defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        _LAT_ROW: {
            CONF_AREA_LAT_MIN: _get(defaults, CONF_AREA_LAT_MIN, DEFAULT_AREA_LAT_MIN),
            CONF_AREA_LAT_MAX: _get(defaults, CONF_AREA_LAT_MAX, DEFAULT_AREA_LAT_MAX),
        },
        _LON_ROW: {
            CONF_AREA_LON_MIN: _get(defaults, CONF_AREA_LON_MIN, DEFAULT_AREA_LON_MIN),
            CONF_AREA_LON_MAX: _get(defaults, CONF_AREA_LON_MAX, DEFAULT_AREA_LON_MAX),
        },
    }


def _notify_time_fields() -> dict[Any, Any]:
    return {
        vol.Required(_ARRIVE_ROW): _FormGrid(
            {
                vol.Required(CONF_ARRIVE_START): TimeSelector(),
                vol.Required(CONF_ARRIVE_END): TimeSelector(),
            },
            column_min_width="160px",
        ),
        vol.Required(_LEAVE_ROW): _FormGrid(
            {
                vol.Required(CONF_LEAVE_START): TimeSelector(),
                vol.Required(CONF_LEAVE_END): TimeSelector(),
            },
            column_min_width="160px",
        ),
    }


def _notify_time_values(defaults: dict[str, Any]) -> dict[str, Any]:
    return {
        _ARRIVE_ROW: {
            CONF_ARRIVE_START: _get(defaults, CONF_ARRIVE_START, DEFAULT_ARRIVE_START),
            CONF_ARRIVE_END: _get(defaults, CONF_ARRIVE_END, DEFAULT_ARRIVE_END),
        },
        _LEAVE_ROW: {
            CONF_LEAVE_START: _get(defaults, CONF_LEAVE_START, DEFAULT_LEAVE_START),
            CONF_LEAVE_END: _get(defaults, CONF_LEAVE_END, DEFAULT_LEAVE_END),
        },
    }


def _notify_times_from_src(src: dict[str, Any]) -> dict[str, str]:
    arrive = src.get(_ARRIVE_ROW)
    leave = src.get(_LEAVE_ROW)
    arrive = arrive if isinstance(arrive, dict) else src
    leave = leave if isinstance(leave, dict) else src
    return {
        CONF_ARRIVE_START: arrive.get(
            CONF_ARRIVE_START, src.get(CONF_ARRIVE_START, DEFAULT_ARRIVE_START)
        ),
        CONF_ARRIVE_END: arrive.get(
            CONF_ARRIVE_END, src.get(CONF_ARRIVE_END, DEFAULT_ARRIVE_END)
        ),
        CONF_LEAVE_START: leave.get(
            CONF_LEAVE_START, src.get(CONF_LEAVE_START, DEFAULT_LEAVE_START)
        ),
        CONF_LEAVE_END: leave.get(
            CONF_LEAVE_END, src.get(CONF_LEAVE_END, DEFAULT_LEAVE_END)
        ),
    }


def _area_from_src(src: dict[str, Any]) -> dict[str, float]:
    area = src.get(_AREA_SECTION)
    lat: dict[str, Any] = {}
    lon: dict[str, Any] = {}
    if isinstance(area, dict):
        lat = area.get(_LAT_ROW) if isinstance(area.get(_LAT_ROW), dict) else area
        lon = area.get(_LON_ROW) if isinstance(area.get(_LON_ROW), dict) else area
    return {
        CONF_AREA_LAT_MIN: float(
            lat.get(CONF_AREA_LAT_MIN, src.get(CONF_AREA_LAT_MIN, DEFAULT_AREA_LAT_MIN))
        ),
        CONF_AREA_LAT_MAX: float(
            lat.get(CONF_AREA_LAT_MAX, src.get(CONF_AREA_LAT_MAX, DEFAULT_AREA_LAT_MAX))
        ),
        CONF_AREA_LON_MIN: float(
            lon.get(CONF_AREA_LON_MIN, src.get(CONF_AREA_LON_MIN, DEFAULT_AREA_LON_MIN))
        ),
        CONF_AREA_LON_MAX: float(
            lon.get(CONF_AREA_LON_MAX, src.get(CONF_AREA_LON_MAX, DEFAULT_AREA_LON_MAX))
        ),
    }


def _shared_fields(
    include_name: bool = False,
    defaults: dict[str, Any] | None = None,
    hass: HomeAssistant | None = None,
) -> dict[Any, Any]:
    defaults = defaults or {}
    schema: dict[Any, Any] = {}
    if include_name:
        schema[vol.Required(CONF_NAME)] = TextSelector()
    schema.update(
        {
            vol.Required(CONF_TOTAL_PEOPLE): NumberSelector(
                NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_INDOOR_SENSOR, default=[]): EntitySelector(
                EntitySelectorConfig(domain="sensor", multiple=True)
            ),
            vol.Optional(CONF_AMAP_KEY): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_HOLIDAY_SENSOR): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
        }
    )
    return schema


def _shared_values(
    defaults: dict[str, Any], include_name: bool = False, hass: Any = None
) -> dict[str, Any]:
    values: dict[str, Any] = {
        CONF_TOTAL_PEOPLE: _get(defaults, CONF_TOTAL_PEOPLE, DEFAULT_TOTAL_PEOPLE),
    }
    if include_name:
        values[CONF_NAME] = _get(
            defaults, CONF_NAME, tr(hass, "default_name") if hass else "通勤统计"
        )
    indoor = _get(defaults, CONF_INDOOR_SENSOR, None)
    if isinstance(indoor, str):
        indoor = [indoor] if indoor else []
    elif indoor:
        indoor = list(indoor)
    else:
        indoor = []
    values[CONF_INDOOR_SENSOR] = indoor
    amap_key = _get(defaults, CONF_AMAP_KEY, None)
    if amap_key:
        values[CONF_AMAP_KEY] = amap_key
    holiday = _holiday_sensor_fallback(defaults)
    if holiday:
        values[CONF_HOLIDAY_SENSOR] = holiday
    return values


def _shared_options(
    src: dict[str, Any], existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    existing = existing or {}
    if CONF_INDOOR_SENSOR in src:
        indoor = src.get(CONF_INDOOR_SENSOR) or []
        if isinstance(indoor, str):
            indoor = [indoor]
        indoor = list(indoor)
    else:
        indoor = existing.get(CONF_INDOOR_SENSOR) or []
        if isinstance(indoor, str):
            indoor = [indoor]
    if CONF_AMAP_KEY in src:
        amap_key = src.get(CONF_AMAP_KEY) or existing.get(CONF_AMAP_KEY)
    else:
        amap_key = existing.get(CONF_AMAP_KEY)
    if CONF_HOLIDAY_SENSOR in src:
        holiday_sensor = src.get(CONF_HOLIDAY_SENSOR) or None
    else:
        holiday_sensor = existing.get(CONF_HOLIDAY_SENSOR)
    return {
        CONF_TOTAL_PEOPLE: int(src.get(CONF_TOTAL_PEOPLE, DEFAULT_TOTAL_PEOPLE)),
        CONF_INDOOR_SENSOR: indoor,
        CONF_AMAP_KEY: amap_key or None,
        CONF_HOLIDAY_SENSOR: holiday_sensor or None,
    }


def _home_rules_schema(hass: HomeAssistant | None = None, defaults: dict[str, Any] | None = None) -> dict[Any, Any]:
    defaults = defaults or {}
    return {
        vol.Optional(CONF_HOME_ZONES): EntitySelector(
            EntitySelectorConfig(domain="zone", multiple=True)
        ),
        vol.Required(_AREA_SECTION): section(
            vol.Schema(_area_fields()),
            {"collapsed": False},
        ),
        vol.Required(CONF_NOTIFY_ARRIVE): BooleanSelector(),
        **_channel_fields(
            CONF_NOTIFY_ARRIVE_NOTIFY, CONF_NOTIFY_ARRIVE_ANNOUNCE, hass, defaults
        ),
        vol.Required(CONF_NOTIFY_LEAVE): BooleanSelector(),
        **_channel_fields(
            CONF_NOTIFY_LEAVE_NOTIFY, CONF_NOTIFY_LEAVE_ANNOUNCE, hass, defaults
        ),
        **_notify_time_fields(),
        vol.Required(CONF_NOTIFY_STATION_ENTER): BooleanSelector(),
        **_channel_fields(
            CONF_NOTIFY_STATION_ENTER_NOTIFY,
            CONF_NOTIFY_STATION_ENTER_ANNOUNCE,
            hass,
            defaults,
        ),
        vol.Optional(CONF_STATION_ENTER_ZONES): EntitySelector(
            EntitySelectorConfig(domain="zone", multiple=True)
        ),
        vol.Required(CONF_NOTIFY_STATION_LEAVE): BooleanSelector(),
        **_channel_fields(
            CONF_NOTIFY_STATION_LEAVE_NOTIFY,
            CONF_NOTIFY_STATION_LEAVE_ANNOUNCE,
            hass,
            defaults,
        ),
        vol.Optional(CONF_STATION_LEAVE_ZONES): EntitySelector(
            EntitySelectorConfig(domain="zone", multiple=True)
        ),
        vol.Required(CONF_RESET_HOME_DURATION): BooleanSelector(),
    }


def _suggested_home_rules(
    src: dict[str, Any], fallback: dict[str, Any] | None = None
) -> dict[str, Any]:
    fallback = fallback or {}
    merged = {**fallback, **{k: v for k, v in src.items() if v not in (None, "")}}
    values: dict[str, Any] = {
        _AREA_SECTION: _area_values(merged),
        CONF_NOTIFY_ARRIVE: _get(merged, CONF_NOTIFY_ARRIVE, DEFAULT_NOTIFY_ARRIVE),
        **_channel_suggested(
            merged, CONF_NOTIFY_ARRIVE_NOTIFY, CONF_NOTIFY_ARRIVE_ANNOUNCE
        ),
        CONF_NOTIFY_LEAVE: _get(merged, CONF_NOTIFY_LEAVE, DEFAULT_NOTIFY_LEAVE),
        **_channel_suggested(
            merged, CONF_NOTIFY_LEAVE_NOTIFY, CONF_NOTIFY_LEAVE_ANNOUNCE
        ),
        **_notify_time_values(merged),
        CONF_NOTIFY_STATION_ENTER: _get(
            merged, CONF_NOTIFY_STATION_ENTER, DEFAULT_NOTIFY_STATION_ENTER
        ),
        **_channel_suggested(
            merged, CONF_NOTIFY_STATION_ENTER_NOTIFY, CONF_NOTIFY_STATION_ENTER_ANNOUNCE
        ),
        CONF_NOTIFY_STATION_LEAVE: _get(
            merged, CONF_NOTIFY_STATION_LEAVE, DEFAULT_NOTIFY_STATION_LEAVE
        ),
        **_channel_suggested(
            merged, CONF_NOTIFY_STATION_LEAVE_NOTIFY, CONF_NOTIFY_STATION_LEAVE_ANNOUNCE
        ),
        CONF_RESET_HOME_DURATION: _get(
            merged, CONF_RESET_HOME_DURATION, DEFAULT_RESET_HOME_DURATION
        ),
    }
    home = _get(merged, CONF_HOME_ZONES, None)
    if home:
        home = [home] if isinstance(home, str) else list(home)
    else:
        home = []
    hometown = _get(merged, CONF_HOMETOWN_ZONE, None)
    if hometown and hometown not in home:
        home.append(hometown)
    if home:
        values[CONF_HOME_ZONES] = home
    enter_zones = _get(merged, CONF_STATION_ENTER_ZONES, None)
    if enter_zones:
        values[CONF_STATION_ENTER_ZONES] = (
            [enter_zones] if isinstance(enter_zones, str) else list(enter_zones)
        )
    leave_zones = _get(merged, CONF_STATION_LEAVE_ZONES, None)
    if leave_zones:
        values[CONF_STATION_LEAVE_ZONES] = (
            [leave_zones] if isinstance(leave_zones, str) else list(leave_zones)
        )
    return values


def _normalize_home_rules(src: dict[str, Any]) -> dict[str, Any]:
    home = src.get(CONF_HOME_ZONES) or []
    if isinstance(home, str):
        home = [home]
    home = list(home)
    hometown = src.get(CONF_HOMETOWN_ZONE)
    if hometown and hometown not in home:
        home.append(hometown)
    enter_zones = src.get(CONF_STATION_ENTER_ZONES) or []
    if isinstance(enter_zones, str):
        enter_zones = [enter_zones]
    leave_zones = src.get(CONF_STATION_LEAVE_ZONES) or []
    if isinstance(leave_zones, str):
        leave_zones = [leave_zones]
    return {
        CONF_HOME_ZONES: home,
        **_area_from_src(src),
        CONF_NOTIFY_ARRIVE: bool(src.get(CONF_NOTIFY_ARRIVE, DEFAULT_NOTIFY_ARRIVE)),
        **_channel_saved(
            src, CONF_NOTIFY_ARRIVE_NOTIFY, CONF_NOTIFY_ARRIVE_ANNOUNCE
        ),
        CONF_NOTIFY_LEAVE: bool(src.get(CONF_NOTIFY_LEAVE, DEFAULT_NOTIFY_LEAVE)),
        **_channel_saved(src, CONF_NOTIFY_LEAVE_NOTIFY, CONF_NOTIFY_LEAVE_ANNOUNCE),
        **_notify_times_from_src(src),
        CONF_NOTIFY_STATION_ENTER: bool(
            src.get(CONF_NOTIFY_STATION_ENTER, DEFAULT_NOTIFY_STATION_ENTER)
        ),
        **_channel_saved(
            src, CONF_NOTIFY_STATION_ENTER_NOTIFY, CONF_NOTIFY_STATION_ENTER_ANNOUNCE
        ),
        CONF_NOTIFY_STATION_LEAVE: bool(
            src.get(CONF_NOTIFY_STATION_LEAVE, DEFAULT_NOTIFY_STATION_LEAVE)
        ),
        **_channel_saved(
            src, CONF_NOTIFY_STATION_LEAVE_NOTIFY, CONF_NOTIFY_STATION_LEAVE_ANNOUNCE
        ),
        CONF_STATION_ENTER_ZONES: list(enter_zones),
        CONF_STATION_LEAVE_ZONES: list(leave_zones),
        CONF_RESET_HOME_DURATION: bool(
            src.get(CONF_RESET_HOME_DURATION, DEFAULT_RESET_HOME_DURATION)
        ),
    }


def _household_fields(
    include_name: bool = False,
    defaults: dict[str, Any] | None = None,
    hass: HomeAssistant | None = None,
) -> dict[Any, Any]:
    return _shared_fields(include_name=include_name, defaults=defaults)


def _household_values(
    defaults: dict[str, Any], include_name: bool = False, hass: Any = None
) -> dict[str, Any]:
    return _shared_values(defaults, include_name=include_name, hass=hass)


def _household_options(
    src: dict[str, Any], existing: dict[str, Any] | None = None
) -> dict[str, Any]:
    return _shared_options(src, existing)


def _work_rules_schema(
    hass: HomeAssistant | None = None, defaults: dict[str, Any] | None = None
) -> dict[Any, Any]:
    defaults = defaults or {}
    hours = NumberSelector(
        NumberSelectorConfig(
            min=1,
            max=24,
            step=0.5,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="h",
            translation_key="hours",
        )
    )
    hours_opt = NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=24,
            step=0.5,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="h",
            translation_key="hours",
        )
    )
    cny_day = NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=10000,
            step=0.01,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="CNY/day",
            translation_key="cny_day",
        )
    )
    cny_hour = NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=1000,
            step=0.01,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="CNY/h",
            translation_key="cny_hour",
        )
    )
    return {
        vol.Optional(CONF_WORK_ZONES): EntitySelector(
            EntitySelectorConfig(domain="zone", multiple=True)
        ),
        vol.Required(CONF_WORK_ENABLED): BooleanSelector(),
        vol.Required(CONF_STANDARD_HOURS): hours,
        vol.Required(CONF_LUNCH_START): TimeSelector(),
        vol.Required(CONF_LUNCH_END): TimeSelector(),
        vol.Required(CONF_OVERTIME_START): TimeSelector(),
        vol.Required(CONF_CLOCK_IN_START): TimeSelector(),
        vol.Required(CONF_CLOCK_IN_END): TimeSelector(),
        vol.Required(CONF_CLOCK_OUT_START): TimeSelector(),
        vol.Required(CONF_CLOCK_OUT_END): TimeSelector(),
        vol.Required(CONF_BASE_SALARY): cny_day,
        vol.Required(CONF_OVER_WAGE): cny_hour,
        vol.Required(CONF_HOLIDAY_WAGE): cny_hour,
        vol.Required(CONF_COMP_THRESHOLD): hours_opt,
        vol.Required(CONF_COMP_DEDUCT): hours_opt,
        vol.Required(CONF_DAILY_RESET): TimeSelector(),
        vol.Required(CONF_MONTHLY_RESET_DAY): NumberSelector(
            NumberSelectorConfig(min=1, max=28, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_WORK_NOTIFY): BooleanSelector(),
        **_channel_fields(
            CONF_WORK_NOTIFY_NOTIFY, CONF_WORK_NOTIFY_ANNOUNCE, hass, defaults
        ),
    }


_RULE_DEFAULTS = {
    CONF_WORK_ENABLED: DEFAULT_WORK_ENABLED,
    CONF_STANDARD_HOURS: DEFAULT_STANDARD_HOURS,
    CONF_LUNCH_START: DEFAULT_LUNCH_START,
    CONF_LUNCH_END: DEFAULT_LUNCH_END,
    CONF_OVERTIME_START: DEFAULT_OVERTIME_START,
    CONF_CLOCK_IN_START: DEFAULT_CLOCK_IN_START,
    CONF_CLOCK_IN_END: DEFAULT_CLOCK_IN_END,
    CONF_CLOCK_OUT_START: DEFAULT_CLOCK_OUT_START,
    CONF_CLOCK_OUT_END: DEFAULT_CLOCK_OUT_END,
    CONF_BASE_SALARY: DEFAULT_BASE_SALARY,
    CONF_OVER_WAGE: DEFAULT_OVER_WAGE,
    CONF_HOLIDAY_WAGE: DEFAULT_HOLIDAY_WAGE,
    CONF_COMP_THRESHOLD: DEFAULT_COMP_THRESHOLD,
    CONF_COMP_DEDUCT: DEFAULT_COMP_DEDUCT,
    CONF_DAILY_RESET: DEFAULT_DAILY_RESET,
    CONF_MONTHLY_RESET_DAY: DEFAULT_MONTHLY_RESET_DAY,
    CONF_WORK_NOTIFY: DEFAULT_WORK_NOTIFY,
}


def _suggested_work_rules(
    src: dict[str, Any], fallback: dict[str, Any] | None = None
) -> dict[str, Any]:
    fallback = fallback or {}
    merged = {**fallback, **{k: v for k, v in src.items() if v not in (None, "")}}
    suggested = {key: _get(merged, key, default) for key, default in _RULE_DEFAULTS.items()}
    suggested.update(
        _channel_suggested(merged, CONF_WORK_NOTIFY_NOTIFY, CONF_WORK_NOTIFY_ANNOUNCE)
    )
    work = _get(src, CONF_WORK_ZONES, None)
    if work:
        suggested[CONF_WORK_ZONES] = [work] if isinstance(work, str) else list(work)
    return suggested


def _normalize_work_rules(src: dict[str, Any]) -> dict[str, Any]:
    work = src.get(CONF_WORK_ZONES) or []
    if isinstance(work, str):
        work = [work]
    out: dict[str, Any] = {
        CONF_WORK_ZONES: list(work),
        CONF_WORK_ENABLED: bool(src.get(CONF_WORK_ENABLED, DEFAULT_WORK_ENABLED)),
        CONF_STANDARD_HOURS: float(
            src.get(CONF_STANDARD_HOURS, DEFAULT_STANDARD_HOURS)
        ),
        CONF_LUNCH_START: src.get(CONF_LUNCH_START, DEFAULT_LUNCH_START),
        CONF_LUNCH_END: src.get(CONF_LUNCH_END, DEFAULT_LUNCH_END),
        CONF_OVERTIME_START: src.get(CONF_OVERTIME_START, DEFAULT_OVERTIME_START),
        CONF_CLOCK_IN_START: src.get(CONF_CLOCK_IN_START, DEFAULT_CLOCK_IN_START),
        CONF_CLOCK_IN_END: src.get(CONF_CLOCK_IN_END, DEFAULT_CLOCK_IN_END),
        CONF_CLOCK_OUT_START: src.get(CONF_CLOCK_OUT_START, DEFAULT_CLOCK_OUT_START),
        CONF_CLOCK_OUT_END: src.get(CONF_CLOCK_OUT_END, DEFAULT_CLOCK_OUT_END),
        CONF_BASE_SALARY: float(src.get(CONF_BASE_SALARY, DEFAULT_BASE_SALARY)),
        CONF_OVER_WAGE: float(src.get(CONF_OVER_WAGE, DEFAULT_OVER_WAGE)),
        CONF_HOLIDAY_WAGE: float(src.get(CONF_HOLIDAY_WAGE, DEFAULT_HOLIDAY_WAGE)),
        CONF_COMP_THRESHOLD: float(
            src.get(CONF_COMP_THRESHOLD, DEFAULT_COMP_THRESHOLD)
        ),
        CONF_COMP_DEDUCT: float(src.get(CONF_COMP_DEDUCT, DEFAULT_COMP_DEDUCT)),
        CONF_DAILY_RESET: src.get(CONF_DAILY_RESET, DEFAULT_DAILY_RESET),
        CONF_MONTHLY_RESET_DAY: int(
            src.get(CONF_MONTHLY_RESET_DAY, DEFAULT_MONTHLY_RESET_DAY)
        ),
        CONF_WORK_NOTIFY: bool(src.get(CONF_WORK_NOTIFY, DEFAULT_WORK_NOTIFY)),
        **_channel_saved(src, CONF_WORK_NOTIFY_NOTIFY, CONF_WORK_NOTIFY_ANNOUNCE),
    }
    return out


def _person_fields() -> dict[Any, Any]:
    return {
        vol.Required(CONF_PERSON_NAME): TextSelector(),
        vol.Required(CONF_PERSON): EntitySelector(
            EntitySelectorConfig(domain="person")
        ),
        vol.Optional(CONF_ACTIVITY_SENSOR): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_select", "input_text"])
        ),
        vol.Optional(CONF_ADDR_SENSOR): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_text"])
        ),
        vol.Optional(CONF_COMMUTE_SENSOR): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_text"])
        ),
        vol.Optional(CONF_COMMUTE_DISTANCE): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_text", "input_number"])
        ),
        vol.Optional(CONF_COMMUTE_TIME): EntitySelector(
            EntitySelectorConfig(domain=["sensor", "input_text"])
        ),
    }


def _person_values(defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults = defaults or {}
    values: dict[str, Any] = {}
    name = _get(defaults, "name", None) or _get(defaults, CONF_PERSON_NAME, None)
    if name:
        values[CONF_PERSON_NAME] = name
    person = _get(defaults, CONF_PERSON, None)
    if person:
        values[CONF_PERSON] = person
    commute = _get(defaults, CONF_COMMUTE_SENSOR, None)
    if isinstance(commute, list):
        commute = commute[0] if commute else None
    if commute:
        values[CONF_COMMUTE_SENSOR] = commute
    for key in (
        CONF_ACTIVITY_SENSOR,
        CONF_ADDR_SENSOR,
        CONF_COMMUTE_DISTANCE,
        CONF_COMMUTE_TIME,
    ):
        val = _get(defaults, key, None)
        if val:
            values[key] = val
    return values


def _normalize_person(src: dict[str, Any]) -> dict[str, Any]:
    commute = src.get(CONF_COMMUTE_SENSOR) or None
    if isinstance(commute, list):
        commute = commute[0] if commute else None
    out = {
        "name": src[CONF_PERSON_NAME],
        CONF_PERSON: src[CONF_PERSON],
        CONF_ACTIVITY_SENSOR: src.get(CONF_ACTIVITY_SENSOR) or None,
        CONF_ADDR_SENSOR: src.get(CONF_ADDR_SENSOR) or None,
        CONF_COMMUTE_SENSOR: commute,
        CONF_COMMUTE_DISTANCE: src.get(CONF_COMMUTE_DISTANCE) or None,
        CONF_COMMUTE_TIME: src.get(CONF_COMMUTE_TIME) or None,
    }
    for key in (*HOME_RULE_KEYS, *WORK_RULE_KEYS):
        if key in src and src[key] not in (None, ""):
            out[key] = src[key]
    return out


class HomeTimeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._household: dict[str, Any] = {}
        self._people: list[dict[str, Any]] = []
        self._pending_person: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_shared_fields(include_name=True, hass=self.hass)),
                    _shared_values({}, include_name=True, hass=self.hass),
                ),
            )
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._household = {
            CONF_NAME: user_input[CONF_NAME],
            **_shared_options(user_input),
        }
        return await self.async_step_person()

    async def async_step_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="person",
                data_schema=vol.Schema(_person_fields()),
            )
        person = _normalize_person(user_input)
        trackers = {p[CONF_PERSON] for p in self._people}
        if person[CONF_PERSON] in trackers:
            errors["base"] = "already_person"
            return self.async_show_form(
                step_id="person",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_person_fields()), user_input
                ),
                errors=errors,
            )
        self._pending_person = person
        return await self.async_step_home_rules()

    async def async_step_home_rules(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        pending = self._pending_person or {}
        if user_input is None:
            return self.async_show_form(
                step_id="home_rules",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_home_rules_schema(self.hass, pending)),
                    _suggested_home_rules(pending),
                ),
            )
        errors = _channel_errors(user_input, _HOME_CHANNELS)
        if errors:
            return self.async_show_form(
                step_id="home_rules",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_home_rules_schema(self.hass, {**pending, **user_input})),
                    user_input,
                ),
                errors=errors,
            )
        person = {**pending, **_normalize_home_rules(user_input)}
        self._pending_person = None
        self._people.append(person)
        return self._finish_setup()

    def _finish_setup(self) -> ConfigFlowResult:
        name = self._household.pop(CONF_NAME)
        return self.async_create_entry(
            title=name,
            data={CONF_NAME: name},
            options={**self._household, CONF_PEOPLE: self._people},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HomeTimeOptionsFlow()


class HomeTimeOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._edit_id: str | None = None
        self._pending_person: dict[str, Any] | None = None
        self._work_id: str | None = None
        self._home_id: str | None = None

    def _entry_fallback(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "global",
                "household",
                "edit_work",
                "add_person",
                "edit_person",
                "remove_person",
            ],
        )

    async def async_step_global(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = self._entry_fallback()
        if user_input is not None:
            options = {**self.config_entry.options}
            options.update(_shared_options(user_input, self.config_entry.options))
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="global",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_shared_fields(defaults=current, hass=self.hass)),
                _shared_values(current, hass=self.hass),
            ),
        )

    async def async_step_household(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
        if not people:
            return self.async_abort(reason="no_people")
        if user_input is None:
            options = [
                {"value": p[CONF_PERSON], "label": p.get("name") or p[CONF_PERSON]}
                for p in people
            ]
            return self.async_show_form(
                step_id="household",
                data_schema=vol.Schema(
                    {
                        vol.Required("person"): SelectSelector(
                            SelectSelectorConfig(options=options)
                        )
                    }
                ),
            )
        if CONF_NOTIFY_ARRIVE in user_input:
            errors = _channel_errors(user_input, _HOME_CHANNELS)
            if errors:
                return self.async_show_form(
                    step_id="household_form",
                    data_schema=self.add_suggested_values_to_schema(
                        vol.Schema(_home_rules_schema(self.hass, user_input)),
                        user_input,
                    ),
                    errors=errors,
                )
            home_id = self._home_id
            rules = _normalize_home_rules(user_input)
            people = [
                {**p, **rules} if p.get(CONF_PERSON) == home_id else p for p in people
            ]
            options = {**self.config_entry.options, CONF_PEOPLE: people}
            return self.async_create_entry(title="", data=options)
        self._home_id = user_input["person"]
        current = next((p for p in people if p.get(CONF_PERSON) == self._home_id), {})
        return self.async_show_form(
            step_id="household_form",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    _home_rules_schema(
                        self.hass, {**self._entry_fallback(), **current}
                    )
                ),
                _suggested_home_rules(current, self._entry_fallback()),
            ),
        )

    async def async_step_household_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
            current = next(
                (p for p in people if p.get(CONF_PERSON) == self._home_id), {}
            )
            if not current:
                return await self.async_step_household()
            return self.async_show_form(
                step_id="household_form",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(
                        _home_rules_schema(
                            self.hass, {**self._entry_fallback(), **current}
                        )
                    ),
                    _suggested_home_rules(current, self._entry_fallback()),
                ),
            )
        return await self.async_step_household(user_input)

    async def async_step_add_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="add_person",
                data_schema=vol.Schema(_person_fields()),
            )
        person = _normalize_person(user_input)
        people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
        if person[CONF_PERSON] in {p.get(CONF_PERSON) for p in people}:
            errors["base"] = "already_person"
            return self.async_show_form(
                step_id="add_person",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_person_fields()), user_input
                ),
                errors=errors,
            )
        self._pending_person = person
        return await self.async_step_add_home_rules()

    async def async_step_add_home_rules(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        pending = self._pending_person or {}
        if user_input is None:
            return self.async_show_form(
                step_id="add_home_rules",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(
                        _home_rules_schema(
                            self.hass, {**self._entry_fallback(), **pending}
                        )
                    ),
                    _suggested_home_rules(pending, self._entry_fallback()),
                ),
            )
        errors = _channel_errors(user_input, _HOME_CHANNELS)
        if errors:
            return self.async_show_form(
                step_id="add_home_rules",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(
                        _home_rules_schema(
                            self.hass,
                            {**self._entry_fallback(), **pending, **user_input},
                        )
                    ),
                    user_input,
                ),
                errors=errors,
            )
        person = {**pending, **_normalize_home_rules(user_input)}
        self._pending_person = None
        people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
        people.append(person)
        options = {**self.config_entry.options, CONF_PEOPLE: people}
        return self.async_create_entry(title="", data=options)

    async def async_step_edit_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
        if not people:
            return self.async_abort(reason="no_people")
        if user_input is None:
            options = [
                {"value": p[CONF_PERSON], "label": p.get("name") or p[CONF_PERSON]}
                for p in people
            ]
            return self.async_show_form(
                step_id="edit_person",
                data_schema=vol.Schema(
                    {
                        vol.Required("person"): SelectSelector(
                            SelectSelectorConfig(options=options)
                        )
                    }
                ),
            )
        if CONF_PERSON_NAME in user_input:
            person = _normalize_person(user_input)
            edit_id = self._edit_id
            existing = next((p for p in people if p.get(CONF_PERSON) == edit_id), {})
            for key in (*HOME_RULE_KEYS, *WORK_RULE_KEYS):
                if key not in person and key in existing:
                    person[key] = existing[key]
            if person[CONF_PERSON] != edit_id:
                others = {
                    p.get(CONF_PERSON)
                    for p in people
                    if p.get(CONF_PERSON) != edit_id
                }
                if person[CONF_PERSON] in others:
                    return self.async_show_form(
                        step_id="edit_form",
                        data_schema=self.add_suggested_values_to_schema(
                            vol.Schema(_person_fields()),
                            user_input,
                        ),
                        errors={"base": "already_person"},
                    )
            people = [
                person if p.get(CONF_PERSON) == edit_id else p for p in people
            ]
            options = {**self.config_entry.options, CONF_PEOPLE: people}
            return self.async_create_entry(title="", data=options)
        self._edit_id = user_input["person"]
        current = next((p for p in people if p.get(CONF_PERSON) == self._edit_id), {})
        return self.async_show_form(
            step_id="edit_form",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_person_fields()),
                _person_values(current),
            ),
        )

    async def async_step_edit_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
            current = next(
                (
                    p
                    for p in people
                    if p.get(CONF_PERSON) == self._edit_id
                ),
                {},
            )
            if not current:
                return await self.async_step_edit_person()
            return self.async_show_form(
                step_id="edit_form",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_person_fields()),
                    _person_values(current),
                ),
            )
        return await self.async_step_edit_person(user_input)

    async def async_step_edit_work(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
        if not people:
            return self.async_abort(reason="no_people")
        if user_input is None:
            options = [
                {"value": p[CONF_PERSON], "label": p.get("name") or p[CONF_PERSON]}
                for p in people
            ]
            return self.async_show_form(
                step_id="edit_work",
                data_schema=vol.Schema(
                    {
                        vol.Required("person"): SelectSelector(
                            SelectSelectorConfig(options=options)
                        )
                    }
                ),
            )
        if CONF_STANDARD_HOURS in user_input:
            errors = _channel_errors(user_input, _WORK_CHANNELS)
            if errors:
                return self.async_show_form(
                    step_id="edit_work_form",
                    data_schema=self.add_suggested_values_to_schema(
                        vol.Schema(_work_rules_schema(self.hass, user_input)),
                        user_input,
                    ),
                    errors=errors,
                )
            work_id = self._work_id
            rules = _normalize_work_rules(user_input)
            people = [
                {**p, **rules} if p.get(CONF_PERSON) == work_id else p for p in people
            ]
            options = {**self.config_entry.options, CONF_PEOPLE: people}
            return self.async_create_entry(title="", data=options)
        self._work_id = user_input["person"]
        current = next((p for p in people if p.get(CONF_PERSON) == self._work_id), {})
        return self.async_show_form(
            step_id="edit_work_form",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    _work_rules_schema(
                        self.hass, {**self._entry_fallback(), **current}
                    )
                ),
                _suggested_work_rules(current, self._entry_fallback()),
            ),
        )

    async def async_step_edit_work_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
            current = next(
                (p for p in people if p.get(CONF_PERSON) == self._work_id), {}
            )
            if not current:
                return await self.async_step_edit_work()
            return self.async_show_form(
                step_id="edit_work_form",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(
                        _work_rules_schema(
                            self.hass, {**self._entry_fallback(), **current}
                        )
                    ),
                    _suggested_work_rules(current, self._entry_fallback()),
                ),
            )
        return await self.async_step_edit_work(user_input)

    async def async_step_remove_person(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        people = list(self.config_entry.options.get(CONF_PEOPLE) or [])
        if not people:
            return self.async_abort(reason="no_people")
        if user_input is not None:
            tracker = user_input["person"]
            people = [p for p in people if p.get(CONF_PERSON) != tracker]
            options = deepcopy(dict(self.config_entry.options))
            options[CONF_PEOPLE] = people
            return self.async_create_entry(title="", data=options)
        options = [
            {"value": p[CONF_PERSON], "label": p.get("name") or p[CONF_PERSON]}
            for p in people
        ]
        return self.async_show_form(
            step_id="remove_person",
            data_schema=vol.Schema(
                {
                    vol.Required("person"): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )
