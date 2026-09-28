from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta, datetime
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.components.persistent_notification import async_create

from .const import (
    CONF_BASE_URL,
    CONF_INTERVAL,
    CONF_SESSION_KEY,
    CONF_USE_PAGE_LOCATION,
    CONF_AMAP_API_KEY,
    CONF_AMAP_DAILY_LIMIT,
    CONF_ENABLE_AMAP,
    DEFAULT_INTERVAL,
    DEFAULT_USE_PAGE_LOCATION,
    LOW_BATTERY_PERCENT,
    DEFAULT_AMAP_DAILY_LIMIT,
)

_LOGGER = logging.getLogger(__name__)


def _amap_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            text = _amap_text(item)
            if text:
                return text
        return None
    text = str(value).strip()
    if not text or text in ("[]", "null", "None"):
        return None
    return text


def _amap_grid(lng: float, lat: float) -> tuple[int, int]:
    return int(round(lng * 278)), int(round(lat * 278))


class SyncCoordinator(DataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_INTERVAL, entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL))
        try:
            interval = int(interval)
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVAL
        if interval < 60:
            interval = interval * 60

        try:
            super().__init__(
                hass,
                _LOGGER,
                config_entry=entry,
                name="荣耀云同步",
                update_interval=timedelta(seconds=interval),
            )
        except TypeError:
            super().__init__(
                hass,
                _LOGGER,
                name="荣耀云同步",
                update_interval=timedelta(seconds=interval),
            )

        self.entry = entry
        self.hass = hass
        self._session_key = entry.data[CONF_SESSION_KEY]
        self._need_reauth_notified = False
        self._credentials_sent = False
        self._refresh_lock = asyncio.Lock()

        self._last_locate_time = 0
        self._min_locate_interval = 60

        self._last_device_count = 0
        self._current_interval = interval
        self._auth_retry_count = 0
        self._auth_retry_unsub = None

        self._last_known_devices: dict[str, dict[str, Any]] = {}
        self._last_known_timestamps: dict[str, float] = {}
        self._device_cache_ttl = 3600

        self._locate_count = 0
        self._amap_count = 0
        self._usage_day: str | None = None
        self._geocode_cache: dict[str, dict[str, Any]] = {}
        self._commute_state: dict[str, dict[str, Any]] = {}

    @property
    def _base_url(self) -> str:
        return self.entry.data[CONF_BASE_URL].rstrip("/")

    def _commute_bucket(self, device_id: str) -> dict[str, Any]:
        bucket = self._commute_state.get(device_id)
        if bucket is None:
            bucket = {
                "distance": None,
                "time": None,
                "info": None,
                "pending": False,
                "inside": False,
                "route_key": None,
                "last_lat": None,
                "last_lon": None,
                "mode": None,
            }
            self._commute_state[device_id] = bucket
        return bucket

    def commute_distance(self, device_id: str) -> float | None:
        bucket = self._commute_state.get(device_id)
        if not bucket:
            return None
        return bucket.get("distance")

    def commute_time(self, device_id: str) -> int | None:
        bucket = self._commute_state.get(device_id)
        if not bucket:
            return None
        return bucket.get("time")

    def commute_info(self, device_id: str) -> str | None:
        bucket = self._commute_state.get(device_id)
        if not bucket:
            return None
        return bucket.get("info")

    def restore_commute_distance(self, device_id: str, state: Any) -> None:
        bucket = self._commute_bucket(device_id)
        if bucket["distance"] is not None or state in (None, "", "unknown", "unavailable"):
            return
        try:
            bucket["distance"] = float(state)
        except (TypeError, ValueError):
            pass

    def restore_commute_time(self, device_id: str, state: Any) -> None:
        bucket = self._commute_bucket(device_id)
        if bucket["time"] is not None or state in (None, "", "unknown", "unavailable"):
            return
        try:
            bucket["time"] = int(float(state))
        except (TypeError, ValueError):
            pass

    def restore_commute_info(self, device_id: str, state: Any) -> None:
        bucket = self._commute_bucket(device_id)
        if bucket["info"] or state in (None, "", "unknown", "unavailable"):
            return
        text = str(state).strip()
        if text:
            bucket["info"] = text

    def _amap_enabled(self) -> bool:
        return bool(
            self.entry.options.get(
                CONF_ENABLE_AMAP,
                self.entry.data.get(CONF_ENABLE_AMAP, False),
            )
        )

    def _get_amap_api_key(self) -> str:
        return (
            self.entry.options.get(CONF_AMAP_API_KEY, "")
            or self.entry.data.get(CONF_AMAP_API_KEY, "")
            or ""
        ).strip()

    def _get_amap_daily_limit(self) -> int:
        try:
            return int(
                self.entry.options.get(
                    CONF_AMAP_DAILY_LIMIT,
                    self.entry.data.get(CONF_AMAP_DAILY_LIMIT, DEFAULT_AMAP_DAILY_LIMIT),
                )
            )
        except (TypeError, ValueError):
            return DEFAULT_AMAP_DAILY_LIMIT

    @property
    def locate_count(self) -> int:
        self._roll_usage_day()
        return self._locate_count

    @property
    def amap_count(self) -> int:
        self._roll_usage_day()
        return self._amap_count

    @property
    def usage_day(self) -> str:
        self._roll_usage_day()
        return self._usage_day or datetime.now().strftime("%Y-%m-%d")

    def _roll_usage_day(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._usage_day != today:
            self._usage_day = today
            self._locate_count = 0
            self._amap_count = 0

    def restore_usage(
        self,
        *,
        locate: int | None = None,
        amap: int | None = None,
        day: str | None = None,
    ) -> None:
        if day:
            self._usage_day = day
        if locate is not None:
            self._locate_count = locate
        if amap is not None:
            self._amap_count = amap

    def bump_locate_count(self) -> None:
        self._roll_usage_day()
        self._locate_count += 1

    def bump_amap_count(self) -> None:
        self._roll_usage_day()
        self._amap_count += 1

    @staticmethod
    def _as_ts(value: Any) -> float | None:
        if value in (None, "", 0, "0"):
            return None
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None
        if n > 1e12:
            n /= 1000.0
        return n if n > 0 else None

    def _merge_with_last_known(self, devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from .device_tracker import _get_stable_device_id

        now = time.time()
        current_ids = set()
        for dev in devices:
            dev_id = _get_stable_device_id(dev)
            if not dev_id:
                continue
            current_ids.add(dev_id)
            is_fresh = dev.get("is_fresh", True)
            if is_fresh or dev_id not in self._last_known_devices:
                merged = dev.copy()
                cached = self._last_known_devices.get(dev_id)
                if cached and not merged.get("address") and cached.get("address"):
                    if (
                        merged.get("latitude") == cached.get("latitude")
                        and merged.get("longitude") == cached.get("longitude")
                    ):
                        merged["address"] = cached.get("address")
                        if cached.get("address_time"):
                            merged["address_time"] = cached.get("address_time")
                self._last_known_devices[dev_id] = merged
            else:
                merged = self._last_known_devices[dev_id].copy()
                for k, v in dev.items():
                    if k not in ("latitude", "longitude", "ts", "address", "address_time"):
                        merged[k] = v
                if dev.get("latitude") is not None and dev.get("longitude") is not None:
                    new_ts = self._as_ts(dev.get("ts"))
                    old_ts = self._as_ts(merged.get("ts"))
                    if new_ts is not None and (old_ts is None or new_ts > old_ts):
                        merged["latitude"] = dev.get("latitude")
                        merged["longitude"] = dev.get("longitude")
                        merged["ts"] = dev.get("ts")
                        if dev.get("address"):
                            merged["address"] = dev.get("address")
                        if dev.get("address_time"):
                            merged["address_time"] = dev.get("address_time")
                self._last_known_devices[dev_id] = merged
            self._last_known_timestamps[dev_id] = now

        merged = list(devices)
        for i, dev in enumerate(merged):
            dev_id = _get_stable_device_id(dev)
            if dev_id and dev_id in self._last_known_devices:
                merged[i] = self._last_known_devices[dev_id]

        expired_ids = []
        for cached_id, cached_dev in self._last_known_devices.items():
            if cached_id not in current_ids:
                cached_time = self._last_known_timestamps.get(cached_id, 0)
                age = now - cached_time
                if age < self._device_cache_ttl:
                    _LOGGER.debug(f"[DeviceCache] {cached_id[:12]}... 使用缓存（{int(age)}s 前）")
                    merged.append(cached_dev)
                else:
                    expired_ids.append(cached_id)

        for eid in expired_ids:
            self._last_known_devices.pop(eid, None)
            self._last_known_timestamps.pop(eid, None)
            self._geocode_cache.pop(eid, None)

        return merged

    def _should_use_low_battery_interval(self, devices: list[dict[str, Any]]) -> bool:
        for device in devices:
            battery = device.get("battery")
            if battery is None:
                continue
            try:
                if int(battery) <= LOW_BATTERY_PERCENT:
                    return True
            except (ValueError, TypeError):
                pass
        return False

    def _normal_interval(self) -> int:
        raw = self.entry.options.get(
            CONF_INTERVAL,
            self.entry.data.get(CONF_INTERVAL, DEFAULT_INTERVAL),
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_INTERVAL
        if value < 60:
            value *= 60
        return value

    def _update_interval_dynamically(self, devices: list[dict[str, Any]]) -> None:
        normal_interval = self._normal_interval()
        target = normal_interval * 2 if self._should_use_low_battery_interval(devices) else normal_interval

        if target != self._current_interval:
            self._current_interval = target
            self.update_interval = timedelta(seconds=target)
            _LOGGER.info(f"[Coordinator] 轮询间隔调整为 {target}s")

    def _cancel_auth_retry(self) -> None:
        if self._auth_retry_unsub:
            self._auth_retry_unsub()
            self._auth_retry_unsub = None

    def _schedule_auth_retry(self) -> None:
        if self._auth_retry_count >= 8:
            return
        self._cancel_auth_retry()
        self._auth_retry_count += 1
        from homeassistant.helpers.event import async_call_later

        async def _retry(_now=None) -> None:
            self._auth_retry_unsub = None
            await self.async_request_refresh()

        self._auth_retry_unsub = async_call_later(self.hass, 15, _retry)
        _LOGGER.info(
            f"[Sync] 认证暂态，{15}s 后重试 ({self._auth_retry_count}/8)"
        )

    @staticmethod
    def _has_fresh_device(devices: list[dict[str, Any]]) -> bool:
        return any(d.get("is_fresh") for d in devices)

    async def async_request_active_locate(self, force: bool = False) -> dict[str, Any]:
        async with self._refresh_lock:
            now = time.time()
            if not force and (now - self._last_locate_time) < self._min_locate_interval:
                wait_time = int(self._min_locate_interval - (now - self._last_locate_time))
                _LOGGER.warning(f"[ActiveLocate] 限频：需等待 {wait_time}s")
                if self.data:
                    return self.data
                raise UpdateFailed(f"限频保护：请等待 {wait_time} 秒后重试")

            raw = await self._call_sync(force_locate=True)
            result = await self._process_sync_result(raw)
            devices = result.get("devices", [])
            if raw.get("code") == 0 and self._has_fresh_device(devices):
                self.bump_locate_count()
                self._last_locate_time = time.time()
            if result.get("auth_pending"):
                self._schedule_auth_retry()
            else:
                self._auth_retry_count = 0
                self._cancel_auth_retry()
            self.async_set_updated_data(result)
            return result

    async def _async_update_data(self) -> dict[str, Any]:
        if self._refresh_lock.locked():
            if self.data:
                return self.data
            raise UpdateFailed("同步任务已在进行中")

        async with self._refresh_lock:
            start_time = time.time()

            if not self._credentials_sent:
                await self._send_credentials()
                self._credentials_sent = True

            use_page_location = self.entry.options.get(
                CONF_USE_PAGE_LOCATION,
                self.entry.data.get(CONF_USE_PAGE_LOCATION, DEFAULT_USE_PAGE_LOCATION),
            )
            force_locate = False
            prev_pending = bool(self.data and self.data.get("auth_pending"))

            if use_page_location:
                now = time.time()
                if prev_pending or (now - self._last_locate_time) >= self._min_locate_interval:
                    force_locate = True

            raw_result = await self._call_sync(force_locate=force_locate)
            result = await self._process_sync_result(raw_result)
            if raw_result.get("auth_pending") and not result.get("auth_pending"):
                result = dict(result)
                result["auth_pending"] = True
                result["auth_reason"] = raw_result.get("auth_reason") or raw_result.get("reason")
            devices = result.get("devices", [])

            if (
                force_locate
                and raw_result.get("code") == 0
                and self._has_fresh_device(devices)
                and not result.get("auth_pending")
            ):
                self.bump_locate_count()
                self._last_locate_time = time.time()

            if result.get("auth_pending"):
                self._schedule_auth_retry()
            else:
                self._auth_retry_count = 0
                self._cancel_auth_retry()

            elapsed = int((time.time() - start_time) * 1000)
            active = result.get("active", False)

            if devices:
                self._update_interval_dynamically(devices)

            if len(devices) != self._last_device_count or elapsed > 1000 or result.get("auth_pending"):
                fresh_count = sum(1 for d in devices if d.get("is_fresh", True))
                _LOGGER.info(
                    f"[Sync] 设备={len(devices)} | active={active} | "
                    f"force_locate={force_locate} | "
                    f"auth_pending={bool(result.get('auth_pending'))} | "
                    f"is_fresh={fresh_count}/{len(devices)} | {elapsed}ms"
                )
                self._last_device_count = len(devices)

            return result

    async def _process_sync_result(self, result: dict[str, Any]) -> dict[str, Any]:
        code = result.get("code", -1)
        message = result.get("message", "")

        if code == 990 or result.get("need_reauth"):
            reason = result.get("reason", "AUTH_EXPIRED")
            _LOGGER.info(f"[Sync] 需要认证 | code={code} | reason={reason}")

            if reason == "CAPTCHA_REQUIRED" and not self._need_reauth_notified:
                async_create(
                    self.hass,
                    f"荣耀云服务需要验证码认证。\n\n后端无法自动登录，请手动访问：\n{self._base_url}/auth/ensure",
                    title="荣耀云服务 - 需要验证码",
                    notification_id=f"honor_cloud_captcha_{self.entry.entry_id}",
                )
                self._need_reauth_notified = True
            elif (
                reason in ["NO_SESSION", "AUTH_EXPIRED", "NOT_LOGGED_IN", "LOGIN_IN_PROGRESS"]
                and not self._need_reauth_notified
                and not self._last_known_devices
            ):
                async_create(
                    self.hass,
                    "荣耀云服务后台登录中...\n\n首次登录可能需要 60-120 秒，请稍候。",
                    title="荣耀云服务 - 后台登录",
                    notification_id=f"honor_cloud_login_{self.entry.entry_id}",
                )
                self._need_reauth_notified = True

            if self._last_known_devices:
                preserved = dict(self.data) if self.data else {}
                preserved["code"] = 0
                preserved["devices"] = list(self._last_known_devices.values())
                preserved.pop("need_reauth", None)
                preserved.pop("reason", None)
                preserved["auth_pending"] = True
                preserved["auth_reason"] = reason
                if "active" in result:
                    preserved["active"] = result.get("active")
                _LOGGER.info(
                    f"[Sync] 认证暂态，保留缓存设备 {len(preserved['devices'])} 台 | reason={reason}"
                )
                return preserved

            return result

        if code == -1:
            _LOGGER.debug(f"[Sync] 网络错误: {message}")
            if self._last_known_devices:
                result["devices"] = list(self._last_known_devices.values())
            return result

        if code == 0:
            self._need_reauth_notified = False
            devices = result.get("devices", [])

            if devices:
                result["devices"] = self._merge_with_last_known(devices)
            elif self._last_known_devices:
                result["devices"] = list(self._last_known_devices.values())

            if result.get("auth_pending"):
                return result

            devices = result.get("devices", [])
            if self._amap_enabled() and self._get_amap_api_key() and devices:
                await self._geocode_devices(devices)
                result["devices"] = devices
            if devices:
                from .commute import update_commute
                await update_commute(self, devices)

            return result

        _LOGGER.warning(f"[Sync] 未知状态 | code={code} | message={message}")
        if not result.get("devices") and self._last_known_devices:
            result["devices"] = list(self._last_known_devices.values())
        return result

    async def _geocode_devices(self, devices: list[dict[str, Any]]) -> None:
        from .device_tracker import _get_stable_device_id, wgs84_to_gcj02

        if not self._amap_enabled():
            return

        key = self._get_amap_api_key()
        if not key:
            return

        limit = self._get_amap_daily_limit()
        self._roll_usage_day()
        if self._amap_count >= limit:
            _LOGGER.warning(
                f"[Geocode] 今日高德调用已达上限 {self._amap_count}/{limit}，跳过"
            )
            for device in devices:
                device_id = _get_stable_device_id(device)
                if not device_id:
                    continue
                cached = self._geocode_cache.get(device_id)
                if cached and cached.get("address") and not device.get("address"):
                    device["address"] = cached["address"]
                    if cached.get("timestamp"):
                        device["address_time"] = int(cached["timestamp"])
            return

        session = aiohttp_client.async_get_clientsession(self.hass)
        now = time.time()

        for device in devices:
            if self._amap_count >= limit:
                _LOGGER.warning(f"[Geocode] 达到日限额 {limit}，停止本次剩余请求")
                break

            device_id = _get_stable_device_id(device)
            if not device_id:
                continue

            wgs_lat = device.get("latitude")
            wgs_lng = device.get("longitude")
            if wgs_lat is None or wgs_lng is None:
                continue

            try:
                wgs_lat_f = float(wgs_lat)
                wgs_lng_f = float(wgs_lng)
            except (TypeError, ValueError):
                continue

            gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng_f, wgs_lat_f)
            grid = _amap_grid(gcj_lng, gcj_lat)
            exact_key = (round(gcj_lat, 5), round(gcj_lng, 5))
            cached = self._geocode_cache.get(device_id)

            if cached and cached.get("address"):
                if cached.get("exact") == exact_key or cached.get("grid") == grid:
                    device["address"] = cached["address"]
                    if cached.get("timestamp"):
                        device["address_time"] = int(cached["timestamp"])
                    continue

            address = await self._gaode_reverse_geocode(session, key, gcj_lng, gcj_lat)
            if not address:
                if cached and cached.get("address"):
                    device["address"] = cached["address"]
                continue

            self.bump_amap_count()
            device["address"] = address
            device["address_time"] = int(now)
            self._geocode_cache[device_id] = {
                "address": address,
                "grid": grid,
                "exact": exact_key,
                "timestamp": now,
            }
            if device_id in self._last_known_devices:
                self._last_known_devices[device_id]["address"] = address
                self._last_known_devices[device_id]["address_time"] = int(now)

    async def _gaode_reverse_geocode(
        self,
        session: aiohttp.ClientSession,
        key: str,
        gcj_lng: float,
        gcj_lat: float,
    ) -> str | None:
        try:
            async with session.get(
                "https://restapi.amap.com/v3/geocode/regeo",
                params={
                    "key": key,
                    "location": f"{gcj_lng:.6f},{gcj_lat:.6f}",
                    "extensions": "base",
                    "output": "json",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(f"[Geocode] HTTP {resp.status}")
                    return None
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            _LOGGER.warning(f"[Geocode] 请求失败: {err}")
            return None

        if str(data.get("status")) != "1":
            _LOGGER.warning(
                f"[Geocode] 失败: info={data.get('info')} infocode={data.get('infocode')}"
            )
            return None

        geo = data.get("regeocode") or {}
        address = _amap_text(geo.get("formatted_address"))
        return address

    async def _send_credentials(self):
        try:
            from .const import CONF_USERNAME, CONF_PASSWORD

            username = self.entry.options.get(CONF_USERNAME, "")
            password = self.entry.options.get(CONF_PASSWORD, "")

            if not username or not password:
                _LOGGER.warning("[Sync] 未配置用户名/密码")
                return

            url = f"{self._base_url}/auth/ensure"
            body = {"session_key": self._session_key, "username": username, "password": password}

            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    _LOGGER.info("[Sync] 凭据已发送到后端")
                else:
                    _LOGGER.warning(f"[Sync] 发送凭据失败 HTTP {resp.status}")
        except Exception as e:
            _LOGGER.error(f"[Sync] 发送凭据异常: {e}")

    async def _call_sync(self, force_locate: bool = False) -> dict[str, Any]:
        url = f"{self._base_url}/sync"
        body = {"session_key": self._session_key, "force_locate": force_locate}
        timeout = 65 if force_locate else 15

        session = aiohttp_client.async_get_clientsession(self.hass)

        try:
            async with session.post(
                url, json=body, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    _LOGGER.warning(f"[Sync] HTTP {resp.status}: {text[:100]}")
                    raise UpdateFailed(f"HTTP {resp.status}")
                return await resp.json()

        except asyncio.TimeoutError as err:
            _LOGGER.debug(f"[Sync] 超时 (force_locate={force_locate})")
            raise UpdateFailed("请求超时") from err
        except aiohttp.ClientError as err:
            _LOGGER.debug(f"[Sync] 网络错误: {err}")
            raise UpdateFailed(f"网络错误: {err}") from err


class StatusCoordinator(DataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        try:
            super().__init__(
                hass,
                _LOGGER,
                config_entry=entry,
                name="荣耀云状态",
                update_interval=timedelta(seconds=60),
            )
        except TypeError:
            super().__init__(
                hass,
                _LOGGER,
                name="荣耀云状态",
                update_interval=timedelta(seconds=60),
            )
        self.entry = entry
        self.hass = hass
        self._session_key = entry.data[CONF_SESSION_KEY]

    @property
    def _base_url(self) -> str:
        return self.entry.data[CONF_BASE_URL].rstrip("/")

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.get(
                f"{self._base_url}/status",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return {"logged_in": False, "error": f"HTTP {resp.status}"}
                return await resp.json()
        except Exception as err:
            _LOGGER.debug(f"[Status] 检查失败: {err}")
            return {"logged_in": False, "error": str(err)}
