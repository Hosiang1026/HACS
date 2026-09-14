from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

from bs4 import BeautifulSoup

from .const import FUEL_0, FUEL_92, FUEL_95, FUEL_98, FUEL_LABELS

_LOGGER = logging.getLogger(__name__)

_FUEL_KEY_BY_LABEL = {label: key for key, label in FUEL_LABELS.items()}


def norm_oil_price(value: Any) -> float | None:
    raw = re.sub(r"\s*\(元\)\s*", "", str(value if value is not None else "")).strip()
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _normalize_fuel_type(text: str) -> str:
    cleaned = re.sub(r"^[\u4e00-\u9fa5]+", "", text or "")
    cleaned = cleaned.replace("#", "号").strip()
    return cleaned


def parse_province_prices(html: str) -> dict[str, float]:
    soup = BeautifulSoup(html or "", "html.parser")
    rows = soup.select(".content_youjia dl")
    if not rows:
        rows = soup.select("#youjia dl")
    result: dict[str, float] = {}
    for row in rows:
        dt = row.find("dt")
        dd = row.find("dd")
        if not dt or not dd:
            continue
        label = _normalize_fuel_type(dt.get_text(strip=True))
        key = _FUEL_KEY_BY_LABEL.get(label)
        if not key:
            if "92" in label and "汽" in label:
                key = FUEL_92
            elif "95" in label and "汽" in label:
                key = FUEL_95
            elif "98" in label and "汽" in label:
                key = FUEL_98
            elif "0" in label and "柴" in label:
                key = FUEL_0
        if not key:
            continue
        price = norm_oil_price(dd.get_text())
        if price is not None:
            result[key] = price
    return result


def parse_tishi_content_from_html(html: str) -> str:
    raw = str(html or "")
    match = re.search(r'tishiContent\s*=\s*"((?:\\.|[^"\\])*)"', raw)
    if not match:
        return ""
    text = match.group(1).replace("\\'", "'")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = re.sub(r"当前微信公众号油价已更新。?", "", text)
    text = re.sub(r"，\s*$", "", text, flags=re.M).strip()
    return text


def parse_update_text(html: str) -> str:
    from_script = parse_tishi_content_from_html(html)
    if from_script:
        return from_script

    soup = BeautifulSoup(html or "", "html.parser")
    right_top = soup.select_one("#rightTop")
    price_update = ""
    if right_top:
        lines = [ln.strip() for ln in right_top.get_text("\n").splitlines() if ln.strip()]
        for keyword in ("相互转告", "调整"):
            matched = [ln for ln in lines if keyword in ln]
            if matched:
                price_update = " ".join(matched)
                break

    tishi = soup.select_one(".tishi")
    tishi_text = ""
    if tishi:
        for tag in tishi.find_all(["script", "style"]):
            tag.decompose()
        tishi_text = tishi.get_text(" ", strip=True)
        tishi_text = tishi_text.replace("\xa0", " ")
        tishi_text = re.sub(r"\s+", " ", tishi_text)
        tishi_text = re.sub(r"当前微信公众号油价已更新。?", "", tishi_text).strip()

    parts = [p for p in (price_update, tishi_text) if p]
    return "\n".join(parts)


def parse_adjust_schedule(text: str, *, today: date | None = None) -> date | bool:
    raw = str(text or "")
    if not raw:
        return True
    today = today or date.today()

    def _resolve(month: int, day: int, *, next_day: bool) -> date | bool:
        try:
            announced = date(today.year, month, day)
        except ValueError:
            return False
        target = announced + timedelta(days=1) if next_day else announced
        if target < today:
            try:
                announced = date(today.year + 1, month, day)
            except ValueError:
                return False
            target = announced + timedelta(days=1) if next_day else announced
        if target < today or (target - today).days > 60:
            return False
        return target

    m = re.search(r"(\d{1,2})月(\d{1,2})日\s*24\s*时", raw)
    if m:
        return _resolve(int(m.group(1)), int(m.group(2)), next_day=True)

    m = re.search(r"(\d{1,2})月(\d{1,2})日\s*(?:零|0)\s*时", raw)
    if m:
        return _resolve(int(m.group(1)), int(m.group(2)), next_day=False)

    m = re.search(
        r"(?:下次调价|调价窗口|预计.*?调价)[^\d]{0,12}(\d{1,2})月(\d{1,2})日",
        raw,
    )
    if m:
        return _resolve(int(m.group(1)), int(m.group(2)), next_day=True)

    return True
