from __future__ import annotations

import re
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify

from .apis.qweather import search_qweather
from .apis.tianqi import search_tianqi_city
from .const import (
    CONF_INTERVAL,
    CONF_LOCATION,
    CONF_NAME,
    CONF_PROVIDER,
    CONF_SLUG,
    PROVIDER_CAIYUN,
    PROVIDER_QWEATHER,
    PROVIDER_TIANQI,
)
from .defaults import default_weather_instance

_CITY_SLUG = {
    "北京": "beijing",
    "上海": "shanghai",
    "天津": "tianjin",
    "重庆": "chongqing",
    "杭州": "hangzhou",
    "宁波": "ningbo",
    "温州": "wenzhou",
    "湖州": "huzhou",
    "嘉兴": "jiaxing",
    "绍兴": "shaoxing",
    "金华": "jinhua",
    "南京": "nanjing",
    "苏州": "suzhou",
    "无锡": "wuxi",
    "常州": "changzhou",
    "扬州": "yangzhou",
    "广州": "guangzhou",
    "深圳": "shenzhen",
    "东莞": "dongguan",
    "佛山": "foshan",
    "成都": "chengdu",
    "武汉": "wuhan",
    "西安": "xian",
    "郑州": "zhengzhou",
    "长沙": "changsha",
    "合肥": "hefei",
    "福州": "fuzhou",
    "厦门": "xiamen",
    "青岛": "qingdao",
    "济南": "jinan",
    "大连": "dalian",
    "沈阳": "shenyang",
    "哈尔滨": "haerbin",
    "长春": "changchun",
    "石家庄": "shijiazhuang",
    "太原": "taiyuan",
    "南昌": "nanchang",
    "南宁": "nanning",
    "海口": "haikou",
    "贵阳": "guiyang",
    "昆明": "kunming",
    "兰州": "lanzhou",
    "西宁": "xining",
    "银川": "yinchuan",
    "乌鲁木齐": "wulumuqi",
    "拉萨": "lasa",
    "呼和浩特": "huhehaote",
    "余杭": "yuhang",
    "浦东": "pudong",
    "朝阳": "chaoyang",
    "海淀": "haidian",
}


def resolve_slug(display_name: str, explicit: str | None, area_id: str) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    name = (display_name or "").strip()
    if name in _CITY_SLUG:
        return _CITY_SLUG[name]
    for part in re.split(r"[-/·,，\s_]+", name):
        if part in _CITY_SLUG:
            return _CITY_SLUG[part]
    try:
        from pypinyin import Style, lazy_pinyin

        py = "".join(lazy_pinyin(name, style=Style.NORMAL))
        s = slugify(py) if py else ""
        if s:
            return s
    except Exception:  # noqa: BLE001
        pass
    s = slugify(name)
    if s:
        return s
    return slugify(area_id) or str(area_id).replace(",", "_").replace(".", "_")


def _qweather_geo_host(api_host: str) -> str:
    host = (api_host or "").strip()
    if not host:
        return "geoapi.qweather.com"
    if host.startswith("api.") and "qweather" in host:
        return host.replace("api.", "geoapi.", 1)
    return host


async def async_search_cities(
    hass: HomeAssistant,
    query: str,
    *,
    provider: str = PROVIDER_TIANQI,
    api_key: str = "",
    api_host: str = "",
) -> list[dict[str, str]]:
    q = (query or "").strip()
    if not q:
        return []
    session = async_get_clientsession(hass)

    if provider == PROVIDER_QWEATHER:
        if not api_key:
            return []
        host = _qweather_geo_host(api_host)
        return await search_qweather(session, q, api_key, host=host)

    if provider == PROVIDER_CAIYUN:
        if "," in q and len(q.split(",")) == 2:
            lon, lat = [x.strip() for x in q.split(",", 1)]
            return [
                {
                    "area_id": f"{lon},{lat}",
                    "name": q,
                    "location": f"{lon},{lat}",
                    "lon": lon,
                    "lat": lat,
                }
            ]
        cities = await search_tianqi_city(session, q)
        out: list[dict[str, str]] = []
        for c in cities[:8]:
            station = await _tianqi_station(session, c["area_id"])
            if not station:
                continue
            lon = station.get("lon")
            lat = station.get("lat")
            if not lon or not lat:
                continue
            out.append(
                {
                    "area_id": f"{lon},{lat}",
                    "name": c.get("name") or q,
                    "location": f"{lon},{lat}",
                    "lon": str(lon),
                    "lat": str(lat),
                }
            )
        return out

    if q.isdigit() and len(q) >= 6:
        return [{"area_id": q, "name": q, "location": q}]
    return await search_tianqi_city(session, q)


async def _tianqi_station(session, area_id: str) -> dict[str, Any] | None:
    import json
    from urllib.parse import quote

    params = quote(
        json.dumps(
            {
                "method": "stationinfo",
                "areaid": area_id,
                "category": "",
                "callback": "zs",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    url = f"https://d7.weather.com.cn/geong/v1/api?params={params}&callback=zs"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://m.weather.com.cn/",
    }
    try:
        async with session.get(url, headers=headers, timeout=15) as resp:
            text = await resp.text(encoding="utf-8", errors="ignore")
        text = text.strip()
        if text.startswith("zs(") and text.endswith(")"):
            text = text[3:-1]
        data = json.loads(text)
        station = data.get("station") or data.get("data") or data
        if isinstance(station, dict):
            return {
                "lon": station.get("lon") or station.get("lng"),
                "lat": station.get("lat"),
                "name": station.get("namecn") or station.get("name"),
            }
    except Exception:  # noqa: BLE001
        return None
    return None


def build_weather_instance(
    *,
    area_id: str,
    display_name: str,
    slug: str | None = None,
    interval: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inst = default_weather_instance()
    if extra:
        inst.update(extra)
    location = (extra or {}).get("location") or area_id
    if (extra or {}).get(CONF_PROVIDER) == PROVIDER_CAIYUN and (extra or {}).get("lon"):
        location = f"{extra['lon']},{extra['lat']}"
    inst[CONF_LOCATION] = location
    inst[CONF_NAME] = display_name
    inst[CONF_SLUG] = resolve_slug(display_name, slug, area_id)
    if interval is not None:
        inst[CONF_INTERVAL] = int(interval)
    return inst


def pick_label(item: dict[str, str]) -> str:
    return f"{item.get('name') or ''} ({item.get('area_id') or item.get('location') or ''})"
