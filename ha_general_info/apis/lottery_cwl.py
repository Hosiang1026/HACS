from __future__ import annotations

from typing import Any

from aiohttp import ClientSession, ClientTimeout

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
)
_TIMEOUT = ClientTimeout(total=20)

_URL = (
    "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
    "?name={name}&pageNo=1&pageSize={size}&systemType=PC"
)


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": item.get("code"),
        "date": item.get("date"),
        "red": item.get("red"),
        "blue": item.get("blue"),
        "content": item.get("content") or item.get("number"),
        "sales": item.get("sales"),
        "poolmoney": item.get("poolmoney"),
        "raw": item,
    }


async def fetch_lottery_history(
    session: ClientSession, lottery_type: str, page_size: int = 1
) -> list[dict[str, Any]]:
    size = max(1, min(int(page_size), 100))
    url = _URL.format(name=lottery_type, size=size)
    headers = {"User-Agent": _UA, "Referer": "https://www.cwl.gov.cn/"}
    async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, list) or not result:
        raise ValueError(f"lottery empty: {lottery_type}")
    return [_normalize(item) for item in result if isinstance(item, dict)]


async def fetch_lottery(session: ClientSession, lottery_type: str) -> dict[str, Any]:
    history = await fetch_lottery_history(session, lottery_type, page_size=1)
    return history[0]
