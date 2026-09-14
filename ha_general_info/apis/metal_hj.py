from __future__ import annotations

import re
from typing import Any

from aiohttp import ClientSession, ClientTimeout

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36"
)
_TIMEOUT = ClientTimeout(total=30)
_URL = "http://www.huangjinjiage.cn"
_BANK_URL = "http://www.huangjinjiage.cn/golden/155283.html"
_OZ_TO_G = 31.1034768

_SHOP_SKIP = ("国际", "国内", "回收", "投资金条", "铂金", "钯金", "18K", "18k", "香港")
_BANK_NAMES = (
    "工商银行",
    "中国银行",
    "建设银行",
    "农业银行",
    "招商银行",
    "交通银行",
    "民生银行",
    "平安银行",
    "邮政银行",
    "邮储银行",
    "中信银行",
    "兴业银行",
)


def _parse_num(text: str) -> float | None:
    m = re.search(r"([\d.]+)", text.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _decode_html(raw: bytes) -> str:
    for enc in ("gb18030", "gbk", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _row_cells(html: str, row_id: str) -> list[str]:
    m = re.search(
        rf'<tr[^>]*id=["\']?{re.escape(row_id)}["\']?[^>]*>(.*?)</tr>',
        html,
        re.I | re.S,
    )
    if not m:
        return []
    tds = re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.I | re.S)
    return [re.sub(r"<[^>]+>", "", t).strip() for t in tds]


def _td_text(html: str, row_id: str) -> str:
    cells = _row_cells(html, row_id)
    if len(cells) < 2:
        return ""
    return cells[1]


def _row_quote(html: str, row_id: str) -> dict[str, Any]:
    cells = _row_cells(html, row_id)
    if len(cells) < 2:
        return {}
    return {
        "name": cells[0],
        "price": _parse_num(cells[1]),
        "price_text": cells[1],
        "change": _parse_num(cells[2]) if len(cells) > 2 else None,
        "change_pct": cells[3] if len(cells) > 3 else None,
        "high": _parse_num(cells[4]) if len(cells) > 4 else None,
        "low": _parse_num(cells[5]) if len(cells) > 5 else None,
        "date": cells[6] if len(cells) > 6 else None,
    }


def _avg(nums: list[float]) -> float | None:
    return round(sum(nums) / len(nums), 2) if nums else None


def _shop_rows(html: str) -> dict[str, float]:
    start = html.find("投资金条")
    end = html.find("香港周大福")
    chunk = html[start:end] if start >= 0 and end > start else html
    out: dict[str, float] = {}
    for m in re.finditer(
        r'class=["\']tabtitle["\'][^>]*>(.*?)</[^>]+>.*?<td[^>]*>(.*?)</td>',
        chunk,
        re.I | re.S,
    ):
        brand = re.sub(r"<[^>]+>", "", m.group(1)).replace("内地", "").strip()
        price_text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not brand or any(x in brand for x in _SHOP_SKIP):
            continue
        price = _parse_num(price_text)
        if price is None or price < 800 or price > 3000:
            continue
        out[brand] = price
    return out


def _parse_bank_rows(html: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
        cells = [
            re.sub(r"<[^>]+>", "", c).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row.group(1), re.I | re.S)
        ]
        cells = [c for c in cells if c]
        if len(cells) < 3:
            continue
        name = cells[0]
        if not any(b in name for b in _BANK_NAMES):
            continue
        price = _parse_num(cells[2])
        if price is None or price < 500 or price > 2000:
            continue
        out[name] = price
    return out


async def fetch_banks(session: ClientSession) -> dict[str, float]:
    headers = {"User-Agent": _UA}
    async with session.get(_BANK_URL, headers=headers, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        html = _decode_html(await resp.read())
    return _parse_bank_rows(html)


async def fetch_metal(session: ClientSession, url: str | None = None) -> dict[str, Any]:
    target = url or _URL
    headers = {"User-Agent": _UA}
    async with session.get(target, headers=headers, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        html = _decode_html(await resp.read())

    gold = _td_text(html, "jiage4") or _td_text(html, "jiage1")
    silver = _td_text(html, "jiage5") or _td_text(html, "jiage3")
    shops = _shop_rows(html)
    shop_avg = _avg(list(shops.values()))

    banks: dict[str, float] = {}
    try:
        banks = await fetch_banks(session)
    except Exception:  # noqa: BLE001
        banks = {}
    bank_avg = _avg(list(banks.values()))

    intl_gold = _row_quote(html, "jiage1")
    intl_silver = _row_quote(html, "jiage3")
    gold_num = _parse_num(gold)
    intl_gold_usd = intl_gold.get("price")
    intl_silver_usd = intl_silver.get("price")
    usd_cny = None
    intl_gold_cny = None
    intl_silver_cny = None
    if (
        isinstance(gold_num, (int, float))
        and isinstance(intl_gold_usd, (int, float))
        and intl_gold_usd > 0
    ):
        usd_cny = round(float(gold_num) * _OZ_TO_G / float(intl_gold_usd), 4)
        intl_gold_cny = round(float(gold_num), 2)
        if isinstance(intl_silver_usd, (int, float)):
            intl_silver_cny = round(
                float(intl_silver_usd) * usd_cny / _OZ_TO_G, 2
            )

    return {
        "gold": gold_num,
        "gold_text": gold,
        "silver": _parse_num(silver),
        "silver_text": silver,
        "shop": shop_avg,
        "shops": shops,
        "bank": bank_avg,
        "banks": banks,
        "intl_gold": intl_gold_usd,
        "intl_gold_text": intl_gold.get("price_text"),
        "intl_gold_cny": intl_gold_cny,
        "intl_gold_change": intl_gold.get("change"),
        "intl_gold_change_pct": intl_gold.get("change_pct"),
        "intl_gold_high": intl_gold.get("high"),
        "intl_gold_low": intl_gold.get("low"),
        "intl_gold_date": intl_gold.get("date"),
        "intl_silver": intl_silver_usd,
        "intl_silver_text": intl_silver.get("price_text"),
        "intl_silver_cny": intl_silver_cny,
        "intl_silver_change": intl_silver.get("change"),
        "intl_silver_change_pct": intl_silver.get("change_pct"),
        "intl_silver_high": intl_silver.get("high"),
        "intl_silver_low": intl_silver.get("low"),
        "intl_silver_date": intl_silver.get("date"),
        "usd_cny": usd_cny,
    }
