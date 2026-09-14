from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from aiohttp import ClientSession, ClientTimeout

_TIMEOUT = ClientTimeout(total=20)
_UA = "Mozilla/5.0 HomeAssistant ha_general_info"


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _parse_rss(xml_text: str, limit: int) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    items: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        pub = _text(item.find("pubDate"))
        if not title:
            continue
        items.append({"title": title, "url": link, "time": pub})
        if len(items) >= limit:
            break
    if items:
        return items
    for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        title = _text(entry.find("{http://www.w3.org/2005/Atom}title"))
        link_el = entry.find("{http://www.w3.org/2005/Atom}link")
        link = ""
        if link_el is not None:
            link = link_el.attrib.get("href") or _text(link_el)
        updated = _text(entry.find("{http://www.w3.org/2005/Atom}updated"))
        if title:
            items.append({"title": title, "url": link, "time": updated})
        if len(items) >= limit:
            break
    return items


async def fetch_rss(
    session: ClientSession, feeds: list[str], limit: int = 10
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    headers = {"User-Agent": _UA}
    for feed in feeds:
        if not feed or len(items) >= limit:
            continue
        try:
            async with session.get(feed, headers=headers, timeout=_TIMEOUT) as resp:
                resp.raise_for_status()
                text = await resp.text(errors="ignore")
            need = limit - len(items)
            items.extend(_parse_rss(text, need))
        except Exception:  # noqa: BLE001
            continue
    items = items[:limit]
    if not items:
        raise ValueError("rss empty")
    headline = items[0]["title"] if items else None
    return {"headline": headline, "items": items}
