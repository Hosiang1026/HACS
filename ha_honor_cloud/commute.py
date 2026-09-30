from __future__ import annotations

import logging
import re
from math import atan2, cos, sin, sqrt
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client, entity_registry as er
from homeassistant.util import slugify

from .const import (
    ACTIVITY_BIKE,
    ACTIVITY_DRIVE,
    COMMUTE_BIKE_MAX_KM,
    COMMUTE_MODE_BICYCLING,
    COMMUTE_MODE_DRIVING,
    CONF_ACTIVITY_ENTITY,
    CONF_COMMUTE_ENABLED,
    CONF_COMMUTE_ZONES,
    DEFAULT_ACTIVITY_ENTITY,
    DEFAULT_COMMUTE_ENABLED,
    DEFAULT_COMMUTE_ZONES,
    DOMAIN,
    HOME_EXIT_BUFFER_M,
)

_LOGGER = logging.getLogger(__name__)
_AMAP_TRAFFIC_RANK = {"缓行": 1, "拥堵": 2, "严重拥堵": 3}
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = lat1 * 0.0174532925
    p2 = lat2 * 0.0174532925
    dlat = (lat2 - lat1) * 0.0174532925
    dlon = (lon2 - lon1) * 0.0174532925
    a = (sin(dlat / 2) ** 2) + cos(p1) * cos(p2) * (sin(dlon / 2) ** 2)
    return 6371000 * 2 * atan2(sqrt(a), sqrt(1 - a))


def _amap_grid(lng: float, lat: float) -> tuple[int, int]:
    return int(round(lng * 278)), int(round(lat * 278))


def _identity_tokens(text: str) -> set[str]:
    raw = (text or "").strip()
    if not raw:
        return set()
    tokens: set[str] = set()
    cjk = "".join(_CJK_RE.findall(raw))
    if cjk:
        tokens.add(cjk)
    slug = slugify(raw)
    if slug:
        for part in slug.split("_"):
            if part and len(part) > 1:
                tokens.add(part)
    return tokens


def _token_score(left: set[str], right: set[str]) -> int:
    score = 0
    for item in left:
        for other in right:
            if item == other:
                score += len(item)
            elif len(item) >= 2 and len(other) >= 2 and (item in other or other in item):
                score += min(len(item), len(other))
    return score


def _mode_from_activity(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    value = str(state.state or "").strip()
    if value in ACTIVITY_BIKE:
        return COMMUTE_MODE_BICYCLING
    if value in ACTIVITY_DRIVE:
        return COMMUTE_MODE_DRIVING
    return None


def _id_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]


def _amap_traffic(path: dict[str, Any]) -> str | None:
    found = None
    rank = 0
    for step in path.get("steps") or []:
        if not isinstance(step, dict):
            continue
        status = str(step.get("tmc_status") or step.get("status") or "").strip()
        level = _AMAP_TRAFFIC_RANK.get(status, 0)
        if level > rank:
            rank = level
            found = status
    return found


