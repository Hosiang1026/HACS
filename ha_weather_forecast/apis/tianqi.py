from __future__ import annotations

import json
import logging
import re
from typing import Any

from aiohttp import ClientSession, ClientTimeout

_LOGGER = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
_REFERER = "https://m.weather.com.cn/"
_TIMEOUT = ClientTimeout(total=20)

_CONDITION_MAP = {
    "00": "sunny",
    "01": "partlycloudy",
    "02": "cloudy",
    "03": "rainy",
    "04": "lightning-rainy",
    "05": "lightning-rainy",
    "06": "snowy-rainy",
    "07": "rainy",
    "08": "rainy",
    "09": "rainy",
    "10": "pouring",
    "13": "snowy",
    "14": "snowy",
    "15": "snowy",
    "16": "snowy",
    "18": "fog",
    "19": "pouring",
    "20": "windy",
    "29": "dust",
    "30": "fog",
    "53": "fog",
}

_CONDITION_CN = {
    "00": "晴",
    "01": "多云",
    "02": "阴",
    "03": "阵雨",
    "04": "雷阵雨",
    "07": "小雨",
    "08": "中雨",
    "09": "大雨",
    "10": "暴雨",
    "13": "阵雪",
    "14": "小雪",
    "15": "中雪",
    "18": "雾",
}


def _headers() -> dict[str, str]:
    return {"User-Agent": _UA, "Referer": _REFERER}


def map_condition(weathercode: str | None, weather: str | None = None) -> str:
    code = (weathercode or "").replace("d", "").replace("n", "")
    if code in _CONDITION_MAP:
        return _CONDITION_MAP[code]
    text = weather or ""
    if "雨" in text and "雪" in text:
        return "snowy-rainy"
    if "雷" in text:
        return "lightning-rainy"
    if "雨" in text:
        return "rainy"
    if "雪" in text:
        return "snowy"
    if "雾" in text or "霾" in text:
        return "fog"
    if "阴" in text:
        return "cloudy"
    if "云" in text:
        return "partlycloudy"
    if "晴" in text:
        return "sunny"
    return "cloudy"


def condition_label(code: str | None) -> str:
    c = (code or "").replace("d", "").replace("n", "")
    return _CONDITION_CN.get(c, c or "")


def _build_tianqi_hourly(
    day0: dict[str, Any] | None,
    temp_now: float | None,
    weathercode: Any,
    weather: Any,
) -> list[dict[str, Any]]:
    from datetime import datetime, timedelta

    day0 = day0 or {}
    t_max = _to_float(day0.get("fc"))
    t_min = _to_float(day0.get("fd"))
    if t_max is None:
        t_max = temp_now
    if t_min is None:
        t_min = temp_now
    if t_max is None or t_min is None:
        return []
    fa = day0.get("fa") or weathercode
    fb = day0.get("fb") or fa
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    out: list[dict[str, Any]] = []
    for i in range(24):
        when = now + timedelta(hours=i)
        hour = when.hour
        # 粗略日变化：午后最高、清晨最低
        if 5 <= hour <= 14:
            ratio = (hour - 5) / 9
            temp = t_min + (t_max - t_min) * ratio
        elif 15 <= hour <= 23:
            ratio = (hour - 15) / 8
            temp = t_max - (t_max - t_min) * ratio * 0.6
        else:
            temp = t_min
        if i == 0 and temp_now is not None:
            temp = temp_now
        code = fa if 6 <= hour < 18 else fb
        out.append(
            {
                "fxTime": when.isoformat(timespec="minutes"),
                "fa": code,
                "temp": round(temp, 1),
                "text": weather if i == 0 else condition_label(code),
            }
        )
    return out


def _to_float(val: Any) -> float | None:
    try:
        if val in (None, ""):
            return None
        return float(str(val).replace("%", ""))
    except (TypeError, ValueError):
        return None


