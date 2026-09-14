from __future__ import annotations

import re
from typing import Any

from aiohttp import ClientSession, ClientTimeout

_TIMEOUT = ClientTimeout(total=15)
_UA = "Mozilla/5.0 HomeAssistant ha_general_info"


def _headers() -> dict[str, str]:
    return {
        "User-Agent": _UA,
        "Referer": "https://finance.sina.com.cn",
    }


async def fetch_stock_sina(
    session: ClientSession, symbols: list[str]
) -> dict[str, dict[str, Any]]:
    codes = [s.strip().lower() for s in symbols if s and s.strip()]
    if not codes:
        return {}
    url = f"https://hq.sinajs.cn/list={','.join(codes)}"
    async with session.get(url, headers=_headers(), timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        text = await resp.text(encoding="gbk", errors="ignore")
    out: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        m = re.match(r'var hq_str_([a-z0-9]+)="(.*)";?', line.strip())
        if not m:
            continue
        code, payload = m.group(1), m.group(2)
        if not payload:
            continue
        parts = payload.split(",")
        if len(parts) < 32:
            continue
        try:
            price = float(parts[3])
            prev = float(parts[2])
            change = price - prev if prev else 0
            pct = (change / prev * 100) if prev else 0
        except (TypeError, ValueError):
            price = change = pct = None
        out[code] = {
            "name": parts[0],
            "price": price,
            "open": _f(parts[1]),
            "prev_close": _f(parts[2]),
            "high": _f(parts[4]),
            "low": _f(parts[5]),
            "volume": _f(parts[8]),
            "amount": _f(parts[9]),
            "change": round(change, 3) if change is not None else None,
            "change_pct": round(pct, 2) if pct is not None else None,
            "date": parts[30] if len(parts) > 30 else None,
            "time": parts[31] if len(parts) > 31 else None,
        }
    return out


async def fetch_stock_tencent(
    session: ClientSession, symbols: list[str]
) -> dict[str, dict[str, Any]]:
    codes = [s.strip().lower() for s in symbols if s and s.strip()]
    if not codes:
        return {}
    url = f"https://qt.gtimg.cn/q={','.join(codes)}"
    async with session.get(
        url,
        headers={"User-Agent": _UA, "Referer": "https://gu.qq.com"},
        timeout=_TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        text = await resp.text(encoding="gbk", errors="ignore")
    out: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        # v_sh600519="1~贵州茅台~600519~price~..."
        m = re.match(r'v_([a-z0-9]+)="(.*)";?', line.strip())
        if not m:
            continue
        code, payload = m.group(1), m.group(2)
        parts = payload.split("~")
        if len(parts) < 50:
            continue
        out[code] = {
            "name": parts[1],
            "price": _f(parts[3]),
            "prev_close": _f(parts[4]),
            "open": _f(parts[5]),
            "volume": _f(parts[6]),
            "high": _f(parts[33]),
            "low": _f(parts[34]),
            "change": _f(parts[31]),
            "change_pct": _f(parts[32]),
            "amount": _f(parts[37]),
            "date": parts[30] if len(parts) > 30 else None,
            "time": None,
        }
    return out


def _f(val: str) -> float | None:
    try:
        return float(val) if val not in ("", None) else None
    except (TypeError, ValueError):
        return None
