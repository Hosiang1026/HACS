from __future__ import annotations

import logging
import ssl
from typing import Any

import aiohttp

from .const import REQUEST_TIMEOUT, VIOLATION_POINTS_MAP

_LOGGER = logging.getLogger(__name__)


def create_ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context()


async def create_session(hass) -> aiohttp.ClientSession:
    ssl_context = await hass.async_add_executor_job(create_ssl_context)
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        connector=aiohttp.TCPConnector(
            ssl=ssl_context,
            force_close=True,
            enable_cleanup_closed=True,
        ),
    )


def _headers(jsessionid: str) -> dict[str, str]:
    return {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Cookie": f"JSESSIONID-L={jsessionid}",
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }


def _rate_limited(message: str, code: str | None = None) -> bool:
    text = f"{message}{code or ''}"
    return any(token in text for token in ("频繁", "预警", "过多", "限制", "稍后", "429"))


def _fail(error: str, code: str | None = None, rate_limited: bool = False) -> dict[str, Any]:
    return {
        "success": False,
        "error": error,
        "code": code,
        "rate_limited": rate_limited or _rate_limited(error, code),
        "need_reauth": "需要重新登录" in error,
    }


async def _post(
    session: aiohttp.ClientSession,
    url: str,
    jsessionid: str,
    payload: str,
) -> dict[str, Any]:
    try:
        async with session.post(url, headers=_headers(jsessionid), data=payload) as resp:
            if resp.status == 429:
                return _fail("请求过于频繁", "429", True)
            if resp.status != 200:
                return _fail(f"HTTP {resp.status}", str(resp.status), resp.status in (403, 503))
            try:
                data = await resp.json()
            except aiohttp.ContentTypeError:
                text = await resp.text()
                if "/m/login" in text:
                    return _fail("需要重新登录")
                return _fail("JSON解析错误")
            if isinstance(data, dict) and "code" in data:
                code = str(data.get("code"))
                if code and code != "200":
                    msg = str(data.get("message") or data.get("msg") or f"code {code}")
                    return _fail(msg, code)
            return {"success": True, "data": data}
    except Exception as err:
        return _fail(str(err))


async def fetch_vehicle_info(
    session: aiohttp.ClientSession,
    jsessionid: str,
    province_code: str,
) -> dict[str, Any]:
    url = f"https://{province_code}.122.gov.cn/user/m/userinfo/allvehs"
    return await _post(session, url, jsessionid, "page=1&size=999&status=null")


async def fetch_violation_info(
    session: aiohttp.ClientSession,
    jsessionid: str,
    province_code: str,
) -> dict[str, Any]:
    url = f"https://{province_code}.122.gov.cn/user/m/userinfo/drvvio"
    return await _post(session, url, jsessionid, "drvSize=10&vioSize=5&forcSize=5")


async def fetch_surveillance_info(
    session: aiohttp.ClientSession,
    jsessionid: str,
    province_code: str,
) -> dict[str, Any]:
    url = f"https://{province_code}.122.gov.cn/user/m/userinfo/vehundosurveils"
    return await _post(session, url, jsessionid, "page=1&size=10")


def _vehicle_list(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not raw or not raw.get("success"):
        return []
    data = raw.get("data")
    content = []
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        content = data["data"].get("content", [])
    elif isinstance(data, dict) and "content" in data:
        content = data.get("content", [])
    if not isinstance(content, list):
        return []
    result = []
    for i, item in enumerate(content, 1):
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "index": i,
                "plate": item.get("hphm") or "未知",
                "type": item.get("cllxStr") or "未知",
                "status": item.get("ztStr") or "未知",
                "inspect": item.get("yxqz") or "未知",
                "dzjk": item.get("dzjk") or "未知",
            }
        )
    return result


def parse_vehicle(raw: dict[str, Any] | None, index: int) -> dict[str, Any]:
    vehicles = _vehicle_list(raw)
    for item in vehicles:
        if item["index"] == index:
            return item
    return {
        "index": index,
        "plate": None,
        "type": None,
        "status": None,
        "inspect": None,
        "dzjk": None,
    }


def parse_vehicles(raw: dict[str, Any] | None) -> list[dict[str, Any]]:
    return _vehicle_list(raw)


def _find_drvs(data: Any) -> list[Any] | None:
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("drvs"), list) and data["drvs"]:
        return data["drvs"]
    inner = data.get("data")
    if isinstance(inner, dict):
        if isinstance(inner.get("drvs"), list) and inner["drvs"]:
            return inner["drvs"]
        deeper = inner.get("data")
        if isinstance(deeper, dict) and isinstance(deeper.get("drvs"), list) and deeper["drvs"]:
            return deeper["drvs"]
    return None


def parse_license(raw: dict[str, Any] | None) -> dict[str, Any]:
    result = {
        "type": None,
        "status": None,
        "points": None,
        "ljjf": None,
        "clear": None,
        "expiry": None,
    }
    if not raw or not raw.get("success"):
        return result
    drvs = _find_drvs(raw.get("data"))
    if not drvs:
        return result
    info = drvs[0] if isinstance(drvs[0], dict) else {}
    result["type"] = info.get("zjcx")
    result["expiry"] = info.get("syyxqz")
    result["status"] = info.get("ztStr") or info.get("ztstr") or info.get("zt")
    result["clear"] = info.get("qfrq")
    try:
        ljjf = int(info.get("ljjf") or 0)
    except (TypeError, ValueError):
        ljjf = 0
    result["ljjf"] = ljjf
    result["points"] = max(0, 12 - ljjf)
    return result


def _pick(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def parse_violations(raw: dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {"count": 0, "records": []}
    if not raw or not raw.get("success"):
        return result
    data = raw.get("data")
    content = None
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        content = data["data"].get("content")
    if content is None and isinstance(data, dict):
        content = data.get("content")
    if content is None and isinstance(data, dict):
        for field in ("records", "list", "items"):
            if field in data:
                content = data[field]
                break
    if not isinstance(content, list):
        return result
    records = []
    for item in content:
        if not isinstance(item, dict):
            continue
        behavior = _pick(item, ("wfms", "wfxw", "behavior", "行为", "violation"))
        points = _pick(item, ("wfjf", "points", "记分", "score"))
        if points is None and behavior and behavior in VIOLATION_POINTS_MAP:
            points = VIOLATION_POINTS_MAP[behavior]
        records.append(
            {
                "plate": _pick(item, ("hphm", "plate", "车牌", "license_plate")),
                "time": _pick(item, ("wfsj", "time", "时间", "createTime", "date")),
                "location": _pick(item, ("wfdz", "location", "地点", "address")),
                "behavior": behavior,
                "fine": _pick(item, ("fkje", "fine", "罚款", "amount")),
                "points": points,
            }
        )
    result["count"] = len(records)
    result["records"] = records
    return result


def extract_account_name(raw: dict[str, Any] | None, fallback: str) -> str:
    if not raw:
        return fallback
    data = raw.get("data") if raw.get("success") else raw
    drvs = _find_drvs(data if isinstance(data, dict) else None)
    if not drvs or not isinstance(drvs[0], dict):
        return fallback
    info = drvs[0]
    for key in ("姓名", "name", "xm"):
        if info.get(key):
            return str(info[key])
    return fallback
