from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
from typing import Any

from aiohttp import ClientSession, ClientTimeout

_TIMEOUT = ClientTimeout(total=20)
_UA = "Mozilla/5.0 HomeAssistant ha_general_info"


def _parse_douban_pubdate(raw: Any) -> str | None:
    values: list[str] = []
    if isinstance(raw, str) and raw.strip():
        values = [raw.strip()]
    elif isinstance(raw, list):
        values = [str(x).strip() for x in raw if str(x).strip()]
    for text in values:
        m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", text)
        if m:
            y, mo, d = m.group(1).split("-")
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"^(\d{4})$", text)
        if m:
            return m.group(1)
    return None


def _ms_to_date(ms: Any) -> str | None:
    try:
        value = int(ms)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _fallback_year(subtitle: str | None) -> str | None:
    year = str(subtitle or "").split("/", 1)[0].strip()
    return year if re.fullmatch(r"\d{4}", year) else None


async def _fetch_douban_detail(
    session: ClientSession, kind: str, subject_id: str
) -> str | None:
    url = f"https://m.douban.com/rexxar/api/v2/{kind}/{subject_id}"
    headers = {
        "User-Agent": _UA,
        "Referer": "https://m.douban.com/movie/",
    }
    try:
        async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    return (
        _parse_douban_pubdate(data.get("pubdate"))
        or _parse_douban_pubdate(data.get("release_date"))
        or (str(data.get("year")) if data.get("year") else None)
    )


async def _noop_date() -> None:
    return None


async def _fetch_douban_hot(
    session: ClientSession, kind: str, limit: int = 10
) -> dict[str, Any]:
    url = f"https://m.douban.com/rexxar/api/v2/subject/recent_hot/{kind}"
    headers = {
        "User-Agent": _UA,
        "Referer": "https://m.douban.com/movie/",
    }
    async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)

    rows = (data.get("items") or [])[:limit]
    tasks = []
    for row in rows:
        subject_id = str(row.get("id") or "").strip()
        if subject_id:
            tasks.append(_fetch_douban_detail(session, kind, subject_id))
        else:
            tasks.append(_noop_date())
    details = await asyncio.gather(*tasks)

    items = []
    for row, release_date in zip(rows, details):
        subject_id = str(row.get("id") or "").strip() or None
        if not release_date:
            release_date = _fallback_year(row.get("card_subtitle"))
        items.append(
            {
                "title": row.get("title"),
                "rating": (row.get("rating") or {}).get("value"),
                "card_subtitle": row.get("card_subtitle"),
                "url": row.get("url") or row.get("uri"),
                "id": subject_id,
                "release_date": release_date,
            }
        )
    if not items:
        raise ValueError(f"{kind} hot empty")
    return {"top": items[0].get("title"), "items": items}


async def fetch_movie_hot(session: ClientSession, limit: int = 10) -> dict[str, Any]:
    return await _fetch_douban_hot(session, "movie", limit)


async def fetch_tv_hot(session: ClientSession, limit: int = 10) -> dict[str, Any]:
    return await _fetch_douban_hot(session, "tv", limit)


async def fetch_music_hot(session: ClientSession, limit: int = 10) -> dict[str, Any]:
    url = "https://music.163.com/api/playlist/detail?id=19723756"
    headers = {
        "User-Agent": _UA,
        "Referer": "https://music.163.com/",
    }
    async with session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    tracks = ((data.get("result") or {}).get("tracks") or [])[:limit]
    items = []
    for t in tracks:
        artists = ",".join(
            a.get("name") for a in (t.get("artists") or []) if a.get("name")
        )
        album = t.get("album") or {}
        release_date = _ms_to_date(t.get("publishTime")) or _ms_to_date(
            album.get("publishTime")
        )
        items.append(
            {
                "title": t.get("name"),
                "artists": artists,
                "album": album.get("name"),
                "id": t.get("id"),
                "release_date": release_date,
            }
        )
    if not items:
        raise ValueError("music hot empty")
    top = items[0]
    label = (
        f"{top.get('title')} - {top.get('artists')}"
        if top.get("artists")
        else top.get("title")
    )
    return {"top": label, "items": items}
