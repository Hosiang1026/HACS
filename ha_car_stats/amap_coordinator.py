from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import math
import random
import re
import time
import urllib.parse
from typing import Any

import requests
from homeassistant.components.persistent_notification import async_create, async_dismiss
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance

from .amap_fetcher import AmapDataFetcher, AmapSessionExpired
from .const import (
    CONF_ADDRESS_DISTANCE,
    CONF_ADDRESSAPI_KEY,
    CONF_AMAP_KEY,
    CONF_AMAP_LOGIN_AT,
    CONF_AMAP_PARAMDATA,
    CONF_AMAP_SESSIONID,
    CONF_AMAP_TID,
    CONF_COMMUTE_INTERVAL,
    CONF_COMMUTE_SPEED,
    CONF_COMMUTE_ZONE,
    CONF_NOTIFY_ARRIVE,
    CONF_NOTIFY_LEAVE,
    CONF_POLL_EXCLUDE_ZONES,
    CONF_PRIVATE_KEY,
    DEFAULT_ADDRESS_DISTANCE,
    DEFAULT_COMMUTE_INTERVAL,
    DEFAULT_COMMUTE_SPEED,
    DOMAIN,
)
from .helpers import (
    cfg_amap_plate,
    cfg_owners,
    cfg_poll_active,
    entry_cfg,
    fmt_duration,
    gcj02towgs84,
    normalize_plate,
    plate_tail_num,
    wgs84togcj02,
)
from .notify import send_notify

_LOGGER = logging.getLogger(__name__)


class AmapGpsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        active = cfg_poll_active(entry)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_amap",
            update_interval=datetime.timedelta(minutes=active),
            config_entry=entry,
        )
        data = entry.data
        self.tid = str(data[CONF_AMAP_TID])
        self._fetcher = AmapDataFetcher(
            hass,
            data[CONF_AMAP_KEY],
            data[CONF_AMAP_SESSIONID],
            data[CONF_AMAP_PARAMDATA],
            self.tid,
            entry.entry_id,
        )
        self._fetcher.on_api_call = self._bump_api_call
        self._coords: list[float] | None = None
        self._coords_old: list[float] = [0, 0]
        self._address = ""
        self._commute: dict[str, Any] = {}
        self._navi_active = False
        self._trip_toll = 0.0
        self._api_calls = 0
        self._api_calls_date = ""
        self._navi_dest_boost = False
        self._notify_prev: dict[str, Any] | None = None
        self._owner_boost = False
        self._confirm_offline = False
        self._session_expired_notified = False
        self._session_notice_cleared = False
        self._owner_in_exclude: bool | None = None
        self._unsub_owners = None
        self._owner_radius = 300
        entry.async_on_unload(self._cleanup_owners)
        entry.async_on_unload(self.async_shutdown)
        entry.async_on_unload(
            async_track_time_change(hass, self.async_reset_daily_calls, hour=0, minute=0, second=0)
        )

    def _cleanup_owners(self) -> None:
        if self._unsub_owners:
            self._unsub_owners()
            self._unsub_owners = None

    def setup_owner_tracking(self) -> None:
        self._cleanup_owners()
        owners = cfg_owners(self.entry)
        if not owners:
            return
        self._owner_in_exclude = self._any_owner_in_exclude_zones()
        self._unsub_owners = async_track_state_change_event(self.hass, owners, self._async_owners_updated)

    def apply_entry(self, entry: ConfigEntry) -> None:
        self.entry = entry
        self.update_interval = datetime.timedelta(minutes=cfg_poll_active(entry))
        self.setup_owner_tracking()

    @callback
    def _async_owners_updated(self, _event) -> None:
        self.hass.async_create_task(self._handle_owner_change())

    async def _handle_owner_change(self) -> None:
        was_boost = self._owner_boost
        was_in_ex = self._owner_in_exclude
        now_in_ex = self._any_owner_in_exclude_zones()
        self._owner_in_exclude = now_in_ex
        boost = self._owner_should_boost()
        if boost != was_boost:
            if was_boost and not boost:
                self._confirm_offline = True
            self._apply_poll_interval()
            await self.async_request_refresh()
            return
        if was_in_ex is True and not now_in_ex and self._is_offline():
            await self.async_request_refresh()
            self._apply_poll_interval()

    async def _async_update_data(self) -> dict[str, Any]:
        await self._fetcher.async_ensure_persisted()
        self._load_persisted_extras()
        self._ensure_api_calls_day()
        try:
            raw = await self._fetcher.get_data()
        except AmapSessionExpired:
            self._notify_session_expired()
            self.update_interval = None
            kept = self._keep_or_fallback()
            if kept:
                await self._persist_extras(kept)
                return kept
            raise UpdateFailed("高德车机会话过期") from None
        except Exception as err:
            kept = self._keep_or_fallback()
            if kept:
                _LOGGER.warning("amap update failed, keep last: %s", err)
                self._attach_api_calls(kept)
                self._apply_poll_interval(kept)
                await self._persist_extras(kept)
                return kept
            raise UpdateFailed(str(err)) from err
        if not raw:
            kept = self._keep_or_fallback()
            if kept:
                self._attach_api_calls(kept)
                self._apply_poll_interval(kept)
                await self._persist_extras(kept)
                return kept
            raise UpdateFailed("amap no data")
        item = {**raw, "attrs": dict(raw.get("attrs") or {})}
        lon, lat = gcj02towgs84(item["thislon"], item["thislat"])
        item["thislon"], item["thislat"] = lon, lat
        self._coords = [lon, lat]
        self._apply_plate_tail(item)
        await self._maybe_update_address(item)
        await self._maybe_update_commute(item)
        await self._maybe_record_navi_toll(item)
        await self._check_and_notify(item)
        self._update_navi_dest_boost(item)
        self._attach_api_calls(item)
        await self._persist_extras(item)
        self._ensure_login_at()
        self._clear_session_notice()
        self._apply_poll_interval(item)
        return item

    def _session_notice_id(self) -> str:
        return f"{DOMAIN}_amap_session_{self.entry.entry_id}"

    def _notify_session_expired(self) -> None:
        if self._session_expired_notified:
            return
        self._session_expired_notified = True
        name = self.entry.title or "车辆"
        _LOGGER.warning("amap session expired: %s", name)
        async_create(
            self.hass,
            f"{name} 的高德车机会话已过期，定位已停止更新。请到该车辆选项「高德凭证」重新填写 sessionid。",
            title="高德车机会话过期",
            notification_id=self._session_notice_id(),
        )

    def _clear_session_notice(self) -> None:
        if self._session_notice_cleared and not self._session_expired_notified:
            return
        self._session_expired_notified = False
        self._session_notice_cleared = True
        async_dismiss(self.hass, self._session_notice_id())

    def _ensure_login_at(self) -> None:
        if self.entry.data.get(CONF_AMAP_LOGIN_AT):
            return
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_AMAP_LOGIN_AT: dt_util.now().isoformat()},
        )

    def _today(self) -> str:
        return dt_util.now().date().isoformat()

    def _ensure_api_calls_day(self) -> bool:
        today = self._today()
        if self._api_calls_date == today:
            return False
        self._api_calls = 0
        self._api_calls_date = today
        return True

    def _bump_api_call(self) -> None:
        self._ensure_api_calls_day()
        self._api_calls = int(self._api_calls or 0) + 1

    def _attach_api_calls(self, item: dict[str, Any]) -> None:
        item.setdefault("attrs", {})["api_calls"] = int(self._api_calls or 0)

    async def async_reset_daily_calls(self, _now=None) -> None:
        if not self._ensure_api_calls_day():
            return
        item = None
        if self.data:
            item = {**self.data, "attrs": dict(self.data.get("attrs") or {})}
            self._attach_api_calls(item)
            self.async_set_updated_data(item)
        await self._persist_extras(item)

    def _keep_or_fallback(self) -> dict[str, Any] | None:
        self._load_persisted_extras()
        if self.data:
            return self.data
        return self._fallback_item()

    def _fallback_item(self) -> dict[str, Any] | None:
        persisted = getattr(self._fetcher, "_persisted", None) or {}
        last = persisted.get("last_item")
        if not isinstance(last, dict):
            return None
        try:
            lat = float(last.get("thislat"))
            lon = float(last.get("thislon"))
        except (TypeError, ValueError):
            return None
        attrs = dict(last.get("attrs") or {})
        vd = self._fetcher.vardata or {}
        if not attrs.get("querytime") and vd.get("querytime"):
            attrs["querytime"] = vd["querytime"]
        item = {
            "thislat": lat,
            "thislon": lon,
            "accuracy": last.get("accuracy") or 0,
            "imei": last.get("imei") or self.tid,
            "status": last.get("status") or "unknown",
            "attrs": attrs,
            "deviceinfo": last.get("deviceinfo") or {},
        }
        self._coords = [lon, lat]
        self._apply_plate_tail(item)
        if self._address:
            item["attrs"]["address"] = self._address
        if self._commute.get("distance") is not None:
            item["attrs"]["commute_distance"] = self._commute["distance"]
            item["attrs"]["commute_time"] = self._commute.get("time")
            if self._commute.get("tolls") is not None:
                item["attrs"]["commute_toll"] = self._commute["tolls"]
            if self._commute.get("traffic_lights") is not None:
                item["attrs"]["traffic_lights"] = self._commute["traffic_lights"]
        return item

    def _load_persisted_extras(self) -> None:
        if getattr(self, "_extras_loaded", False):
            return
        self._extras_loaded = True
        persisted = getattr(self._fetcher, "_persisted", None) or {}
        if not self._commute and isinstance(persisted.get("commute"), dict):
            self._commute = dict(persisted["commute"])
        if not self._address and persisted.get("address"):
            self._address = str(persisted["address"])
        self._navi_active = bool(persisted.get("navi_active"))
        try:
            self._trip_toll = float(persisted.get("trip_toll") or 0)
        except (TypeError, ValueError):
            self._trip_toll = 0.0
        try:
            self._api_calls = int(persisted.get("api_calls") or 0)
        except (TypeError, ValueError):
            self._api_calls = 0
        self._api_calls_date = str(persisted.get("api_calls_date") or "")
        self._ensure_api_calls_day()
        self._navi_dest_boost = bool(persisted.get("navi_dest_boost"))

    async def _persist_extras(self, item: dict[str, Any] | None = None) -> None:
        try:
            persisted = dict(getattr(self._fetcher, "_persisted", None) or {})
            persisted["vardata"] = self._fetcher.vardata
            persisted["lastgpstime"] = self._fetcher.lastgpstime.isoformat()
            persisted["timestamp"] = datetime.datetime.now().isoformat()
            persisted["commute"] = dict(self._commute)
            persisted["address"] = self._address
            persisted["navi_active"] = self._navi_active
            persisted["trip_toll"] = self._trip_toll
            persisted["api_calls"] = int(self._api_calls or 0)
            persisted["api_calls_date"] = self._api_calls_date or self._today()
            persisted["navi_dest_boost"] = self._navi_dest_boost
            if item:
                persisted["last_item"] = {
                    "thislat": item.get("thislat"),
                    "thislon": item.get("thislon"),
                    "accuracy": item.get("accuracy") or 0,
                    "imei": item.get("imei"),
                    "status": item.get("status"),
                    "attrs": dict(item.get("attrs") or {}),
                    "deviceinfo": dict(item.get("deviceinfo") or {}),
                }
            self._fetcher._persisted = persisted
            await self._fetcher._store.async_save(persisted)
        except Exception as err:
            _LOGGER.debug("amap extras persist failed: %s", err)

    def _apply_plate_tail(self, item: dict[str, Any]) -> None:
        plate = cfg_amap_plate(self.entry)
        item.setdefault("attrs", {})
        item["attrs"]["restrict_tail"] = plate_tail_num(plate) or "未知"
        item["attrs"]["plate"] = plate or "未知"

    def _cfg(self) -> dict[str, Any]:
        return entry_cfg(self.entry)

    def _zone_ids(self, key: str, default: list[str] | None = None) -> list[str]:
        raw = self._cfg().get(key)
        if raw is None or raw == "":
            return list(default or [])
        if isinstance(raw, str):
            raw = [raw] if raw.strip() else []
        return [str(z).strip() for z in raw if str(z).strip()] or list(default or [])

    def _is_running(self, runorstop: Any) -> bool:
        return runorstop in ("run", "运动")

    def _is_offline(self) -> bool:
        attrs = (self.data or {}).get("attrs") or {}
        return attrs.get("onlinestatus") != "在线"

    def _is_owner_near_car(self) -> bool:
        owners = cfg_owners(self.entry)
        if not owners or not self.data:
            return False
        try:
            clat = float(self.data.get("thislat"))
            clon = float(self.data.get("thislon"))
        except (TypeError, ValueError):
            return False
        for pid in owners:
            state = self.hass.states.get(pid)
            if not state:
                continue
            plat = state.attributes.get("latitude")
            plon = state.attributes.get("longitude")
            if plat is None or plon is None:
                continue
            try:
                if distance(clat, clon, float(plat), float(plon)) <= self._owner_radius:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _in_zones(self, lat: float, lon: float, zone_ids: list[str], prev: bool | None = None) -> bool | None:
        if not zone_ids:
            return None
        extra = 50 if prev is True else 0
        found = False
        for zone_id in zone_ids:
            zone = self.hass.states.get(zone_id)
            if not zone:
                continue
            try:
                zlat = float(zone.attributes.get("latitude"))
                zlon = float(zone.attributes.get("longitude"))
                radius = float(zone.attributes.get("radius") or 100)
            except (TypeError, ValueError):
                continue
            found = True
            if self.get_distance(lat, lon, zlat, zlon) <= radius + extra:
                return True
        return None if not found else False

    def _car_in_exclude_zones(self) -> bool:
        zones = self._zone_ids(CONF_POLL_EXCLUDE_ZONES)
        if not zones or not self.data:
            return False
        try:
            lat = float(self.data.get("thislat"))
            lon = float(self.data.get("thislon"))
        except (TypeError, ValueError):
            return False
        return self._in_zones(lat, lon, zones) is True

    def _any_owner_in_exclude_zones(self) -> bool:
        zones = self._zone_ids(CONF_POLL_EXCLUDE_ZONES)
        if not zones:
            return False
        for pid in cfg_owners(self.entry):
            state = self.hass.states.get(pid)
            if not state:
                continue
            plat = state.attributes.get("latitude")
            plon = state.attributes.get("longitude")
            if plat is None or plon is None:
                continue
            try:
                if self._in_zones(float(plat), float(plon), zones) is True:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _owner_should_boost(self) -> bool:
        return self._is_owner_near_car() and not self._car_in_exclude_zones()

    def _update_navi_dest_boost(self, item: dict[str, Any]) -> None:
        attrs = item.get("attrs") or {}
        navigating = attrs.get("naviStatus") == "导航中"
        if not navigating:
            self._navi_dest_boost = False
            return
        if attrs.get("navi_dest_fresh"):
            self._navi_dest_boost = False
            return
        prev_navi = ((self.data or {}).get("attrs") or {}).get("naviStatus") == "导航中"
        if not prev_navi:
            self._navi_dest_boost = True

    def _apply_poll_interval(self, item: dict[str, Any] | None = None) -> None:
        data = item if item is not None else self.data
        if not data:
            return
        attrs = data.get("attrs") or {}
        online = attrs.get("onlinestatus") == "在线"
        navigating = attrs.get("naviStatus") == "导航中"
        owner_boost = self._owner_should_boost()
        self._owner_boost = owner_boost
        if self._session_expired_notified:
            self.update_interval = None
            return
        active_max = cfg_poll_active(self.entry)
        running = self._is_running(attrs.get("runorstop"))
        driving = navigating or (online and running)
        if owner_boost and not driving:
            self._confirm_offline = False
            self.update_interval = datetime.timedelta(minutes=5)
        elif driving or (self._confirm_offline and online):
            self.update_interval = datetime.timedelta(minutes=5)
        elif online:
            self.update_interval = datetime.timedelta(seconds=random.randint(1, active_max) * 60)
        else:
            self._confirm_offline = False
            self.update_interval = datetime.timedelta(seconds=random.randint(1, 120) * 60)

    def _fmt_duration(self, seconds: int) -> str:
        return fmt_duration(seconds)

    def _calc_parkingtime(self, attrs: dict[str, Any]) -> str:
        laststop = attrs.get("laststoptime")
        if not laststop:
            return attrs.get("parkingtime") or "00:00"
        try:
            stop = datetime.datetime.strptime(str(laststop), "%Y-%m-%d %H:%M:%S")
            if attrs.get("onlinestatus") == "在线" and self._is_running(attrs.get("runorstop")):
                return "00:00"
            return self._fmt_duration(int((datetime.datetime.now() - stop).total_seconds()))
        except (ValueError, TypeError):
            return attrs.get("parkingtime") or "00:00"

    def _calc_drivetime(self, attrs: dict[str, Any]) -> str:
        lastrun = attrs.get("lastruntime")
        laststop = attrs.get("laststoptime")
        if not lastrun:
            return "00:00"
        try:
            start = datetime.datetime.strptime(str(lastrun), "%Y-%m-%d %H:%M:%S")
            now = datetime.datetime.now()
            if start > now:
                return "00:00"
            running = attrs.get("onlinestatus") == "在线" and self._is_running(attrs.get("runorstop"))
            if running:
                return self._fmt_duration(int((now - start).total_seconds()))
            if laststop:
                stop = datetime.datetime.strptime(str(laststop), "%Y-%m-%d %H:%M:%S")
                if stop > start:
                    return self._fmt_duration(int((stop - start).total_seconds()))
            return "00:00"
        except (ValueError, TypeError):
            return "00:00"

    def _home_zone_ids(self) -> list[str]:
        return self._zone_ids(CONF_COMMUTE_ZONE, ["zone.home"]) or ["zone.home"]

    def _in_home_zone(self, item: dict[str, Any], prev: bool | None = None) -> bool | None:
        try:
            lat = float(item.get("thislat"))
            lon = float(item.get("thislon"))
        except (TypeError, ValueError):
            return prev
        return self._in_zones(lat, lon, self._home_zone_ids(), prev)

    async def _check_and_notify(self, item: dict[str, Any]) -> None:
        cfg = self._cfg()
        events = []
        if cfg.get(CONF_NOTIFY_LEAVE):
            events.append("leave")
        if cfg.get(CONF_NOTIFY_ARRIVE):
            events.append("arrive")
        attrs = item.get("attrs") or {}
        new_state = {
            "address": attrs.get("address") or "",
            "querytime": attrs.get("querytime") or "",
            "in_home": self._in_home_zone(item, (self._notify_prev or {}).get("in_home")),
            "parkingtime": self._calc_parkingtime(attrs),
            "drivetime": self._calc_drivetime(attrs),
        }
        old = self._notify_prev
        self._notify_prev = new_state
        if not events or old is None:
            return
        addr = new_state["address"]
        if "leave" in events and old.get("in_home") is True and new_state.get("in_home") is False:
            await send_notify(
                self.hass,
                self.entry,
                "汽车离家通知",
                f"停车时长：{new_state.get('parkingtime')}\n当前位置：{addr}",
                CONF_NOTIFY_LEAVE,
            )
        if "arrive" in events and old.get("in_home") is False and new_state.get("in_home") is True:
            await send_notify(
                self.hass,
                self.entry,
                "汽车到家通知",
                f"开车时长：{new_state.get('drivetime')}\n当前位置：{addr}",
                CONF_NOTIFY_ARRIVE,
            )

    async def _maybe_update_address(self, item: dict[str, Any]) -> None:
        cfg = self._cfg()
        key = cfg.get(CONF_ADDRESSAPI_KEY) or ""
        if not self._coords or not key:
            return
        attrs = item.setdefault("attrs", {})
        driving = self._is_running(attrs.get("runorstop")) and attrs.get("onlinestatus") == "在线"
        if driving and self._address:
            attrs["address"] = self._address
            return
        dist = self.get_distance(self._coords[1], self._coords[0], self._coords_old[1], self._coords_old[0])
        threshold = float(cfg.get(CONF_ADDRESS_DISTANCE) or DEFAULT_ADDRESS_DISTANCE)
        if not self._address or dist > threshold:
            addr = await self._get_address(key, cfg.get(CONF_PRIVATE_KEY) or "")
            if addr:
                self._address = addr
                self._coords_old = list(self._coords)
        if self._address:
            attrs["address"] = self._address

    async def _get_address(self, key: str, private_key: str) -> str:
        if not self._coords or not key:
            return ""
        try:
            async with asyncio.timeout(10):
                gcj = wgs84togcj02(self._coords[0], self._coords[1])
                data = await self.hass.async_add_executor_job(self._gaode_regeo, gcj[1], gcj[0], key, private_key)
                if str(data.get("status")) == "1":
                    return self._format_gaode(data.get("regeocode") or {})
        except Exception as err:
            _LOGGER.debug("address failed: %s", err)
        return ""

    def _format_gaode(self, regeo: dict) -> str:
        fmt = regeo.get("formatted_address")
        if isinstance(fmt, list):
            fmt = ""
        fmt = str(fmt or "").strip()
        if fmt:
            return fmt
        return ""

    def _http_json(self, url: str) -> dict:
        self._bump_api_call()
        text = requests.get(url, timeout=10).content.decode("utf-8")
        text = re.sub(r"\\", "", text)
        text = re.sub(r'"\{', "{", text)
        text = re.sub(r'\}"', "}", text)
        return json.loads(text)

    def _sig(self, params: dict, private_key: str) -> str:
        sorted_params = sorted(params.items(), key=lambda x: x[0])
        param_str = "&".join([f"{k}={v}" for k, v in sorted_params]) + private_key
        return hashlib.md5(param_str.encode()).hexdigest()

    def _gaode_regeo(self, lat: float, lng: float, key: str, private_key: str) -> dict:
        location = f"{lng:.6f},{lat:.6f}"
        params = {"key": key, "output": "json", "extensions": "all", "location": location}
        url = f"https://restapi.amap.com/v3/geocode/regeo?key={key}&output=json&extensions=all&location={location}"
        if private_key:
            url += f"&sig={self._sig(params, private_key)}"
        return self._http_json(url)

    async def _maybe_update_commute(self, item: dict[str, Any]) -> None:
        attrs = item.setdefault("attrs", {})
        if self._commute.get("distance") is not None:
            attrs["commute_distance"] = self._commute["distance"]
            attrs["commute_time"] = self._commute.get("time")
            if self._commute.get("tolls") is not None:
                attrs["commute_toll"] = self._commute["tolls"]
            if self._commute.get("traffic_lights") is not None:
                attrs["traffic_lights"] = self._commute["traffic_lights"]
        if attrs.get("naviStatus") != "导航中":
            return
        try:
            dest_lat = float(attrs.get("navi_dest_lat"))
            dest_lon = float(attrs.get("navi_dest_lon"))
        except (TypeError, ValueError):
            return
        dest_lon, dest_lat = gcj02towgs84(dest_lon, dest_lat)
        cfg = self._cfg()
        key = cfg.get(CONF_ADDRESSAPI_KEY) or ""
        if not key:
            return
        try:
            speed = float(attrs.get("speed") or 0)
            speed_th = float(cfg.get(CONF_COMMUTE_SPEED) if cfg.get(CONF_COMMUTE_SPEED) is not None else DEFAULT_COMMUTE_SPEED)
            interval = int(cfg.get(CONF_COMMUTE_INTERVAL) if cfg.get(CONF_COMMUTE_INTERVAL) is not None else DEFAULT_COMMUTE_INTERVAL)
        except (TypeError, ValueError):
            return
        driving = self._is_running(attrs.get("runorstop")) and attrs.get("onlinestatus") == "在线"
        if not (driving and speed > speed_th):
            return
        if time.time() - float(self._commute.get("updated") or 0) < interval * 60:
            return
        try:
            lat = float(item.get("thislat"))
            lon = float(item.get("thislon"))
        except (TypeError, ValueError):
            return
        result = await self.hass.async_add_executor_job(
            self._fetch_commute, lat, lon, dest_lat, dest_lon, key, cfg.get(CONF_PRIVATE_KEY) or ""
        )
        if not result:
            return
        self._commute = {
            "distance": result[0],
            "time": result[1],
            "tolls": result[2],
            "traffic_lights": result[3],
            "updated": time.time(),
        }
        attrs["commute_distance"] = result[0]
        attrs["commute_time"] = result[1]
        attrs["commute_toll"] = result[2]
        attrs["traffic_lights"] = result[3]

    async def _maybe_record_navi_toll(self, item: dict[str, Any]) -> None:
        attrs = item.get("attrs") or {}
        navigating = attrs.get("naviStatus") == "导航中"
        if navigating:
            toll = attrs.get("commute_toll")
            if toll is None:
                toll = self._commute.get("tolls")
            try:
                t = float(toll)
            except (TypeError, ValueError):
                t = 0.0
            if t > self._trip_toll:
                self._trip_toll = t
            self._navi_active = True
            return
        if not self._navi_active:
            return
        amount = round(float(self._trip_toll or 0), 2)
        self._navi_active = False
        self._trip_toll = 0.0
        if amount <= 0:
            return
        store = (self.hass.data.get(DOMAIN) or {}).get("store")
        if not store:
            return
        try:
            await store.add_expense(self.entry.entry_id, "etc", amount)
            _LOGGER.info("amap toll recorded: %.2f", amount)
        except Exception as err:
            _LOGGER.warning("amap toll record failed: %s", err)

    def _fmt_commute_time(self, seconds: int) -> str:
        seconds = max(int(seconds or 0), 0)
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        if days == 0 and hours == 0:
            return f"{minutes}分钟"
        parts: list[str] = []
        if days:
            parts.append(f"{days}天")
        if hours:
            parts.append(f"{hours}小时")
        if minutes or not parts:
            parts.append(f"{minutes}分钟")
        return "".join(parts)

    def _fetch_commute(self, lat, lon, dest_lat, dest_lon, key, private_key):
        olon, olat = wgs84togcj02(lon, lat)
        dlon, dlat = wgs84togcj02(dest_lon, dest_lat)
        origin = f"{olon:.6f},{olat:.6f}"
        dest = f"{dlon:.6f},{dlat:.6f}"
        params = {"key": key, "origin": origin, "destination": dest, "show_fields": "cost", "output": "json"}
        plate = normalize_plate(cfg_amap_plate(self.entry))
        if plate:
            params["plate"] = plate
        sig = self._sig(params, private_key) if private_key else ""
        url = f"https://restapi.amap.com/v5/direction/driving?key={key}&origin={origin}&destination={dest}&show_fields=cost&output=json"
        if plate:
            url += f"&plate={urllib.parse.quote(plate)}"
        if sig:
            url += f"&sig={sig}"
        resp = self._http_json(url)
        if str(resp.get("status")) != "1":
            return None
        path = ((resp.get("route") or {}).get("paths") or [{}])[0]
        cost = path.get("cost") if isinstance(path.get("cost"), dict) else {}
        try:
            tolls = float(cost.get("tolls") or 0)
        except (TypeError, ValueError):
            tolls = 0.0
        try:
            lights = int(float(cost.get("traffic_lights") or 0))
        except (TypeError, ValueError):
            lights = 0
        return (
            round(float(path.get("distance") or 0) / 1000, 1),
            self._fmt_commute_time(float(cost.get("duration") or 0)),
            tolls,
            lights,
        )

    @staticmethod
    def get_distance(lat1, lng1, lat2, lng2) -> float:
        earth_radius = 6378.137
        rad_lat1 = lat1 * math.pi / 180.0
        rad_lat2 = lat2 * math.pi / 180.0
        a = rad_lat1 - rad_lat2
        b = lng1 * math.pi / 180.0 - lng2 * math.pi / 180.0
        s = 2 * math.asin(
            math.sqrt(math.pow(math.sin(a / 2), 2) + math.cos(rad_lat1) * math.cos(rad_lat2) * math.pow(math.sin(b / 2), 2))
        )
        return s * earth_radius * 1000

    async def async_shutdown(self) -> None:
        self._clear_session_notice()
        try:
            self._fetcher.session.close()
        except Exception:
            pass
