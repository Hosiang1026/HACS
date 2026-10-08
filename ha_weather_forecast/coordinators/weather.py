from __future__ import annotations

from datetime import timedelta
import logging
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..apis.caiyun import fetch_caiyun
from ..apis.qweather import fetch_qweather
from ..apis.tianqi import _day_is_rain, build_rain_payload, condition_label, fetch_tianqi
from ..city_resolve import resolve_slug
from ..const import (
    CONF_API_HOST,
    CONF_API_KEY,
    CONF_FORECAST_DAYS,
    CONF_INDICES_ENABLED,
    CONF_INTERVAL,
    CONF_LOCATION,
    CONF_NAME,
    CONF_NOTIFY_ALARM,
    CONF_NOTIFY_ALARM_ANNOUNCE,
    CONF_NOTIFY_ALARM_NOTIFY,
    CONF_NOTIFY_RAIN,
    CONF_NOTIFY_RAIN_ANNOUNCE,
    CONF_NOTIFY_RAIN_NOTIFY,
    CONF_PROVIDER,
    CONF_SLUG,
    DEFAULT_FORECAST_DAYS,
    DEFAULT_WEATHER_IDLE_INTERVAL,
    DEFAULT_WEATHER_INTERVAL,
    DOMAIN,
    PROVIDER_CAIYUN,
    PROVIDER_QWEATHER,
    PROVIDER_TIANQI,
)
from ..notify_util import async_send_notify, channel_targets
from ..weather_schedule import calc_weather_interval_minutes
from .update_stamp import mark_updated

_LOGGER = logging.getLogger(__name__)


_WEATHER_ICON = {
    "晴": "🌤",
    "雾": "🌫",
    "霾": "🌫",
    "多云": "🌥",
    "阴": "☁",
    "小雨": "🌨",
    "中雨": "🌧",
    "大雨": "⛈",
}


def _weather_icon(weather: str) -> str:
    if weather in _WEATHER_ICON:
        return _WEATHER_ICON[weather]
    if "晴" in weather:
        return "🌤"
    if "雨" in weather:
        return "🌨"
    return ""


def _sk(data: dict[str, Any]) -> dict[str, Any]:
    raw = data.get("raw_sk")
    return raw if isinstance(raw, dict) else {}


def _wind_text(data: dict[str, Any]) -> str:
    sk = _sk(data)
    wd = data.get("wind_dir") or sk.get("WD") or "未知"
    ws = data.get("wind_scale") or sk.get("WS") or ""
    wse = sk.get("wse") or ""
    if not wse and data.get("wind_speed") is not None:
        wse = f"({data.get('wind_speed')}km/h)"
    return f"{wd}{ws}{wse}"


def _num(val: Any, default: str = "0") -> str:
    if val in (None, ""):
        return default
    try:
        return f"{float(val):g}"
    except (TypeError, ValueError):
        return str(val)


def _cn_label(code: Any, text: str = "") -> str:
    label = condition_label(code) if code is not None else ""
    if label and re.search(r"[\u4e00-\u9fff]", str(label)):
        return str(label)
    return str(text or "")


def _temp_humid_rain(data: dict[str, Any]) -> str:
    sk = _sk(data)
    temp = data.get("temp")
    if temp is None:
        temp = sk.get("temp")
    sd = sk.get("sd")
    if sd in (None, ""):
        h = data.get("humidity")
        sd = f"{h:g}%" if h is not None else "未知"
    rain = sk.get("rain")
    if rain in (None, ""):
        rain = _num(data.get("rain"), "0")
    return f"{_num(temp)}°C {sd} {rain}mm"


def _obs_time(data: dict[str, Any]) -> str:
    sk = _sk(data)
    date = re.sub(r"\(星期[一二三四五六日]\)", "", str(sk.get("date") or "")).strip()
    time_s = str(sk.get("time") or "").strip()
    if date or time_s:
        return f"{date} {time_s}".strip()
    ut = data.get("update_time")
    if isinstance(ut, (int, float)):
        try:
            t = dt_util.as_local(dt_util.utc_from_timestamp(float(ut)))
            return f"{t.month}月{t.day}日 {t.strftime('%H:%M')}"
        except (OSError, OverflowError, ValueError):
            pass
    uts = str(ut or "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}:\d{2})", uts)
    if m:
        return f"{int(m.group(2))}月{int(m.group(3))}日 {m.group(4)}"
    if uts:
        return uts
    now = dt_util.now()
    return f"{now.month}月{now.day}日 {now.strftime('%H:%M')}"


