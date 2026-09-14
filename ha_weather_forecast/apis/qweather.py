from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout

from .tianqi import map_condition

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=20)

_QW_CONDITION = {
    "100": "sunny",
    "101": "partlycloudy",
    "102": "partlycloudy",
    "103": "partlycloudy",
    "104": "cloudy",
    "150": "clear-night",
    "300": "rainy",
    "301": "rainy",
    "302": "lightning-rainy",
    "303": "lightning-rainy",
    "304": "hail",
    "305": "rainy",
    "306": "rainy",
    "307": "pouring",
    "308": "pouring",
    "309": "rainy",
    "310": "pouring",
    "311": "pouring",
    "312": "pouring",
    "313": "rainy",
    "400": "snowy",
    "401": "snowy",
    "402": "snowy",
    "403": "snowy",
    "404": "snowy-rainy",
    "405": "snowy-rainy",
    "406": "snowy-rainy",
    "407": "snowy",
    "500": "fog",
    "501": "fog",
    "502": "fog",
    "503": "fog",
    "504": "fog",
    "507": "dust",
    "508": "dust",
    "900": "exceptional",
    "901": "exceptional",
}


def _headers(api_key: str) -> dict[str, str]:
    return {
        "X-QW-Api-Key": api_key,
        "Accept-Encoding": "gzip",
        "User-Agent": "HomeAssistant-ha_general_info",
    }


def _to_float(val: Any) -> float | None:
    try:
        if val in (None, ""):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


async def search_qweather(
    session: ClientSession, query: str, api_key: str, host: str = "geoapi.qweather.com"
) -> list[dict[str, str]]:
    url = f"https://{host}/v2/city/lookup?location={quote(query)}&lang=zh&key={api_key}"
    async with session.get(url, headers=_headers(api_key), timeout=_TIMEOUT) as resp:
        data = await resp.json(content_type=None)
    if str(data.get("code")) not in ("200", "204"):
        return []
    out: list[dict[str, str]] = []
    for item in data.get("location") or []:
        loc_id = item.get("id")
        name = item.get("name") or ""
        adm = item.get("adm2") or item.get("adm1") or ""
        label = f"{adm}-{name}" if adm and adm != name else name
        lon = item.get("lon")
        lat = item.get("lat")
        out.append(
            {
                "area_id": loc_id,
                "name": label,
                "location": loc_id,
                "lon": str(lon or ""),
                "lat": str(lat or ""),
            }
        )
    return out


async def fetch_qweather(
    session: ClientSession,
    location: str,
    api_key: str,
    host: str = "api.qweather.com",
    forecast_days: int = 7,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError("qweather requires api_key")
    base = f"https://{host}/v7"
    headers = _headers(api_key)
    params = f"location={quote(location)}&lang=zh&key={api_key}"

    async def _get(path: str) -> dict[str, Any]:
        async with session.get(
            f"{base}/{path}?{params}", headers=headers, timeout=_TIMEOUT
        ) as resp:
            return await resp.json(content_type=None)

    now_data = await _get("weather/now")
    if str(now_data.get("code")) != "200":
        raise ValueError(f"qweather now failed: {now_data.get('code')}")
    now = now_data.get("now") or {}

    days = 7 if forecast_days <= 7 else 15
    daily_data = await _get(f"weather/{days}d")
    forecast = []
    for day in (daily_data.get("daily") or [])[:forecast_days]:
        forecast.append(
            {
                "fi": day.get("fxDate") or "",
                "fa": day.get("iconDay"),
                "fc": day.get("tempMax"),
                "fd": day.get("tempMin"),
                "fn": day.get("humidity"),
                "text": day.get("textDay"),
                "precip": _to_float(day.get("precip")),
                "pop": _to_float(day.get("pop")),
            }
        )

    hourly: list[dict[str, Any]] = []
    try:
        hour_data = await _get("weather/24h")
        if str(hour_data.get("code")) == "200":
            for h in (hour_data.get("hourly") or [])[:24]:
                hourly.append(
                    {
                        "fxTime": h.get("fxTime"),
                        "fa": h.get("icon"),
                        "temp": h.get("temp"),
                        "humidity": h.get("humidity"),
                        "text": h.get("text"),
                        "precip": _to_float(h.get("precip")),
                        "pop": _to_float(h.get("pop")),
                    }
                )
    except Exception:  # noqa: BLE001
        pass

    aqi = None
    try:
        air = await _get("air/now")
        if str(air.get("code")) == "200":
            aqi = _to_float((air.get("now") or {}).get("aqi"))
    except Exception:  # noqa: BLE001
        pass

    alarms: list[dict[str, Any]] = []
    try:
        warn = await _get("warning/now")
        if str(warn.get("code")) == "200":
            for w in warn.get("warning") or []:
                alarms.append(
                    {
                        "w1": w.get("typeName") or "",
                        "w2": w.get("level") or "",
                        "w3": w.get("title") or "",
                        "w5": w.get("text") or "",
                    }
                )
    except Exception:  # noqa: BLE001
        pass

    indices: dict[str, Any] = {}
    try:
        async with session.get(
            f"{base}/indices/1d?{params}&type=0",
            headers=headers,
            timeout=_TIMEOUT,
        ) as resp:
            idx = await resp.json(content_type=None)
        if str(idx.get("code")) == "200":
            for item in idx.get("daily") or []:
                key = str(item.get("type") or item.get("name") or len(indices))
                indices[key] = {
                    "name": item.get("name"),
                    "level": item.get("category"),
                    "hint": item.get("text"),
                }
    except Exception:  # noqa: BLE001
        pass

    icon = now.get("icon")
    text = now.get("text")
    summary = None
    if forecast:
        d0 = forecast[0]
        summary = f"{d0.get('text') or ''} {d0.get('fd')}~{d0.get('fc')}℃".strip()

    rain_f = _to_float(now.get("precip"))
    minutely: dict[str, Any] = {}
    try:
        from .tianqi import _rain_window

        mdata = await _get("minutely/5m")
        if str(mdata.get("code")) == "200":
            times = list(mdata.get("minutely") or [])
            tlist = [x.get("fxTime") for x in times if isinstance(x, dict)]
            vlist = [x.get("precip") for x in times if isinstance(x, dict)]
            start, end, total = _rain_window(tlist, vlist)
            msg = mdata.get("summary") or ""
            minutely = {
                "msg": msg,
                "ph": "rain" if total > 0 or "雨" in str(msg) else None,
                "times": tlist,
                "values": vlist,
                "rain_start": start,
                "rain_end": end,
                "precip": total,
            }
    except Exception:  # noqa: BLE001
        pass

    return {
        "temp": _to_float(now.get("temp")),
        "feels": _to_float(now.get("feelsLike")),
        "humidity": _to_float(now.get("humidity")),
        "condition": _QW_CONDITION.get(str(icon), map_condition(None, text)),
        "condition_desc": text,
        "aqi": aqi,
        "pressure": now.get("pressure"),
        "wind_dir": now.get("windDir"),
        "wind_scale": now.get("windScale"),
        "wind_speed": _to_float(now.get("windSpeed")),
        "wind_bearing": _to_float(now.get("wind360")),
        "visibility": now.get("vis"),
        "update_time": now.get("obsTime"),
        "rain": rain_f,
        "rain24h": None,
        "minutely": minutely,
        "alarms": alarms,
        "indices": indices,
        "forecast": forecast,
        "hourly": hourly,
        "forecast_summary": summary,
        "raw_sk": now,
    }
