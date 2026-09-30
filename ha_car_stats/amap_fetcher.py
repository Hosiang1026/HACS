from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import time
from typing import Any

import requests
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import AMAP_API_HOST, DOMAIN
from .helpers import fmt_duration

_LOGGER = logging.getLogger(__name__)


class AmapSessionExpired(Exception):
    pass


def _session_expired(resp: dict[str, Any]) -> bool:
    code = str(resp.get("code") if resp.get("code") is not None else "")
    message = str(resp.get("message") or resp.get("msg") or "")
    low = message.lower()
    if code == "14" or "not login" in low:
        return True
    if any(k in message for k in ("未登录", "登录失效", "登录已过期", "会话失效", "会话过期")):
        return True
    return "session" in low and any(k in low for k in ("invalid", "expire", "expired"))


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return obj.isoformat()
        return super().default(obj)


def probe_amap_cars(amap_key: str, sessionid: str, paramdata: str) -> list[dict[str, Any]]:
    sessionid = str(sessionid or "").strip().rstrip(";")
    if not amap_key or not sessionid or not paramdata:
        return []
    session = requests.session()
    session.headers.update(
        {
            "Host": "ts.amap.com",
            "Accept": "application/json",
            "sessionid": sessionid,
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Cookie": f"sessionid={sessionid}",
        }
    )
    resp = session.post(AMAP_API_HOST + amap_key, data=paramdata, timeout=15).json()
    if not isinstance(resp, dict):
        return []
    ok = resp.get("result")
    if ok not in (True, 1, "1", "true") and "data" not in resp:
        return []
    lst = (resp.get("data") or {}).get("carLinkInfoList") or []
    return lst if isinstance(lst, list) else []