async def _amap_route_async(
    session: aiohttp.ClientSession,
    key: str,
    mode: str,
    olng: float,
    olat: float,
    dlng: float,
    dlat: float,
) -> tuple[float, int, str | None] | None:
    bike = mode == COMMUTE_MODE_BICYCLING
    endpoint = (
        "https://restapi.amap.com/v5/direction/electrobike"
        if bike
        else "https://restapi.amap.com/v5/direction/driving"
    )
    try:
        async with session.get(
            endpoint,
            params={
                "key": key,
                "origin": f"{olng:.6f},{olat:.6f}",
                "destination": f"{dlng:.6f},{dlat:.6f}",
                "show_fields": "cost" if bike else "cost,tmcs",
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return None
    if str(data.get("status")) != "1":
        return None
    paths = (data.get("route") or {}).get("paths") or []
    if not paths or not isinstance(paths[0], dict):
        return None
    path = paths[0]
    cost = path.get("cost") if isinstance(path.get("cost"), dict) else {}
    try:
        meters = float(path.get("distance") or 0)
        seconds = float(cost.get("duration") or 0)
    except (TypeError, ValueError):
        return None
    steps = path.get("steps") or []
    first = steps[0] if steps and isinstance(steps[0], dict) else None
    info = str(first.get("instruction") or "").strip() if first else None
    if not bike:
        traffic = _amap_traffic(path)
        if traffic:
            info = f"{info} · {traffic}" if info else traffic
    minutes = 0 if meters < 50 else max(1, int(round(seconds / 60)))
    return round(meters / 1000, 2), minutes, info or None


def _home_zones(hass: HomeAssistant, zone_ids: list[str]) -> list[tuple[str, str, float, float, float]]:
    result: list[tuple[str, str, float, float, float]] = []
    for entity_id in zone_ids:
        state = hass.states.get(entity_id)
        if state is None:
            continue
        lat = state.attributes.get("latitude")
        lon = state.attributes.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            radius = float(state.attributes.get("radius") or 100)
        except (TypeError, ValueError):
            radius = 100.0
        name = state.attributes.get("friendly_name") or entity_id
        result.append((entity_id, str(name), float(lat), float(lon), radius))
    return result


def _device_tokens(hass: HomeAssistant, device_id: str, name: str, model: str) -> set[str]:
    tokens = _identity_tokens(name) | _identity_tokens(model)
    tracker_id = er.async_get(hass).async_get_entity_id(
        "device_tracker", DOMAIN, f"{DOMAIN}:{device_id}"
    )
    tracker_ids = {tracker_id} if tracker_id else set()
    if not tracker_ids:
        return tokens
    for state in hass.states.async_all("person"):
        trackers = state.attributes.get("device_trackers") or []
        if not any(item in tracker_ids for item in trackers):
            continue
        tokens |= _identity_tokens(state.name)
        tokens |= _identity_tokens(state.entity_id.split(".", 1)[-1])
        tokens |= _identity_tokens(str(state.attributes.get("friendly_name") or ""))
    return tokens


def _activity_mode(hass: HomeAssistant, device_id: str, name: str, model: str, entity_ids: list[str]) -> str | None:
    if not entity_ids:
        return None
    tokens = _device_tokens(hass, device_id, name, model)
    best_id = None
    best_score = 0
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        if state is None:
            continue
        score = _token_score(
            tokens,
            _identity_tokens(entity_id.split(".", 1)[-1])
            | _identity_tokens(state.name)
            | _identity_tokens(str(state.attributes.get("friendly_name") or "")),
        )
        if score > best_score:
            best_score = score
            best_id = entity_id
    if best_id is None:
        return None
    return _mode_from_activity(hass, best_id)


async def _apply_commute(
    coordinator: Any,
    session: aiohttp.ClientSession,
    key: str,
    bucket: dict[str, Any],
    wgs_lat: float,
    wgs_lng: float,
    mode: str | None,
    zones: list[tuple[str, str, float, float, float]],
) -> bool:
    from .device_tracker import wgs84_to_gcj02

    inside = None
    inside_dist = None
    best = None
    best_dist = None
    for zone in zones:
        meters = _haversine_m(wgs_lat, wgs_lng, zone[2], zone[3])
        leave_limit = zone[4] + (HOME_EXIT_BUFFER_M if bucket["inside"] else 0)
        if meters <= leave_limit and (inside_dist is None or meters < inside_dist):
            inside = zone
            inside_dist = meters
        if best_dist is None or meters < best_dist:
            best_dist = meters
            best = zone

    if inside is not None:
        bucket["inside"] = True
        bucket["distance"] = 0.0
        bucket["time"] = 0
        bucket["info"] = inside[1]
        bucket["route_key"] = None
        bucket["mode"] = None
        return True

    bucket["inside"] = False
    if best is None:
        return False
    if mode is None:
        mode = (
            COMMUTE_MODE_BICYCLING
            if (best_dist or 0) < COMMUTE_BIKE_MAX_KM * 1000
            else COMMUTE_MODE_DRIVING
        )
    olng, olat = wgs84_to_gcj02(wgs_lng, wgs_lat)
    dlng, dlat = wgs84_to_gcj02(best[3], best[2])
    route_key = (*_amap_grid(olng, olat), *_amap_grid(dlng, dlat), mode)
    if route_key == bucket["route_key"] and bucket["distance"] is not None:
        bucket["mode"] = mode
        return True
    coordinator._roll_usage_day()
    if coordinator._amap_count >= coordinator._get_amap_daily_limit():
        return False
    route = await _amap_route_async(session, key, mode, olng, olat, dlng, dlat)
    if route is None:
        _LOGGER.warning("[Commute] 路径规划失败")
        return False
    coordinator.bump_amap_count()
    bucket["route_key"] = route_key
    bucket["mode"] = mode
    distance_km, minutes, info = route
    bucket["distance"] = distance_km
    bucket["time"] = minutes
    bucket["info"] = info or best[1]
    return True


async def update_commute(coordinator: Any, devices: list[dict[str, Any]]) -> None:
    from .device_tracker import _get_stable_device_id

    options = coordinator.entry.options or {}
    if not bool(options.get(CONF_COMMUTE_ENABLED, DEFAULT_COMMUTE_ENABLED)):
        return
    if not coordinator._amap_enabled():
        return
    key = coordinator._get_amap_api_key()
    if not key:
        return

    zones = _home_zones(
        coordinator.hass,
        _id_list(options.get(CONF_COMMUTE_ZONES, DEFAULT_COMMUTE_ZONES)),
    )
    if not zones:
        return

    activity_ids = [
        entity_id
        for entity_id in _id_list(options.get(CONF_ACTIVITY_ENTITY, DEFAULT_ACTIVITY_ENTITY))
        if coordinator.hass.states.get(entity_id) is not None
    ]
    session = aiohttp_client.async_get_clientsession(coordinator.hass)
    for device in devices:
        device_id = _get_stable_device_id(device)
        if not device_id:
            continue
        try:
            wgs_lat = float(device["latitude"])
            wgs_lng = float(device["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        bucket = coordinator._commute_bucket(device_id)
        name = str(device.get("deviceAliasName") or device.get("name") or "")
        model = str(device.get("model") or "")
        mode = _activity_mode(coordinator.hass, device_id, name, model, activity_ids)
        moved = bucket["last_lat"] != wgs_lat or bucket["last_lon"] != wgs_lng
        empty = bucket["distance"] is None and not bucket["info"]
        mode_changed = mode is not None and bucket.get("mode") not in (None, mode)
        if not (moved or empty or mode_changed or bucket["pending"]):
            continue
        try:
            ok = await _apply_commute(
                coordinator, session, key, bucket, wgs_lat, wgs_lng, mode, zones
            )
        except Exception as err:
            _LOGGER.warning("[Commute] 更新失败: %s", err)
            ok = False
        if not ok:
            bucket["pending"] = True
            continue
        bucket["pending"] = False
        bucket["last_lat"] = wgs_lat
        bucket["last_lon"] = wgs_lng
