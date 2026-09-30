from __future__ import annotations

from copy import deepcopy
from typing import Any

from .const import (
    CONF_ANNOUNCE,
    CONF_ANNOUNCE_ENABLED,
    CONF_API_HOST,
    CONF_API_KEY,
    CONF_DISTRICT,
    CONF_ENABLED,
    CONF_FORECAST_DAYS,
    CONF_INDICES_ENABLED,
    CONF_INSTANCES,
    CONF_INTERVAL,
    CONF_LOCATION,
    CONF_NAME,
    CONF_NOTIFY,
    CONF_NOTIFY_ALARM,
    CONF_NOTIFY_ALARM_ANNOUNCE,
    CONF_NOTIFY_ALARM_NOTIFY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_END,
    CONF_NOTIFY_RAIN,
    CONF_NOTIFY_RAIN_ANNOUNCE,
    CONF_NOTIFY_RAIN_NOTIFY,
    CONF_NOTIFY_START,
    CONF_PROVIDER,
    CONF_SLUG,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_NOTIFY_END,
    DEFAULT_NOTIFY_START,
    DEFAULT_WEATHER_INTERVAL,
    PROVIDER_TIANQI,
)


def _notify_block(enabled: bool = False) -> dict[str, Any]:
    return {
        CONF_NOTIFY_ENABLED: enabled,
        CONF_NOTIFY_START: DEFAULT_NOTIFY_START,
        CONF_NOTIFY_END: DEFAULT_NOTIFY_END,
        CONF_ANNOUNCE_ENABLED: False,
    }


def default_options() -> dict[str, Any]:
    return {
        CONF_ENABLED: True,
        **_notify_block(False),
        CONF_NOTIFY_ALARM: True,
        CONF_NOTIFY_RAIN: True,
        CONF_INSTANCES: [],
    }


def _module_notify(options: dict[str, Any]) -> dict[str, Any]:
    alarm_notify = (
        options[CONF_NOTIFY_ALARM_NOTIFY]
        if CONF_NOTIFY_ALARM_NOTIFY in options
        else options.get(CONF_NOTIFY) or []
    )
    alarm_announce = (
        options[CONF_NOTIFY_ALARM_ANNOUNCE]
        if CONF_NOTIFY_ALARM_ANNOUNCE in options
        else options.get(CONF_ANNOUNCE)
    )
    rain_notify = (
        options[CONF_NOTIFY_RAIN_NOTIFY]
        if CONF_NOTIFY_RAIN_NOTIFY in options
        else options.get(CONF_NOTIFY) or []
    )
    rain_announce = (
        options[CONF_NOTIFY_RAIN_ANNOUNCE]
        if CONF_NOTIFY_RAIN_ANNOUNCE in options
        else options.get(CONF_ANNOUNCE)
    )
    return {
        CONF_NOTIFY_ENABLED: options.get(CONF_NOTIFY_ENABLED, False),
        CONF_NOTIFY_START: options.get(CONF_NOTIFY_START, DEFAULT_NOTIFY_START),
        CONF_NOTIFY_END: options.get(CONF_NOTIFY_END, DEFAULT_NOTIFY_END),
        CONF_NOTIFY_ALARM: options.get(CONF_NOTIFY_ALARM, True),
        CONF_NOTIFY_ALARM_NOTIFY: alarm_notify or [],
        CONF_NOTIFY_ALARM_ANNOUNCE: alarm_announce,
        CONF_NOTIFY_RAIN: options.get(CONF_NOTIFY_RAIN, True),
        CONF_NOTIFY_RAIN_NOTIFY: rain_notify or [],
        CONF_NOTIFY_RAIN_ANNOUNCE: rain_announce,
    }


def merge_options(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_options()
    if not raw:
        return base
    out = deepcopy(base)
    for key, val in raw.items():
        if key in out and isinstance(val, dict) and isinstance(out[key], dict):
            merged = deepcopy(out[key])
            merged.update(val)
            out[key] = merged
        else:
            out[key] = val
    inherited = _module_notify(out)
    cities: list[dict[str, Any]] = []
    for inst in out.get(CONF_INSTANCES) or []:
        item = dict(inst)
        for key, val in inherited.items():
            if key not in item:
                item[key] = val
        cities.append(item)
    out[CONF_INSTANCES] = cities
    return out


def default_weather_instance() -> dict[str, Any]:
    return {
        CONF_NAME: "杭州",
        CONF_SLUG: "hangzhou",
        CONF_PROVIDER: PROVIDER_TIANQI,
        CONF_LOCATION: "101210101",
        CONF_DISTRICT: "",
        CONF_INTERVAL: DEFAULT_WEATHER_INTERVAL,
        CONF_FORECAST_DAYS: DEFAULT_FORECAST_DAYS,
        CONF_INDICES_ENABLED: True,
        CONF_API_KEY: "",
        CONF_API_HOST: "",
        CONF_NOTIFY_ENABLED: False,
        CONF_NOTIFY_START: DEFAULT_NOTIFY_START,
        CONF_NOTIFY_END: DEFAULT_NOTIFY_END,
        CONF_NOTIFY_ALARM: True,
        CONF_NOTIFY_ALARM_NOTIFY: [],
        CONF_NOTIFY_ALARM_ANNOUNCE: None,
        CONF_NOTIFY_RAIN: True,
        CONF_NOTIFY_RAIN_NOTIFY: [],
        CONF_NOTIFY_RAIN_ANNOUNCE: None,
    }