class AmapDataFetcher:
    def __init__(
        self,
        hass: HomeAssistant,
        amap_key: str,
        sessionid: str,
        paramdata: str,
        tid: str,
        store_key: str,
    ) -> None:
        self.hass = hass
        self.tid = str(tid)
        self.amap_key = amap_key
        self.amap_sessionid = str(sessionid or "").strip().rstrip(";")
        self.amap_paramdata = paramdata
        self.session = requests.session()
        self.session.headers.update(
            {
                "Host": "ts.amap.com",
                "Accept": "application/json",
                "sessionid": self.amap_sessionid,
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "Cookie": f"sessionid={self.amap_sessionid}",
            }
        )
        self.vardata: dict[str, Any] = {}
        self.lastgpstime = datetime.datetime.now()
        self._store = Store(hass, 1, f"{DOMAIN}_amap_{slugify(store_key)}", encoder=DateTimeEncoder)
        self._persisted_loaded = False
        self._fetch_lock = asyncio.Lock()
        self.on_api_call = None

    def _get_devices_info(self) -> list[dict[str, Any]]:
        if self.on_api_call:
            self.on_api_call()
        resp = self.session.post(AMAP_API_HOST + self.amap_key, data=self.amap_paramdata, timeout=15).json()
        if not isinstance(resp, dict):
            return []
        if _session_expired(resp):
            raise AmapSessionExpired(str(resp.get("message") or resp.get("code") or "session expired"))
        lst = (resp.get("data") or {}).get("carLinkInfoList") or []
        return lst if isinstance(lst, list) else []

    @staticmethod
    def time_diff(timestamp: int) -> str:
        total = int((datetime.datetime.now() - datetime.datetime.fromtimestamp(timestamp)).total_seconds())
        return fmt_duration(total)

    @staticmethod
    def get_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        earth_radius = 6378.137
        rad_lat1 = lat1 * math.pi / 180.0
        rad_lat2 = lat2 * math.pi / 180.0
        a = rad_lat1 - rad_lat2
        b = lng1 * math.pi / 180.0 - lng2 * math.pi / 180.0
        s = 2 * math.asin(
            math.sqrt(math.pow(math.sin(a / 2), 2) + math.cos(rad_lat1) * math.cos(rad_lat2) * math.pow(math.sin(b / 2), 2))
        )
        return s * earth_radius * 1000

    @staticmethod
    def calculate_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
        lat1 = math.radians(lat1)
        lat2 = math.radians(lat2)
        delta_lng = math.radians(lng2 - lng1)
        y = math.sin(delta_lng) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lng)
        return int((math.degrees(math.atan2(y, x)) + 360) % 360)

    async def _load_persisted(self) -> None:
        try:
            self._persisted = await self._store.async_load() or {}
        except Exception:
            self._persisted = {}

    async def _persist(self) -> None:
        try:
            data = dict(getattr(self, "_persisted", None) or {})
            data.update(
                {
                    "vardata": self.vardata,
                    "lastgpstime": self.lastgpstime.isoformat(),
                    "timestamp": datetime.datetime.now().isoformat(),
                }
            )
            self._persisted = data
            await self._store.async_save(data)
        except Exception as err:
            _LOGGER.error("amap persist failed: %s", err)

    async def async_remove_store(self) -> None:
        try:
            await self._store.async_remove()
        except Exception:
            pass

    async def async_ensure_persisted(self) -> None:
        if self._persisted_loaded:
            return
        await self._load_persisted()
        self._persisted_loaded = True
        self.vardata = dict((self._persisted or {}).get("vardata") or {})
        raw_t = (self._persisted or {}).get("lastgpstime")
        if raw_t:
            try:
                self.lastgpstime = datetime.datetime.fromisoformat(str(raw_t))
            except (TypeError, ValueError):
                pass

    async def get_data(self) -> dict[str, Any] | None:
        async with self._fetch_lock:
            return await self._get_data_locked()

    async def _get_data_locked(self) -> dict[str, Any] | None:
        await self.async_ensure_persisted()

        try:
            async with asyncio.timeout(20):
                devices = await self.hass.async_add_executor_job(self._get_devices_info) or []
        except AmapSessionExpired:
            raise
        except Exception as err:
            _LOGGER.error("amap fetch failed: %s", err)
            raise

        imei = self.tid
        for infodata in devices:
            if not isinstance(infodata, dict):
                continue
            tid = str(infodata.get("tid") or "")
            if tid != imei:
                continue

            deviceinfo = dict(infodata)
            deviceinfo["device_model"] = "高德地图车机版"
            deviceinfo["sw_version"] = (infodata.get("sysInfo") or {}).get("autodiv", "")
            loc = infodata.get("naviLocInfo") if isinstance(infodata.get("naviLocInfo"), dict) else {}
            try:
                thislat = float(loc.get("lat"))
                thislon = float(loc.get("lon"))
            except (TypeError, ValueError):
                continue
            if abs(thislat) < 0.01 and abs(thislon) < 0.01:
                continue

            accuracy = 0
            for k in ("posAcc", "showPosAcc", "accuracy", "acc", "radius"):
                v = loc.get(k)
                if v in (None, ""):
                    continue
                try:
                    accuracy = int(float(v))
                    break
                except (TypeError, ValueError):
                    continue

            querytime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.vardata["querytime"] = querytime
            lastlat = self.vardata.get("lastlat")
            lastlon = self.vardata.get("lastlon")
            has_last = lastlat not in (None, "") and lastlon not in (None, "") and not (float(lastlat) == 0 and float(lastlon) == 0)
            lastlat = float(lastlat or 0)
            lastlon = float(lastlon or 0)
            distance = self.get_distance(thislat, thislon, lastlat, lastlon) if has_last else 0

            if str(infodata.get("onlineStatus")) == "1":
                onlinestatus = "在线"
            elif str(infodata.get("onlineStatus")) == "0":
                onlinestatus = "离线"
            else:
                onlinestatus = "未知"

            status = "停车"
            if not has_last:
                self.vardata["lastlat"] = thislat
                self.vardata["lastlon"] = thislon
                self.vardata.setdefault("runorstop", "stop")
            elif onlinestatus == "在线" and distance > 10:
                status = "行驶"
                distancetime = (datetime.datetime.now() - self.lastgpstime).total_seconds()
                if distancetime > 1 and distance < 10000:
                    self.vardata["speed"] = round(distance / distancetime * 3.6, 1)
                    self.vardata["course"] = self.calculate_bearing(lastlat, lastlon, thislat, thislon)
                self.lastgpstime = datetime.datetime.now()
                if self.vardata.get("runorstop", "stop") == "stop":
                    laststop = self.vardata.get("laststoptime")
                    reset_run = True
                    if laststop:
                        try:
                            stop_dt = datetime.datetime.strptime(str(laststop), "%Y-%m-%d %H:%M:%S")
                            last_run = self.vardata.get("lastruntime")
                            never_ran = False
                            stale_run = False
                            if last_run:
                                run_dt = datetime.datetime.strptime(str(last_run), "%Y-%m-%d %H:%M:%S")
                                never_ran = stop_dt <= run_dt
                                stale_run = (stop_dt - run_dt).total_seconds() > 36 * 3600
                            if not never_ran and not stale_run and (datetime.datetime.now() - stop_dt).total_seconds() <= 1800:
                                reset_run = False
                        except (ValueError, TypeError):
                            pass
                    if reset_run or not str(self.vardata.get("lastruntime") or "").strip():
                        self.vardata["lastruntime"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.vardata["runorstop"] = "run"
                self.vardata["had_run"] = True
                self.vardata["lastlat"] = thislat
                self.vardata["lastlon"] = thislon
            elif onlinestatus == "在线" and self.vardata.get("runorstop", "stop") == "run":
                status = "静止"
                self.vardata["laststoptime"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.vardata["runorstop"] = "stop"
                self.vardata["speed"] = 0
            if self.vardata.get("runorstop") == "stop" and not str(self.vardata.get("laststoptime") or "").strip():
                self.vardata["laststoptime"] = querytime

            navi_dest = ""
            navi_dest_lat = None
            navi_dest_lon = None
            navi_dest_fresh = False
            if str(infodata.get("naviStatus")) == "1":
                navi_status = "导航中"
                status = "导航中"
                poi = infodata.get("endPoi") or infodata.get("end_poi") or infodata.get("destPoi") or {}
                if isinstance(poi, str):
                    navi_dest = poi.strip()
                elif isinstance(poi, dict):
                    pname = str(poi.get("name") or poi.get("poiName") or "").strip()
                    if isinstance(poi.get("name"), list):
                        pname = ""
                    paddr = str(poi.get("address") or "").strip()
                    if isinstance(poi.get("address"), list):
                        paddr = ""
                    navi_dest = f"{pname} {paddr}".strip() if pname and paddr and pname not in paddr else (pname or paddr)
                    try:
                        navi_dest_lat = float(poi.get("lat"))
                        navi_dest_lon = float(poi.get("lon"))
                    except (TypeError, ValueError):
                        navi_dest_lat = navi_dest_lon = None
                    if navi_dest_lat is not None and abs(navi_dest_lat) < 0.01 and abs(navi_dest_lon or 0) < 0.01:
                        navi_dest_lat = navi_dest_lon = None
                navi_dest_fresh = bool(navi_dest)
            else:
                navi_status = "在线"
            if onlinestatus == "离线":
                status = "离线"
                navi_status = "离线"
            if navi_dest:
                self.vardata["navi_dest"] = navi_dest
            if navi_dest_lat is not None and navi_dest_lon is not None:
                self.vardata["navi_dest_lat"] = navi_dest_lat
                self.vardata["navi_dest_lon"] = navi_dest_lon
            navi_dest = self.vardata.get("navi_dest") or ""
            if navi_status == "导航中":
                navi_dest_lat = self.vardata.get("navi_dest_lat")
                navi_dest_lon = self.vardata.get("navi_dest_lon")
            else:
                navi_dest_lat = navi_dest_lon = None
                navi_dest_fresh = False

            prev_online = self.vardata.get("isonline")
            if onlinestatus == "离线":
                nowstr = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if prev_online == "在线":
                    self.vardata["lastofflinetime"] = nowstr
                if self.vardata.get("runorstop") == "run":
                    self.vardata["laststoptime"] = nowstr
                    self.vardata["runorstop"] = "stop"
                    self.vardata["speed"] = 0
                self.vardata["isonline"] = "离线"
            elif onlinestatus == "在线":
                if prev_online == "离线":
                    self.vardata["lastonlinetime"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.vardata["isonline"] = "在线"

            if not str(self.vardata.get("lastonlinetime") or "").strip() and onlinestatus == "在线":
                self.vardata["lastonlinetime"] = querytime

            laststoptime = self.vardata.get("laststoptime", "")
            runorstop = self.vardata.get("runorstop", "stop")
            parkingtime = ""
            if laststoptime and runorstop == "stop":
                parkingtime = self.time_diff(int(time.mktime(time.strptime(laststoptime, "%Y-%m-%d %H:%M:%S"))))

            await self._persist()
            attrs = {
                "querytime": querytime,
                "speed": self.vardata.get("speed", 0),
                "distance": distance,
                "runorstop": runorstop,
                "lastruntime": self.vardata.get("lastruntime", ""),
                "laststoptime": laststoptime,
                "parkingtime": parkingtime,
                "naviStatus": navi_status,
                "navi_dest": navi_dest,
                "navi_dest_lat": navi_dest_lat,
                "navi_dest_lon": navi_dest_lon,
                "navi_dest_fresh": navi_dest_fresh,
                "onlinestatus": self.vardata.get("isonline", "离线"),
                "lastofflinetime": self.vardata.get("lastofflinetime", ""),
                "lastonlinetime": self.vardata.get("lastonlinetime", ""),
                "had_run": bool(self.vardata.get("had_run")),
            }
            if self.vardata.get("course") not in (None, ""):
                attrs["course"] = self.vardata["course"]
            return {
                "thislat": thislat,
                "thislon": thislon,
                "accuracy": accuracy,
                "imei": imei,
                "status": status,
                "attrs": attrs,
                "deviceinfo": deviceinfo,
            }
        return None