def _extract_json_assign(text: str, var_name: str) -> Any | None:
    m = re.search(rf"{re.escape(var_name)}\s*=\s*(\{{.*?\}})\s*;", text, re.S)
    if not m:
        m = re.search(rf"var\s+{re.escape(var_name)}\s*=\s*(\{{.*?\}})\s*;", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


async def _get_text(session: ClientSession, url: str) -> str:
    async with session.get(url, headers=_headers(), timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        return await resp.text(encoding="utf-8", errors="ignore")


def _parse_indices(zs: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(zs, dict):
        return {}
    out: dict[str, Any] = {}
    for key, val in zs.items():
        if not str(key).endswith("_name"):
            continue
        base = key[: -len("_name")]
        brief = zs.get(base)
        desc = zs.get(f"{base}_hint") or zs.get(f"{base}_des_s") or zs.get(
            f"{base}_des"
        )
        if brief in (None, ""):
            brief = zs.get(f"{base}_hint")
            desc = zs.get(f"{base}_des_s") or zs.get(f"{base}_des")
        out[base] = {
            "name": val,
            "level": brief,
            "hint": desc,
        }
    if not out:
        for key, val in zs.items():
            if key != "date":
                out[key] = val
    return out


_RAIN_CODES = {"03", "04", "05", "06", "07", "08", "09", "10", "19"}


def _code_is_rain(code: Any) -> bool:
    c = str(code or "").replace("d", "").replace("n", "")
    return c in _RAIN_CODES


def _rain_window(
    times: list[Any], values: list[Any]
) -> tuple[str | None, str | None, float]:
    pairs: list[tuple[str, float]] = []
    for t, v in zip(times, values):
        try:
            amt = float(v or 0)
        except (TypeError, ValueError):
            continue
        if amt > 0:
            pairs.append((str(t), amt))
    if not pairs:
        return None, None, 0.0
    return pairs[0][0], pairs[-1][0], round(sum(p[1] for p in pairs), 2)


async def _fetch_station_latlon(
    session: ClientSession, area_id: str
) -> tuple[float | None, float | None]:
    from urllib.parse import quote

    params = quote(
        json.dumps(
            {"method": "stationinfo", "areaid": area_id}, separators=(",", ":")
        )
    )
    url = f"https://d7.weather.com.cn/geong/v1/api?params={params}"
    try:
        text = await _get_text(session, url)
        data = json.loads(text)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("stationinfo failed for %s: %s", area_id, err)
        return None, None
    loc = data.get("location") if isinstance(data, dict) else None
    if not isinstance(loc, dict):
        return None, None
    return _to_float(loc.get("lat")), _to_float(loc.get("lng") or loc.get("lon"))


async def _fetch_minutely(
    session: ClientSession, lat: float, lon: float
) -> dict[str, Any]:
    url = f"https://mpf.weather.com.cn/mpf_v3/webgis/minute?lat={lat}&lon={lon}"
    try:
        text = await _get_text(session, url)
        data = json.loads(text)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("minutely failed: %s", err)
        return {}
    if not isinstance(data, dict) or str(data.get("status")) not in ("true", "True", "1"):
        return {}
    times = list(data.get("times") or [])
    values = list(data.get("values") or [])
    start, end, total = _rain_window(times, values)
    return {
        "msg": data.get("msg") or "",
        "ph": data.get("ph"),
        "times": times,
        "values": values,
        "rain_start": start,
        "rain_end": end,
        "precip": total,
    }


def _short_time(val: Any) -> str:
    s = str(val or "").strip()
    if not s:
        return ""
    m = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})", s)
    if m:
        return f"{m.group(1)[5:]} {m.group(2)}"
    m = re.search(r"(\d{1,2}:\d{2})", s)
    return m.group(1) if m else s


def _day_is_rain(day: dict[str, Any]) -> bool:
    fa, fb = day.get("fa"), day.get("fb")
    text = day.get("text") or ""
    label = condition_label(fa) if fa is not None else str(text)
    night = condition_label(fb) if fb is not None else ""
    return bool(
        _code_is_rain(fa)
        or _code_is_rain(fb)
        or "雨" in str(text)
        or "雨" in label
        or "雨" in night
        or "RAIN" in str(fa).upper()
        or "RAIN" in str(fb).upper()
        or "RAIN" in str(text).upper()
    )


_RAIN_MINUTE_MIN = 1.0
_RAIN_DAY_MIN = 5.0


def _rain_level(mm: float, *, daily: bool = False) -> str | None:
    if daily:
        if mm < _RAIN_DAY_MIN:
            return None
        if mm < 15.0:
            return "L"
        if mm < 25.0:
            return "M"
        return "H"
    if mm < _RAIN_MINUTE_MIN:
        return None
    if mm < 5.0:
        return "L"
    if mm < 15.0:
        return "M"
    return "H"


def _minutely_raining(minutely: dict[str, Any]) -> bool:
    return (_to_float(minutely.get("precip")) or 0.0) >= _RAIN_MINUTE_MIN


def build_rain_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    blocks: list[str] = []
    sig_parts: list[str] = []

    rain_now = _to_float(data.get("rain"))
    rain24h = _to_float(data.get("rain24h"))
    condition = str(data.get("condition") or "")
    desc = str(data.get("condition_desc") or "")
    raining_now = (
        (rain_now or 0) >= _RAIN_MINUTE_MIN
        or "rain" in condition
        or "pouring" in condition
        or "雨" in desc
    )
    now_level = _rain_level(rain_now or 0.0) if raining_now else None
    if raining_now and now_level is None and (
        "rain" in condition or "pouring" in condition or "雨" in desc
    ):
        now_level = "L"

    minutely = data.get("minutely") if isinstance(data.get("minutely"), dict) else {}
    m_precip = _to_float(minutely.get("precip")) or 0.0
    m_start = minutely.get("rain_start")
    m_end = minutely.get("rain_end")
    m_msg = str(minutely.get("msg") or "").strip()
    has_minute = _minutely_raining(minutely)
    m_level = _rain_level(m_precip) if has_minute else None

    overview: list[str] = []
    if data.get("temp") is not None:
        overview.append(f"气温 {data.get('temp')}℃")
    if data.get("humidity") is not None:
        overview.append(f"湿度 {data.get('humidity')}%")
    wind = " ".join(
        str(x) for x in (data.get("wind_dir"), data.get("wind_scale")) if x
    ).strip()
    if wind:
        overview.append(wind)

    show_now = False
    if raining_now and now_level:
        show_now = True
        sig_parts.append(f"now:{now_level}")

    if has_minute and m_level:
        sig_parts.append(f"m:{m_level}")

    forecast_lines: list[str] = []
    car_fc_rain = ""
    car_fc_amt = ""
    for i, day in enumerate(data.get("forecast") or []):
        if i > 2 or not isinstance(day, dict):
            continue
        if not _day_is_rain(day):
            continue
        fa, fb = day.get("fa"), day.get("fb")
        text = day.get("text") or ""
        day_l = condition_label(fa) if fa is not None else str(text)
        night_l = condition_label(fb) if fb is not None else ""
        weather = "转".join(x for x in (day_l or text, night_l) if x) or "有雨"
        date = day.get("fi") or ("今日" if i == 0 else "明日")
        precip = _to_float(day.get("precip"))
        if precip is None:
            precip = _to_float(day.get("precipitation"))
        amt = f"{precip:g} mm" if precip is not None else "—"
        row = f"{date}  {weather}\n雨量 {amt}"
        if day.get("fd") is not None or day.get("fc") is not None:
            row += f" · 气温 {day.get('fd')}~{day.get('fc')}℃"
        forecast_lines.append(row)
        if precip is not None:
            day_level = _rain_level(precip, daily=True)
            if day_level:
                sig_parts.append(f"f{i}:{date}:{day_level}")
        if not car_fc_rain:
            car_fc_rain = f"{date} {weather}"
            car_fc_amt = f"{date} {amt}"

    if not sig_parts:
        return None

    if show_now or overview:
        lines = ["【实况】"]
        if show_now or desc:
            lines.append(f"天气：{desc or '有雨'}")
        if rain_now is not None:
            lines.append(f"当前雨量：{rain_now:g} mm")
        if rain24h is not None:
            lines.append(f"近24小时：{rain24h:g} mm")
        if overview:
            lines.append(" · ".join(overview))
        blocks.append("\n".join(lines))

    if has_minute and m_level:
        lines = ["【短时降雨】"]
        lines.append(f"雨量：{m_precip:g} mm" if m_precip > 0 else "雨量：—")
        lines.append(m_msg or "短时有雨")
        if m_start and m_end:
            lines.append(f"时段：{_short_time(m_start)} ~ {_short_time(m_end)}")
        elif m_start:
            lines.append(f"开始：{_short_time(m_start)}")
        blocks.append("\n".join(lines))

    if forecast_lines:
        blocks.append("【预报有雨】\n" + "\n\n".join(forecast_lines))

    if has_minute and m_level:
        car_rain = m_msg or "短时有雨"
        car_amt = f"短时 {m_precip:g} mm" if m_precip > 0 else "—"
    elif show_now:
        car_rain = desc or "有雨"
        parts = []
        if rain_now is not None:
            parts.append(f"当前 {rain_now:g} mm")
        if rain24h is not None:
            parts.append(f"24h {rain24h:g} mm")
        car_amt = " · ".join(parts) if parts else "—"
    else:
        car_rain = car_fc_rain or (desc or "有雨")
        car_amt = car_fc_amt or "—"

    return {
        "sig": "|".join(sig_parts),
        "message": "\n\n".join(blocks),
        "carousel_rain": car_rain,
        "carousel_amt": car_amt,
    }

async def fetch_tianqi(
    session: ClientSession, area_id: str, forecast_days: int = 7
) -> dict[str, Any]:
    index_url = f"https://d1.weather.com.cn/weather_index/{area_id}.html"
    text = await _get_text(session, index_url)

    sk = _extract_json_assign(text, "dataSK")
    if not isinstance(sk, dict):
        m = re.search(r"dataSK\s*=\s*(\{.*?\})\s*;", text, re.S)
        if not m:
            raise ValueError(f"tianqi: no dataSK for {area_id}")
        sk = json.loads(m.group(1))

    alarms: list[dict[str, Any]] = []
    alarm_obj = _extract_json_assign(text, "alarmDZ")
    if isinstance(alarm_obj, dict):
        raw = alarm_obj.get("w") or []
        if isinstance(raw, list):
            alarms = [a for a in raw if isinstance(a, dict)]

    zs_obj = _extract_json_assign(text, "dataZS")
    indices_src = zs_obj.get("zs") if isinstance(zs_obj, dict) else zs_obj
    indices = _parse_indices(indices_src if isinstance(indices_src, dict) else None)

    forecast: list[dict[str, Any]] = []
    try:
        fc_text = await _get_text(
            session, f"https://d1.weather.com.cn/weixinfc/{area_id}.html"
        )
        fc_obj = _extract_json_assign(fc_text, "fc")
        if isinstance(fc_obj, dict):
            forecast = list(fc_obj.get("f") or [])[: max(1, forecast_days)]
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("weixinfc failed for %s: %s", area_id, err)

    if not forecast:
        try:
            w40 = await _get_text(
                session, f"https://d1.weather.com.cn/wap_40d/{area_id}.html"
            )
            # 40 天页里常有 fc40 / weather 列表
            for key in ("fc40", "fc", "weather40d"):
                obj = _extract_json_assign(w40, key)
                if isinstance(obj, dict):
                    arr = obj.get("f") or obj.get("forecast") or obj.get("list")
                    if isinstance(arr, list) and arr:
                        forecast = [x for x in arr if isinstance(x, dict)][
                            : max(1, forecast_days)
                        ]
                        break
                if isinstance(obj, list) and obj:
                    forecast = [x for x in obj if isinstance(x, dict)][
                        : max(1, forecast_days)
                    ]
                    break
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("wap_40d failed for %s: %s", area_id, err)

    weather = sk.get("weather")
    weathercode = sk.get("weathercode")
    temp_f = _to_float(sk.get("temp"))
    humidity_f = _to_float(sk.get("sd"))
    aqi_f = _to_float(sk.get("aqi"))
    feels_f = _to_float(sk.get("bodytemp"))
    if feels_f is None:
        feels_f = temp_f
    rain_f = _to_float(sk.get("rain"))
    rain24h_f = _to_float(sk.get("rain24h"))

    if not forecast:
        from datetime import datetime, timedelta

        code = str(weathercode or "").replace("d", "").replace("n", "") or "01"
        base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for i in range(max(1, min(forecast_days, 7))):
            d = base + timedelta(days=i)
            forecast.append(
                {
                    "fi": d.strftime("%m/%d"),
                    "fa": code,
                    "fb": code,
                    "fc": temp_f if temp_f is not None else 25,
                    "fd": (temp_f - 5) if temp_f is not None else 18,
                    "fn": humidity_f,
                    "text": weather,
                }
            )

    minutely: dict[str, Any] = {}
    lat, lon = await _fetch_station_latlon(session, area_id)
    if lat is not None and lon is not None:
        minutely = await _fetch_minutely(session, lat, lon)

    summary = None
    if forecast and isinstance(forecast[0], dict):
        day0 = forecast[0]
        summary = (
            f"{condition_label(day0.get('fa'))}"
            f" {day0.get('fd')}~{day0.get('fc')}℃"
        )

    hourly = _build_tianqi_hourly(
        forecast[0] if forecast and isinstance(forecast[0], dict) else None,
        temp_f,
        weathercode,
        weather,
    )

    return {
        "temp": temp_f,
        "feels": feels_f,
        "humidity": humidity_f,
        "condition": map_condition(weathercode, weather),
        "condition_desc": weather,
        "aqi": aqi_f,
        "pressure": sk.get("qy"),
        "wind_dir": sk.get("WD"),
        "wind_scale": sk.get("WS"),
        "visibility": sk.get("njd"),
        "update_time": sk.get("time"),
        "rain": rain_f,
        "rain24h": rain24h_f,
        "minutely": minutely,
        "alarms": alarms,
        "indices": indices,
        "forecast": forecast,
        "hourly": hourly,
        "forecast_summary": summary,
        "raw_sk": sk,
    }


async def search_tianqi_city(session: ClientSession, name: str) -> list[dict[str, str]]:
    from urllib.parse import quote

    url = f"https://toy1.weather.com.cn/search?cityname={quote(name)}"
    text = await _get_text(session, url)
    text = text.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return []
    out: list[dict[str, str]] = []
    for item in items or []:
        ref = (item.get("ref") or "") if isinstance(item, dict) else ""
        parts = ref.split("~")
        if len(parts) < 3:
            continue
        area_id = parts[0]
        if not area_id or len(area_id) > 9:
            continue
        label = parts[2]
        if len(parts) > 9 and parts[9]:
            label = f"{parts[9]}-{parts[2]}"
        out.append({"area_id": area_id, "name": label})
    return out
