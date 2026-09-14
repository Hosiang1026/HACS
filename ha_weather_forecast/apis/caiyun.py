from __future__ import annotations

from typing import Any
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout

_TIMEOUT = ClientTimeout(total=20)

_SKYCON = {
    "CLEAR_DAY": "sunny",
    "CLEAR_NIGHT": "clear-night",
    "PARTLY_CLOUDY_DAY": "partlycloudy",
    "PARTLY_CLOUDY_NIGHT": "partlycloudy",
    "CLOUDY": "cloudy",
    "LIGHT_HAZE": "fog",
    "MODERATE_HAZE": "fog",
    "HEAVY_HAZE": "fog",
    "LIGHT_RAIN": "rainy",
    "MODERATE_RAIN": "rainy",
    "HEAVY_RAIN": "pouring",
    "STORM_RAIN": "pouring",
    "FOG": "fog",
    "LIGHT_SNOW": "snowy",
    "MODERATE_SNOW": "snowy",
    "HEAVY_SNOW": "snowy",
    "STORM_SNOW": "snowy",
    "DUST": "dust",
    "SAND": "dust",
    "WIND": "windy",
}


def _to_float(val: Any) -> float | None:
    try:
        if val in (None, ""):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def parse_lonlat(location: str) -> tuple[str, str]:
    parts = [p.strip() for p in str(location).split(",")]
    if len(parts) != 2:
        raise ValueError("caiyun location must be lon,lat")
    return parts[0], parts[1]


async def fetch_caiyun(
    session: ClientSession,
    location: str,
    api_key: str,
    api_version: str = "v2.6",
    forecast_days: int = 7,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("caiyun requires api_key")
    lon, lat = parse_lonlat(location)
    url = (
        f"https://api.caiyunapp.com/{api_version}/{api_key}/"
        f"{quote(lon)},{quote(lat)}/weather.json"
        f"?dailysteps={max(1, forecast_days)}&hourlysteps=24&alert=true&unit=metric:v2"
    )
    async with session.get(url, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    if data.get("status") != "ok":
        raise ValueError(f"caiyun failed: {data.get('error') or data.get('status')}")
    result = data.get("result") or {}
    realtime = result.get("realtime") or {}
    skycon = realtime.get("skycon")
    daily = (result.get("daily") or {})
    temp_arr = (daily.get("temperature") or [])[:forecast_days]
    sky_arr = (daily.get("skycon") or [])[:forecast_days]
    hum_arr = (daily.get("humidity") or [])[:forecast_days]
    precip_arr = (daily.get("precipitation") or [])[:forecast_days]
    forecast: list[dict[str, Any]] = []
    for i, temp in enumerate(temp_arr):
        raw_date = temp.get("date") or ""
        date = raw_date[:10] if len(raw_date) >= 10 else raw_date[5:10].replace("-", "/")
        sky = (
            sky_arr[i].get("value")
            if i < len(sky_arr) and isinstance(sky_arr[i], dict)
            else skycon
        )
        hum = hum_arr[i].get("avg") if i < len(hum_arr) else None
        precip = None
        if i < len(precip_arr) and isinstance(precip_arr[i], dict):
            precip = _to_float(precip_arr[i].get("avg") or precip_arr[i].get("max"))
        forecast.append(
            {
                "fi": date,
                "fa": sky,
                "fc": temp.get("max"),
                "fd": temp.get("min"),
                "fn": round(float(hum) * 100, 1) if hum is not None else None,
                "text": sky,
                "precip": precip,
            }
        )

    hourly: list[dict[str, Any]] = []
    hourly_raw = result.get("hourly") or {}
    h_temp = hourly_raw.get("temperature") or []
    h_sky = hourly_raw.get("skycon") or []
    h_hum = hourly_raw.get("humidity") or []
    h_precip = hourly_raw.get("precipitation") or []
    for i, temp in enumerate(h_temp[:24]):
        if not isinstance(temp, dict):
            continue
        sky = h_sky[i].get("value") if i < len(h_sky) and isinstance(h_sky[i], dict) else skycon
        hum = h_hum[i].get("value") if i < len(h_hum) and isinstance(h_hum[i], dict) else None
        precip = None
        if i < len(h_precip) and isinstance(h_precip[i], dict):
            precip = _to_float(h_precip[i].get("value"))
        hourly.append(
            {
                "fxTime": temp.get("datetime") or temp.get("date"),
                "fa": sky,
                "temp": temp.get("value"),
                "humidity": round(float(hum) * 100, 1) if hum is not None else None,
                "precip": precip,
            }
        )

    alarms: list[dict[str, Any]] = []
    for a in result.get("alert", {}).get("content") or []:
        alarms.append(
            {
                "w1": a.get("title") or "",
                "w2": a.get("code") or "",
                "w3": a.get("description") or "",
                "w5": a.get("description") or "",
            }
        )
    life = realtime.get("life_index") or {}
    indices = {}
    if comfort := life.get("comfort"):
        indices["comfort"] = {
            "name": "舒适度",
            "level": comfort.get("index"),
            "hint": comfort.get("desc"),
        }
    if uv := life.get("ultraviolet"):
        indices["uv"] = {
            "name": "紫外线",
            "level": uv.get("index"),
            "hint": uv.get("desc"),
        }
    aqi = None
    air = realtime.get("air_quality") or {}
    if isinstance(air.get("aqi"), dict):
        aqi = _to_float(air["aqi"].get("chn"))
    else:
        aqi = _to_float(air.get("aqi"))
    summary = None
    if forecast:
        d0 = forecast[0]
        summary = f"{d0.get('text')} {d0.get('fd')}~{d0.get('fc')}℃"

    precip_rt = realtime.get("precipitation") or {}
    local = precip_rt.get("local") if isinstance(precip_rt, dict) else {}
    rain_f = _to_float((local or {}).get("intensity"))
    minutely_raw = result.get("minutely") or {}
    m_desc = minutely_raw.get("description") or ""
    m_vals = list(
        minutely_raw.get("precipitation_2h")
        or minutely_raw.get("precipitation")
        or []
    )
    try:
        total = round(sum(float(v or 0) for v in m_vals), 2)
    except (TypeError, ValueError):
        total = 0.0
    minutely = {
        "msg": m_desc,
        "ph": "rain" if total > 0 or "雨" in str(m_desc) else None,
        "times": [],
        "values": m_vals,
        "rain_start": None,
        "rain_end": None,
        "precip": total,
    }

    return {
        "temp": _to_float(realtime.get("temperature")),
        "feels": _to_float(realtime.get("apparent_temperature")),
        "humidity": (
            round(float(realtime.get("humidity")) * 100, 1)
            if realtime.get("humidity") is not None
            else None
        ),
        "condition": _SKYCON.get(str(skycon), "cloudy"),
        "condition_desc": skycon,
        "aqi": aqi,
        "pressure": (
            round(float(realtime.get("pressure")) / 100.0, 1)
            if realtime.get("pressure") is not None
            else None
        ),
        "wind_dir": (realtime.get("wind") or {}).get("direction"),
        "wind_scale": (realtime.get("wind") or {}).get("speed"),
        "wind_speed": _to_float((realtime.get("wind") or {}).get("speed")),
        "wind_bearing": (realtime.get("wind") or {}).get("direction"),
        "visibility": realtime.get("visibility"),
        "update_time": data.get("server_time"),
        "rain": rain_f,
        "rain24h": None,
        "minutely": minutely,
        "alarms": alarms,
        "indices": indices,
        "forecast": forecast,
        "hourly": hourly,
        "forecast_summary": summary,
        "raw_sk": realtime,
    }