def _hm(val: Any) -> str:
    s = str(val or "").strip()
    m = re.search(r"(\d{1,2}:\d{2})", s)
    return m.group(1) if m else s


def _live_weather(city: str, data: dict[str, Any]) -> str:
    weather = str(data.get("condition_desc") or _sk(data).get("weather") or "未知")
    icon = _weather_icon(weather)
    weather_line = f"· 天气: {weather} {icon}".rstrip()
    return "\n".join(
        [
            "🌈实时天气信息",
            "",
            f"🚩{city}",
            "",
            weather_line,
            f"· 风况: {_wind_text(data)}",
            f"· 温湿度: {_temp_humid_rain(data)}",
            f"· 预报时间: {_obs_time(data)}",
        ]
    )


def _alarm_section(alarms: list[Any]) -> str:
    texts: list[str] = []
    for a in alarms:
        if not isinstance(a, dict):
            continue
        t = str(a.get("w9") or a.get("w5") or a.get("w3") or "").strip()
        if not t:
            t = f"{a.get('w1', '')}{a.get('w2', '')}".strip() or "未知"
        texts.append(t)
    if not texts:
        return ""
    return "🚨天气预警信息\n\n" + "\n".join(texts)


def _rain_section(data: dict[str, Any], payload: dict[str, Any]) -> str:
    lines: list[str] = []
    sig = str(payload.get("sig") or "")
    minutely = data.get("minutely") if isinstance(data.get("minutely"), dict) else {}
    if "m:" in sig:
        try:
            precip = float(minutely.get("precip") or 0)
        except (TypeError, ValueError):
            precip = 0.0
        lines.append(f"· 雨量: {precip:g}mm" if precip > 0 else "· 雨量: —")
        start, end = minutely.get("rain_start"), minutely.get("rain_end")
        if start and end:
            lines.append(f"· 时段: {_hm(start)} ~ {_hm(end)}")
        elif start:
            lines.append(f"· 开始: {_hm(start)}")
        m_msg = str(minutely.get("msg") or "").strip()
        lines.append(f"· 短时降雨: {m_msg or payload.get('carousel_rain') or '有雨'}")
    elif "now:" in sig:
        rain_now = data.get("rain")
        rain24h = data.get("rain24h")
        if rain_now is not None:
            lines.append(f"· 当前雨量: {_num(rain_now)}mm")
        if rain24h is not None:
            lines.append(f"· 近24小时: {_num(rain24h)}mm")
    for i, day in enumerate(data.get("forecast") or []):
        if i > 2 or not isinstance(day, dict):
            continue
        if not _day_is_rain(day):
            continue
        fa, fb = day.get("fa"), day.get("fb")
        text = str(day.get("text") or "")
        day_l = _cn_label(fa, text)
        night_l = _cn_label(fb, "")
        weather = "转".join(x for x in (day_l or text, night_l) if x) or "有雨"
        date = day.get("fi") or ("今日" if i == 0 else "明日")
        precip = day.get("precip")
        if precip is None:
            precip = day.get("precipitation")
        amt = f"{_num(precip, '')}mm" if precip not in (None, "") else "—"
        row = f"· 预报: {date} {weather} 雨量 {amt}"
        if day.get("fd") is not None or day.get("fc") is not None:
            row += f" {day.get('fd')}~{day.get('fc')}℃"
        lines.append(row)
    if not lines:
        return ""
    return "🌧降雨信息\n\n" + "\n".join(lines)


def _rain_rank(sig: str) -> int:
    rank = {"L": 1, "M": 2, "H": 3}
    best = 0
    for part in str(sig).split("|"):
        best = max(best, rank.get(part.rsplit(":", 1)[-1], 0))
    return best


def _notify_body(*sections: str) -> str:
    parts = [s.strip() for s in sections if s and str(s).strip()]
    return "\n\n".join(parts)


class WeatherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        instance: dict[str, Any],
        entry_opts: dict[str, Any],
    ) -> None:
        self.entry = entry
        self.instance = instance
        self.entry_opts = entry_opts
        self.city_name = instance.get(CONF_NAME) or "天气"
        self.slug = resolve_slug(
            self.city_name,
            instance.get(CONF_SLUG),
            str(instance.get(CONF_LOCATION) or "city"),
        )
        self.provider = instance.get(CONF_PROVIDER) or PROVIDER_TIANQI
        self.device_id = f"{entry.entry_id}_weather_{self.slug}"
        self.device_name = f"天气预报 · {self.city_name}"
        self._last_alarm_sig: str | None = None
        self._last_rain_sig: str | None = None
        self._last_rain_rank = 0
        self._last_rain_at = None
        self.last_update_at = None
        minutes = calc_weather_interval_minutes(
            peak_minutes=int(instance.get(CONF_INTERVAL) or DEFAULT_WEATHER_INTERVAL),
            idle_minutes=DEFAULT_WEATHER_IDLE_INTERVAL,
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_weather_{self.slug}",
            update_interval=timedelta(minutes=max(1, minutes)),
        )

    def _apply_interval(self) -> None:
        minutes = calc_weather_interval_minutes(
            peak_minutes=int(
                self.instance.get(CONF_INTERVAL) or DEFAULT_WEATHER_INTERVAL
            ),
            idle_minutes=DEFAULT_WEATHER_IDLE_INTERVAL,
        )
        self.update_interval = timedelta(minutes=max(1, minutes))

    async def _async_update_data(self) -> dict[str, Any]:
        location = self.instance.get(CONF_LOCATION)
        if not location:
            raise UpdateFailed("missing location")
        session = async_get_clientsession(self.hass)
        days = int(self.instance.get(CONF_FORECAST_DAYS) or DEFAULT_FORECAST_DAYS)
        api_key = self.instance.get(CONF_API_KEY) or ""
        api_host = self.instance.get(CONF_API_HOST) or ""
        try:
            if self.provider == PROVIDER_TIANQI:
                data = await fetch_tianqi(session, str(location), days)
            elif self.provider == PROVIDER_QWEATHER:
                data = await fetch_qweather(
                    session,
                    str(location),
                    api_key,
                    host=api_host or "api.qweather.com",
                    forecast_days=days,
                )
            elif self.provider == PROVIDER_CAIYUN:
                data = await fetch_caiyun(
                    session, str(location), api_key, forecast_days=days
                )
            else:
                raise UpdateFailed(f"provider not implemented: {self.provider}")
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err

        if not self.instance.get(CONF_INDICES_ENABLED, True):
            data["indices"] = {}

        await self._maybe_notify(data)
        await self._maybe_notify_rain(data)
        mark_updated(self)
        self._apply_interval()
        return data

    async def _maybe_notify(self, data: dict[str, Any]) -> None:
        if not self.instance.get(CONF_NOTIFY_ALARM, True):
            return
        alarms = data.get("alarms") or []
        sig = "|".join(
            sorted(
                f"{a.get('w1','')}-{a.get('w2','')}-{a.get('w3','')}"
                for a in alarms
                if isinstance(a, dict)
            )
        )
        if not sig or sig == self._last_alarm_sig:
            self._last_alarm_sig = sig or self._last_alarm_sig
            return
        self._last_alarm_sig = sig
        text = _notify_body(_alarm_section(alarms))
        await async_send_notify(
            self.hass,
            self.entry_opts,
            self.instance,
            f"{self.city_name}天气预警",
            text,
            carousel=text,
            channel=channel_targets(
                self.instance,
                self.entry_opts,
                CONF_NOTIFY_ALARM_NOTIFY,
                CONF_NOTIFY_ALARM_ANNOUNCE,
            ),
        )

    async def _maybe_notify_rain(self, data: dict[str, Any]) -> None:
        if not self.instance.get(CONF_NOTIFY_RAIN, True):
            return
        payload = build_rain_payload(data)
        now = dt_util.now()
        if not payload:
            if (
                self._last_rain_at is not None
                and now - self._last_rain_at >= timedelta(hours=3)
            ):
                self._last_rain_sig = None
                self._last_rain_rank = 0
            return
        sig = payload.get("sig") or ""
        if not sig or sig == self._last_rain_sig:
            return
        rank = _rain_rank(sig)
        if (
            self._last_rain_at is not None
            and now - self._last_rain_at < timedelta(hours=3)
            and rank <= self._last_rain_rank
        ):
            self._last_rain_sig = sig
            return
        self._last_rain_sig = sig
        self._last_rain_rank = rank
        self._last_rain_at = now
        text = _notify_body(_rain_section(data, payload))
        await async_send_notify(
            self.hass,
            self.entry_opts,
            self.instance,
            f"{self.city_name}降雨提醒",
            text,
            carousel=text,
            channel=channel_targets(
                self.instance,
                self.entry_opts,
                CONF_NOTIFY_RAIN_NOTIFY,
                CONF_NOTIFY_RAIN_ANNOUNCE,
            ),
        )
