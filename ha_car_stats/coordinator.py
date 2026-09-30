from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    create_session,
    fetch_surveillance_info,
    fetch_vehicle_info,
    fetch_violation_info,
    parse_license,
    parse_vehicle,
    parse_violations,
)
from .const import (
    API_BACKOFF_MAX,
    API_RATE_LIMIT_COOLDOWN,
    CONF_ACCESS_TOKEN,
    CONF_ACW_TC,
    CONF_JSESSIONID,
    CONF_LOGIN_AT,
    CONF_NOTIFY_INSPECT,
    CONF_NOTIFY_INSURANCE,
    CONF_NOTIFY_LICENSE,
    CONF_NOTIFY_MAINT,
    CONF_NOTIFY_VIOLATION,
    CONF_NOTIFY_YEARLY,
    CONF_SF,
    CONF_URL,
    DOMAIN,
    GET_KEEPALIVE_INTERVAL,
    LOGIN_ONCE_INTERVAL,
    SURVEILLANCE_INFO_INTERVAL,
)
from .helpers import (
    cfg_12123,
    cfg_battery_replace_date,
    cfg_expire_days,
    cfg_insurance_expiry,
    cfg_inspect_expiry,
    cfg_maint_date,
    cfg_maint_odo,
    compute_maint_remaining,
    cfg_maint_days,
    cfg_maint_km,
    cfg_name,
    cfg_notify_has_target,
    cfg_purchase_date,
    cfg_notify_inspect,
    cfg_notify_insurance,
    cfg_notify_license,
    cfg_notify_maint,
    cfg_notify_violation,
    cfg_notify_yearly,
    cfg_tank,
    cfg_vehicle_index,
    consumption_rating,
    days_until,
    in_year,
    resolve_fuel_price,
    resolve_odometer,
    same_month,
    same_year,
    usage_duration,
)
from .notify import send_notify
from .store import CarStatsStore

_LOGGER = logging.getLogger(__name__)


class CarStatsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: CarStatsStore,
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None, config_entry=entry)
        self.entry = entry
        self.store = store
        self.session: aiohttp.ClientSession | None = None
        self.inputs: dict[str, Any] = {
            "refuel_liters": 0.0,
            "refuel_cost": 0.0,
            "odometer": 0.0,
            "station_name": "",
        }
        self._cached_vehicle: dict[str, Any] = {}
        self._cached_license: dict[str, Any] = {}
        self._cached_violations: dict[str, Any] = {"count": 0, "records": []}
        has_js = bool(entry.data.get(CONF_JSESSIONID))
        self._session_status: dict[str, Any] = {
            "logged_in": has_js,
            "message": "等待同步" if has_js else "未登录",
            "error": None,
        }
        self._reauth_issued = False
        self._paused = False
        self._need_vehicle = False
        self._need_license = False
        self._fail_streak = {"vehicle": 0, "license": 0, "violations": 0}
        self._next_ok_ts = {"vehicle": 0.0, "license": 0.0, "violations": 0.0, "keepalive": 0.0}
        self._yearly_lock = asyncio.Lock()
        self._load_snapshot()
        self.async_set_updated_data(self._build_data())

    async def _async_update_data(self) -> dict[str, Any]:
        return self._build_data()

    def _load_snapshot(self) -> None:
        snap = self.store.snapshot(self.entry.entry_id)
        if isinstance(snap.get("vehicle"), dict) and snap["vehicle"].get("plate"):
            self._cached_vehicle = snap["vehicle"]
        if isinstance(snap.get("license"), dict) and snap["license"]:
            self._cached_license = snap["license"]
        if isinstance(snap.get("violations"), dict):
            self._cached_violations = snap["violations"]
        inputs = snap.get("inputs")
        if isinstance(inputs, dict):
            for key in ("refuel_liters", "refuel_cost", "odometer"):
                if inputs.get(key) is not None:
                    try:
                        self.inputs[key] = float(inputs[key])
                    except (TypeError, ValueError):
                        pass
            if inputs.get("station_name") is not None:
                self.inputs["station_name"] = str(inputs["station_name"])
        session = snap.get("session")
        if isinstance(session, dict) and session.get("message"):
            self._session_status = {
                "logged_in": bool(session.get("logged_in")),
                "message": session.get("message"),
                "error": session.get("error"),
            }
        next_ok = snap.get("next_ok")
        if isinstance(next_ok, dict):
            for key in self._next_ok_ts:
                try:
                    self._next_ok_ts[key] = float(next_ok.get(key) or 0)
                except (TypeError, ValueError):
                    pass
        has_plate = bool(self._cached_vehicle.get("plate"))
        prev_js = snap.get("jsessionid")
        changed_login = prev_js != self.entry.data.get(CONF_JSESSIONID) and (
            bool(prev_js) or bool(self.entry.data.get(CONF_JSESSIONID))
        )
        prev_idx = snap.get("vehicle_index")
        cur_idx = cfg_vehicle_index(self.entry)
        changed_vehicle = False
        if prev_idx is not None:
            try:
                changed_vehicle = int(prev_idx) != cur_idx
            except (TypeError, ValueError):
                changed_vehicle = True
        elif has_plate:
            cached_idx = self._cached_vehicle.get("index")
            if cached_idx is not None:
                try:
                    changed_vehicle = int(cached_idx) != cur_idx
                except (TypeError, ValueError):
                    changed_vehicle = True
        if changed_login:
            self._next_ok_ts["vehicle"] = 0
            self._next_ok_ts["license"] = 0
            self._next_ok_ts["violations"] = 0
            self._next_ok_ts["keepalive"] = 0
            self._paused = False
            self._reauth_issued = False
        if changed_vehicle:
            self._cached_vehicle = {}
            self._next_ok_ts["vehicle"] = 0
            has_plate = False
        self._need_vehicle = not has_plate or changed_login or changed_vehicle
        self._need_license = not bool(self._cached_license) or changed_login
        if self._need_vehicle:
            self._next_ok_ts["vehicle"] = 0
        if self._need_license:
            self._next_ok_ts["license"] = 0
        if (
            not changed_login
            and snap.get("paused")
            and snap.get("jsessionid") == self.entry.data.get(CONF_JSESSIONID)
        ):
            self._paused = True

    async def async_persist_snapshot(self) -> None:
        await self.store.save_snapshot(
            self.entry.entry_id,
            {
                "vehicle": self._cached_vehicle,
                "license": self._cached_license,
                "violations": self._cached_violations,
                "inputs": dict(self.inputs),
                "session": dict(self._session_status),
                "next_ok": dict(self._next_ok_ts),
                "paused": self._paused,
                "jsessionid": self.entry.data.get(CONF_JSESSIONID),
                "vehicle_index": cfg_vehicle_index(self.entry),
            },
        )

    def _can_call(self, key: str) -> bool:
        if self._paused:
            return False
        return time.time() >= float(self._next_ok_ts.get(key) or 0)

    def _schedule(self, key: str, delay: timedelta) -> None:
        self._next_ok_ts[key] = time.time() + delay.total_seconds()

    def _pause_api(self) -> None:
        self._paused = True
        self._session_status = {
            "logged_in": False,
            "message": "需要重新登录",
            "error": "需要重新登录",
        }
        self.request_reauth()

    def _mark_result(self, key: str, raw: dict[str, Any] | None, interval: timedelta) -> None:
        if raw and raw.get("success"):
            self._fail_streak[key] = 0
            self._schedule(key, interval)
            return
        if raw and (raw.get("need_reauth") or raw.get("error") == "需要重新登录"):
            self._pause_api()
            return
        self._fail_streak[key] = self._fail_streak.get(key, 0) + 1
        if raw and raw.get("rate_limited"):
            delay = API_RATE_LIMIT_COOLDOWN
        else:
            delay = min(interval * (2 ** min(self._fail_streak[key], 3)), API_BACKOFF_MAX)
        self._schedule(key, delay)

    async def _refresh_if_due(self, key: str) -> None:
        if not self.session or self._paused or not self._can_call(key):
            return
        _, jsessionid, _, sf, _ = self._auth()
        if not jsessionid or not sf:
            return
        if key == "vehicle":
            raw = await fetch_vehicle_info(self.session, jsessionid, sf)
            self._accept_vehicle(raw)
            if raw and raw.get("success") and self._cached_vehicle.get("plate"):
                self._fail_streak[key] = 0
                self._schedule(key, LOGIN_ONCE_INTERVAL)
            elif raw and raw.get("success"):
                self._schedule(key, timedelta(hours=2))
            else:
                self._mark_result(key, raw, timedelta(hours=2))
        elif key == "license":
            raw = await fetch_violation_info(self.session, jsessionid, sf)
            self._accept_license(raw)
            if raw and raw.get("success") and self._cached_license:
                self._fail_streak[key] = 0
                self._schedule(key, LOGIN_ONCE_INTERVAL)
            elif raw and raw.get("success"):
                self._schedule(key, timedelta(hours=2))
            else:
                self._mark_result(key, raw, timedelta(hours=2))
        elif key == "violations":
            raw = await fetch_surveillance_info(self.session, jsessionid, sf)
            self._accept_violations(raw)
            self._mark_result(key, raw, SURVEILLANCE_INFO_INTERVAL)

    def _accept_vehicle(self, raw: dict[str, Any] | None) -> None:
        parsed = parse_vehicle(raw, cfg_vehicle_index(self.entry))
        plate = parsed.get("plate")
        if plate and plate != "未知":
            self._cached_vehicle = parsed

    def _accept_license(self, raw: dict[str, Any] | None) -> None:
        if not raw or not raw.get("success"):
            return
        parsed = parse_license(raw)
        if any(
            parsed.get(key) not in (None, "", "未知")
            for key in ("type", "status", "expiry", "clear", "ljjf", "points")
        ):
            self._cached_license = parsed

    def _accept_violations(self, raw: dict[str, Any] | None) -> None:
        if raw and raw.get("success"):
            self._cached_violations = parse_violations(raw)

    async def async_setup(self) -> None:
        if cfg_12123(self.entry):
            self.session = await create_session(self.hass)
            if self.entry.data.get(CONF_JSESSIONID):
                if self._paused:
                    _, jsessionid, _, sf, _ = self._auth()
                    if jsessionid and sf:
                        raw = await fetch_vehicle_info(self.session, jsessionid, sf)
                        if raw and raw.get("success"):
                            self._paused = False
                            self._reauth_issued = False
                            self._accept_vehicle(raw)
                        elif raw and (raw.get("need_reauth") or raw.get("error") == "需要重新登录"):
                            pass
                        else:
                            self._paused = False
                            self._reauth_issued = False
                if not self._paused:
                    await self.async_sync_12123(force=True)
        self.async_set_updated_data(self._build_data())
        await self.async_ensure_year_start()
        await self.async_check_yearly()

    async def async_sync_12123(self, force: bool = False) -> None:
        if not self.session or self._paused:
            return
        _, jsessionid, _, sf, _ = self._auth()
        if not jsessionid or not sf:
            return
        if force:
            for key in ("vehicle", "license", "violations"):
                self._next_ok_ts[key] = 0
        await self._refresh_if_due("vehicle")
        self._need_vehicle = not bool(self._cached_vehicle.get("plate"))
        await self._refresh_if_due("license")
        self._need_license = not bool(self._cached_license)
        await self._refresh_if_due("violations")
        if self._cached_vehicle.get("plate") or self._cached_license:
            self._session_status = {
                "logged_in": True,
                "message": "会话有效",
                "error": None,
            }
        self.async_set_updated_data(self._build_data())
        await self.async_persist_snapshot()
        await self.async_check_violations()

    async def async_logout_12123(self) -> None:
        self._paused = True
        self._reauth_issued = False
        self._need_vehicle = True
        self._need_license = True
        self._cached_vehicle = {}
        self._cached_license = {}
        self._cached_violations = {"count": 0, "records": []}
        self._session_status = {
            "logged_in": False,
            "message": "已退出登录",
            "error": None,
        }
        for key in self._next_ok_ts:
            self._next_ok_ts[key] = 0
        self.async_set_updated_data(self._build_data())
        await self.store.save_snapshot(
            self.entry.entry_id,
            {
                "vehicle": {},
                "license": {},
                "violations": {"count": 0, "records": []},
                "inputs": dict(self.inputs),
                "session": dict(self._session_status),
                "next_ok": dict(self._next_ok_ts),
                "paused": True,
                "jsessionid": None,
                "vehicle_index": cfg_vehicle_index(self.entry),
            },
        )
        data = {
            key: value
            for key, value in self.entry.data.items()
            if key
            not in (
                CONF_ACCESS_TOKEN,
                CONF_JSESSIONID,
                CONF_ACW_TC,
                CONF_URL,
                CONF_LOGIN_AT,
            )
        }
        self.hass.config_entries.async_update_entry(self.entry, data=data)

    async def async_shutdown_session(self) -> None:
        if self.session:
            await self.session.close()
            self.session = None

    def _auth(self) -> tuple[str, str, str, str, str]:
        data = self.entry.data
        return (
            data.get(CONF_ACCESS_TOKEN) or "",
            data.get(CONF_JSESSIONID) or "",
            data.get(CONF_ACW_TC) or "",
            data.get(CONF_SF) or "",
            data.get(CONF_URL) or "",
        )

    async def async_refresh_vehicle(self) -> None:
        await self._refresh_if_due("vehicle")
        self.async_set_updated_data(self._build_data())
        await self.async_persist_snapshot()

    async def async_refresh_license(self, _: datetime | None = None) -> None:
        await self._refresh_if_due("license")
        self.async_set_updated_data(self._build_data())
        await self.async_persist_snapshot()

    async def async_refresh_violations(self, _: datetime | None = None) -> None:
        await self._refresh_if_due("violations")
        self.async_set_updated_data(self._build_data())
        await self.async_persist_snapshot()
        await self.async_check_violations()

    async def async_keepalive(self, _: datetime | None = None) -> None:
        if self._paused or not self._can_call("keepalive"):
            return
        access_token, jsessionid, acw_tc, sf, url = self._auth()
        if not jsessionid or not sf or not self.session:
            return
        if not url or not access_token:
            await self.async_sync_12123()
            self._schedule("keepalive", GET_KEEPALIVE_INTERVAL)
            return
        cookie_parts = [f"accessToken={access_token}"]
        if acw_tc:
            cookie_parts.append(f"acw_tc={acw_tc}")
        cookie_parts.append(f"JSESSIONID-L={jsessionid}")
        headers = {
            "Cookie": "; ".join(cookie_parts),
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "Referer": f"https://{sf}.122.gov.cn/",
        }
        try:
            async with self.session.get(url, headers=headers, allow_redirects=True) as resp:
                final_url = str(resp.url)
                redirected_to_login = any(
                    marker in final_url.lower()
                    for marker in ("/m/login", "/login", "loginsuccess?fail", "logon")
                )
                if resp.status == 200 and not redirected_to_login:
                    self._paused = False
                    self._reauth_issued = False
                    self._session_status = {
                        "logged_in": True,
                        "message": "会话有效",
                        "error": None,
                    }
                    self._schedule("keepalive", GET_KEEPALIVE_INTERVAL)
                    await self.async_sync_12123()
                    return
                if redirected_to_login or resp.status in (401, 403):
                    raw = await fetch_vehicle_info(self.session, jsessionid, sf)
                    if raw and raw.get("success"):
                        self._paused = False
                        self._reauth_issued = False
                        self._accept_vehicle(raw)
                        self._session_status = {
                            "logged_in": True,
                            "message": "会话有效",
                            "error": None,
                        }
                        self._schedule("keepalive", GET_KEEPALIVE_INTERVAL)
                        await self.async_sync_12123()
                        return
                    if raw and (raw.get("need_reauth") or raw.get("error") == "需要重新登录"):
                        self._pause_api()
                    else:
                        self._session_status = {
                            "logged_in": self._session_status.get("logged_in", False),
                            "message": "保活暂失败，将重试",
                            "error": (raw or {}).get("error") or f"HTTP {resp.status}",
                        }
                        self._schedule("keepalive", GET_KEEPALIVE_INTERVAL)
                else:
                    self._session_status = {
                        "logged_in": self._session_status.get("logged_in", False),
                        "message": f"保活暂失败 HTTP {resp.status}",
                        "error": f"HTTP {resp.status}",
                    }
                    self._schedule("keepalive", GET_KEEPALIVE_INTERVAL)
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            self._session_status = {
                "logged_in": self._session_status.get("logged_in", False),
                "message": "保活网络异常",
                "error": str(err),
            }
            self._schedule("keepalive", GET_KEEPALIVE_INTERVAL)
            self.async_set_updated_data(self._build_data())
            await self.async_persist_snapshot()
            return
        self.async_set_updated_data(self._build_data())
        await self.async_persist_snapshot()

    def request_reauth(self) -> None:
        if self._reauth_issued:
            return
        self._reauth_issued = True
        self.entry.async_start_reauth(self.hass)

    def reset_reauth(self) -> None:
        self._reauth_issued = False
        self._paused = False

    def current_odometer(self) -> float:
        stored = float(self.store.get(self.entry.entry_id).get("odometer") or 0)
        try:
            input_odo = float(self.inputs.get("odometer") or 0)
        except (TypeError, ValueError):
            input_odo = 0.0
        fallback = max(input_odo, stored)
        return resolve_odometer(self.hass, self.entry, fallback)

    def current_price(self) -> float:
        return resolve_fuel_price(self.hass, self.entry)

    def _year_total_cost(self, rec: dict[str, Any], year: int) -> float:
        return (
            sum(float(r.get("cost") or 0) for r in (rec.get("refuels") or []) if in_year(r.get("ts", ""), year))
            + sum(float(e.get("amount") or 0) for e in (rec.get("expenses") or []) if in_year(e.get("ts", ""), year))
            + sum(float(m.get("cost") or 0) for m in (rec.get("maintenances") or []) if in_year(m.get("ts", ""), year))
        )

    def _year_odos(self, rec: dict[str, Any], year: int) -> list[float]:
        return [
            float(r.get("odo") or 0)
            for r in (rec.get("refuels") or [])
            if in_year(r.get("ts", ""), year) and float(r.get("odo") or 0) > 0
        ]

    def _year_km_from_refuels(self, rec: dict[str, Any], year: int) -> float:
        odos = self._year_odos(rec, year)
        if len(odos) >= 2:
            return round(max(odos) - min(odos), 1)
        return 0.0

    def _close_year_km(
        self,
        rec: dict[str, Any],
        year: int,
        start_odo: float,
        end_odo: float,
        index: int,
        total: int,
    ) -> float:
        odos = self._year_odos(rec, year)
        if total == 1:
            if odos:
                return round(max(max(odos) - start_odo, 0), 1)
            return 0.0
        if index == 0:
            end = max(odos) if odos else start_odo
            return round(max(end - start_odo, 0), 1)
        if index == total - 1:
            if len(odos) >= 2:
                return round(max(max(odos) - min(odos), 0), 1)
            if odos:
                return round(max(max(odos) - start_odo, 0), 1)
            return 0.0
        return self._year_km_from_refuels(rec, year)

    def _build_yearly_history(self, rec: dict[str, Any], now: datetime, odo: float) -> list[dict[str, Any]]:
        stored = rec.get("yearly_history") or {}
        years: set[int] = set()
        for key in stored:
            try:
                years.add(int(key))
            except (TypeError, ValueError):
                pass
        for collection in (rec.get("refuels"), rec.get("expenses"), rec.get("maintenances")):
            for item in collection or []:
                try:
                    years.add(datetime.fromisoformat(item.get("ts", "")).year)
                except (TypeError, ValueError):
                    pass
        years.add(now.year)
        start_odo = float(rec.get("year_start_odo") or 0)
        result: list[dict[str, Any]] = []
        for year in sorted(years):
            calc_cost = round(self._year_total_cost(rec, year), 2)
            saved = stored.get(str(year)) if isinstance(stored, dict) else None
            if year == now.year:
                cost = calc_cost
                km = round(max(odo - start_odo, 0), 1) if start_odo > 0 else self._year_km_from_refuels(rec, year)
            elif isinstance(saved, dict):
                try:
                    cost = round(float(saved["cost"]), 2) if saved.get("cost") is not None else calc_cost
                except (TypeError, ValueError):
                    cost = calc_cost
                try:
                    km = round(float(saved["km"]), 1) if saved.get("km") is not None else self._year_km_from_refuels(rec, year)
                except (TypeError, ValueError):
                    km = self._year_km_from_refuels(rec, year)
            else:
                cost = calc_cost
                km = self._year_km_from_refuels(rec, year)
            result.append({"year": year, "cost": cost, "km": km})
        return result

    def _avg_consumption(self, refuels: list[dict[str, Any]]) -> float:
        fulls = [r for r in refuels if r.get("full") and float(r.get("odo") or 0) > 0]
        if len(fulls) < 2:
            return 0.0
        first, last = fulls[0], fulls[-1]
        dist = float(last["odo"]) - float(first["odo"])
        liters = sum(float(r.get("liters") or 0) for r in fulls[1:])
        if dist > 0 and liters > 0:
            return round(liters / dist * 100, 1)
        return 0.0

    def compute_stats(self) -> dict[str, Any]:
        rec = self.store.get(self.entry.entry_id)
        refuels = rec.get("refuels") or []
        expenses = rec.get("expenses") or []
        maints = rec.get("maintenances") or []
        now = dt_util.now()
        odo = self.current_odometer()
        price = self.current_price()
        last = refuels[-1] if refuels else None
        monthly_fuel = sum(float(r.get("cost") or 0) for r in refuels if same_month(r.get("ts", ""), now))
        yearly_fuel = sum(float(r.get("cost") or 0) for r in refuels if same_year(r.get("ts", ""), now))
        monthly_etc = sum(
            float(e.get("amount") or 0)
            for e in expenses
            if e.get("type") == "etc" and same_month(e.get("ts", ""), now)
        )
        yearly_total = (
            sum(float(r.get("cost") or 0) for r in refuels if same_year(r.get("ts", ""), now))
            + sum(float(e.get("amount") or 0) for e in expenses if same_year(e.get("ts", ""), now))
            + sum(float(m.get("cost") or 0) for m in maints if same_year(m.get("ts", ""), now))
        )
        total_cost = (
            sum(float(r.get("cost") or 0) for r in refuels)
            + sum(float(e.get("amount") or 0) for e in expenses)
            + sum(float(m.get("cost") or 0) for m in maints)
        )
        avg = self._avg_consumption(refuels)
        interval_km = cfg_maint_km(self.entry)
        interval_days = cfg_maint_days(self.entry)
        km_until, days_until_maint = compute_maint_remaining(
            cfg_maint_date(self.entry),
            cfg_maint_odo(self.entry),
            interval_km,
            interval_days,
            odo,
        )
        insurance_days = days_until(cfg_insurance_expiry(self.entry))
        inspection_days = days_until(cfg_inspect_expiry(self.entry))
        yearly_refuels: list[dict[str, Any]] = []
        for r in refuels:
            if not same_year(r.get("ts", ""), now):
                continue
            item: dict[str, Any] = {
                "date": (r.get("ts") or "")[:16].replace("T", " "),
                "cost": round(float(r.get("cost") or 0), 2),
                "odometer": round(float(r.get("odo") or 0), 1),
            }
            liters = float(r.get("liters") or 0)
            if liters > 0:
                item["liters"] = round(liters, 2)
            station = str(r.get("station") or "").strip()
            if station:
                item["station"] = station
            yearly_refuels.append(item)
        return {
            "avg_consumption": avg,
            "consumption_rating": consumption_rating(avg),
            "last_refuel_liters": round(float(last.get("liters") or 0), 2) if last else 0,
            "last_refuel_cost": round(float(last.get("cost") or 0), 2) if last else 0,
            "fuel_price": round(float(price), 2),
            "monthly_fuel_cost": round(monthly_fuel, 2),
            "yearly_fuel_cost": round(yearly_fuel, 2),
            "monthly_etc_cost": round(monthly_etc, 2),
            "yearly_total_cost": round(yearly_total, 2),
            "cost_per_km": round(total_cost / odo, 2) if odo > 0 else 0,
            "driving_odometer": round(float(rec.get("odometer") or 0), 1),
            "km_until_maint": km_until,
            "days_until_maint": days_until_maint,
            "insurance_days": insurance_days,
            "inspection_days": inspection_days,
            "usage_time": usage_duration(cfg_purchase_date(self.entry), now.date()),
            "battery_usage_time": usage_duration(cfg_battery_replace_date(self.entry), now.date()),
            "yearly_refuels": yearly_refuels,
            "yearly_history": self._build_yearly_history(rec, now, odo),
        }

    def _build_data(self) -> dict[str, Any]:
        vehicle = self._cached_vehicle
        license_info = self._cached_license
        violations = self._cached_violations
        logged_in = bool(self._session_status.get("logged_in"))
        msg = self._session_status.get("message")
        if logged_in:
            session_state = "已登录"
        elif msg in ("需要重新登录", "已退出登录", "未登录"):
            session_state = msg
        else:
            session_state = "会话异常"
        return {
            "vehicle": vehicle,
            "license": license_info,
            "violations": violations,
            "session": {
                "state": session_state,
                "logged_in": logged_in,
                "message": self._session_status.get("message"),
                "error": self._session_status.get("error"),
            },
            "stats": self.compute_stats(),
        }

    def push(self) -> None:
        self.async_set_updated_data(self._build_data())

    async def async_push(self) -> None:
        self.push()

    async def async_add_refuel_from_inputs(self) -> None:
        liters = float(self.inputs.get("refuel_liters") or 0)
        cost = float(self.inputs.get("refuel_cost") or 0)
        price = self.current_price()
        if liters <= 0 and cost <= 0:
            return
        if liters <= 0 and price > 0:
            liters = round(cost / price, 2)
        if cost <= 0 and price > 0:
            cost = round(liters * price, 2)
        odo = self.current_odometer()
        tank = cfg_tank(self.entry)
        full = tank <= 0 or liters >= tank * 0.9
        station = str(self.inputs.get("station_name") or "").strip()
        input_odo = float(self.inputs.get("odometer") or 0)
        update_odometer = input_odo > 0
        if update_odometer:
            odo = input_odo
        await self.store.add_refuel(
            self.entry.entry_id, odo, liters, cost, price, full, station, update_odometer=update_odometer
        )
        self.inputs["refuel_liters"] = 0.0
        self.inputs["refuel_cost"] = 0.0
        self.inputs["station_name"] = ""
        self.inputs["odometer"] = odo
        self.push()
        await self.async_persist_snapshot()

    def _plate(self) -> str:
        plate = (self.data or {}).get("vehicle", {}).get("plate")
        return plate or cfg_name(self.entry)

    def _violation_key(self, rec: dict[str, Any]) -> str:
        return f"{rec.get('time') or ''}|{rec.get('location') or ''}|{rec.get('behavior') or ''}"

    async def async_ensure_year_start(self) -> None:
        rec = self.store.get(self.entry.entry_id)
        if rec.get("year_start_year") is not None:
            return
        await self.store.update_fields(
            self.entry.entry_id,
            year_start_odo=self.current_odometer(),
            year_start_year=dt_util.now().year,
        )

    async def async_check_violations(self) -> None:
        records = ((self.data or {}).get("violations") or {}).get("records") or []
        keys = [self._violation_key(item) for item in records]
        rec = self.store.get(self.entry.entry_id)
        known = rec.get("notified_violations")
        if known is None:
            await self.store.update_fields(self.entry.entry_id, notified_violations=keys)
            return
        known_set = set(known)
        new_items = [item for item, key in zip(records, keys) if key and key not in known_set]
        if new_items:
            self._next_ok_ts["license"] = 0
            await self._refresh_if_due("license")
            self.async_set_updated_data(self._build_data())
            await self.async_persist_snapshot()
        if new_items and cfg_notify_violation(self.entry):
            lines = []
            for item in new_items:
                lines.append(
                    f"地点：{item.get('location') or '-'}\n"
                    f"行为：{item.get('behavior') or '-'}\n"
                    f"记分：{item.get('points') if item.get('points') is not None else '-'}\n"
                    f"罚款：{item.get('fine') if item.get('fine') is not None else '-'}\n"
                    f"时间：{item.get('time') or '-'}"
                )
            if not await send_notify(
                self.hass,
                self.entry,
                "汽车违章通知",
                f"车牌：{self._plate()}\n" + "\n\n".join(lines),
                CONF_NOTIFY_VIOLATION,
            ):
                return
        merged = list(known_set | {k for k in keys if k})
        if set(merged) != set(known):
            await self.store.update_fields(self.entry.entry_id, notified_violations=merged)

    async def async_daily_notify(self, now: datetime | None = None) -> None:
        current = now or dt_util.now()
        self.push()
        await self.async_check_expiry(current)

    async def async_check_yearly(self, now: datetime | None = None) -> None:
        async with self._yearly_lock:
            await self._async_check_yearly(now)

    async def _async_check_yearly(self, now: datetime | None = None) -> None:
        current = now or dt_util.now()
        await self.async_ensure_year_start()
        rec = self.store.get(self.entry.entry_id)
        try:
            start_year = int(rec.get("year_start_year"))
        except (TypeError, ValueError):
            return
        odo = self.current_odometer()
        start_odo = float(rec.get("year_start_odo") or 0)
        history = dict(rec.get("yearly_history") or {})
        fields: dict[str, Any] = {}
        need_close = start_year < current.year
        is_new_year_day = current.month == 1 and current.day == 1
        if need_close:
            years_to_close = list(range(start_year, current.year))
            for i, year in enumerate(years_to_close):
                history[str(year)] = {
                    "cost": round(self._year_total_cost(rec, year), 2),
                    "km": self._close_year_km(rec, year, start_odo, odo, i, len(years_to_close)),
                }
            fields["yearly_history"] = history
        prev_year = current.year - 1
        if prev_year < 1:
            if need_close:
                fields["year_start_odo"] = odo
                fields["year_start_year"] = current.year
            if fields:
                await self.store.update_fields(self.entry.entry_id, **fields)
                self.push()
            return
        prev = history.get(str(prev_year)) or (rec.get("yearly_history") or {}).get(str(prev_year)) or {}
        already = rec.get("last_yearly_notify") == str(prev_year)
        mark_notified = False
        advance_year = False

        async def _try_yearly_notify() -> bool:
            fuel = sum(
                float(r.get("cost") or 0)
                for r in (rec.get("refuels") or [])
                if in_year(r.get("ts", ""), prev_year)
            )
            fuel_count = sum(1 for r in (rec.get("refuels") or []) if in_year(r.get("ts", ""), prev_year))
            etc = sum(
                float(e.get("amount") or 0)
                for e in (rec.get("expenses") or [])
                if e.get("type") == "etc" and in_year(e.get("ts", ""), prev_year)
            )
            total = float(prev.get("cost") or self._year_total_cost(rec, prev_year))
            km = float(prev.get("km") or 0)
            return await send_notify(
                self.hass,
                self.entry,
                "汽车上年用车通知",
                f"车牌：{self._plate()}\n"
                f"行驶里程：{km}公里\n"
                f"加油次数：{fuel_count}次\n"
                f"油费：{round(fuel, 2)}元\n"
                f"高速费：{round(etc, 2)}元\n"
                f"总费用：{round(total, 2)}元",
                CONF_NOTIFY_YEARLY,
            )

        if need_close:
            if is_new_year_day:
                if already:
                    mark_notified = True
                    advance_year = True
                elif not cfg_notify_yearly(self.entry) or not cfg_notify_has_target(self.entry, CONF_NOTIFY_YEARLY):
                    mark_notified = True
                    advance_year = True
                elif await _try_yearly_notify():
                    mark_notified = True
                    advance_year = True
            else:
                mark_notified = True
                advance_year = True
        elif is_new_year_day and not already:
            if not cfg_notify_yearly(self.entry) or not cfg_notify_has_target(self.entry, CONF_NOTIFY_YEARLY):
                mark_notified = True
            elif await _try_yearly_notify():
                mark_notified = True

        if mark_notified:
            fields["last_yearly_notify"] = str(prev_year)
        if advance_year:
            fields["year_start_odo"] = odo
            fields["year_start_year"] = current.year
        if fields:
            await self.store.update_fields(self.entry.entry_id, **fields)
            self.push()

    async def async_check_expiry(self, now: datetime) -> None:
        today = now.date().isoformat()
        rec = self.store.get(self.entry.entry_id)
        stats = self.compute_stats()
        expire_days = cfg_expire_days(self.entry)
        km_left = stats.get("km_until_maint")
        days_left = stats.get("days_until_maint")
        if km_left is not None and days_left is not None:
            try:
                km_left_n = float(km_left)
            except (TypeError, ValueError):
                km_left_n = 999999
            try:
                days_left_n = int(days_left)
            except (TypeError, ValueError):
                days_left_n = 999999
            if (
                cfg_notify_maint(self.entry)
                and (km_left_n <= 0 or days_left_n <= 0)
                and rec.get("last_maint_notify") != today
            ):
                if await send_notify(
                    self.hass,
                    self.entry,
                    "汽车保养到期通知",
                    f"车牌：{self._plate()}\n"
                    f"剩余里程：{km_left}公里\n"
                    f"剩余天数：{days_left}天",
                    CONF_NOTIFY_MAINT,
                ):
                    await self.store.update_fields(self.entry.entry_id, last_maint_notify=today)
        ins_expiry = cfg_insurance_expiry(self.entry)
        ins_days = days_until(ins_expiry) if ins_expiry else None
        if (
            cfg_notify_insurance(self.entry)
            and ins_days is not None
            and ins_days <= expire_days
            and rec.get("last_insure_notify") != today
        ):
            if await send_notify(
                self.hass,
                self.entry,
                "汽车保险到期通知",
                f"车牌：{self._plate()}\n"
                f"到期日期：{ins_expiry}\n"
                f"剩余天数：{ins_days}天",
                CONF_NOTIFY_INSURANCE,
            ):
                await self.store.update_fields(self.entry.entry_id, last_insure_notify=today)
        inspect_expiry = cfg_inspect_expiry(self.entry)
        inspect_days = days_until(inspect_expiry) if inspect_expiry else None
        if (
            cfg_notify_inspect(self.entry)
            and inspect_days is not None
            and inspect_days <= expire_days
            and rec.get("last_inspect_notify") != today
        ):
            if await send_notify(
                self.hass,
                self.entry,
                "汽车年检到期通知",
                f"车牌：{self._plate()}\n"
                f"到期日期：{inspect_expiry}\n"
                f"剩余天数：{inspect_days}天",
                CONF_NOTIFY_INSPECT,
            ):
                await self.store.update_fields(self.entry.entry_id, last_inspect_notify=today)
        license_expiry = ((self.data or {}).get("license") or {}).get("expiry")
        license_days = days_until(license_expiry)
        if (
            cfg_notify_license(self.entry)
            and license_days is not None
            and license_days <= expire_days
            and rec.get("last_license_notify") != today
        ):
            if await send_notify(
                self.hass,
                self.entry,
                "汽车驾驶证到期通知",
                f"车牌：{self._plate()}\n"
                f"到期日期：{license_expiry}\n"
                f"剩余天数：{license_days}天",
                CONF_NOTIFY_LICENSE,
            ):
                await self.store.update_fields(self.entry.entry_id, last_license_notify=today)
