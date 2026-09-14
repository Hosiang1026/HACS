from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from . import calendar_cn as cal
from .const import (
    BIRTHDAY_TYPE_LUNAR,
    BIRTHDAY_TYPE_SOLAR,
    CONF_ANNIVERSARIES,
    CONF_BIRTHDAYS,
    CONF_ITEM_DATE,
    CONF_ITEM_NAME,
    CONF_ITEM_TYPE,
    CONF_LEGAL,
)
from .festival_engine import load_json


def _parse_md(raw: str) -> tuple[int, int] | None:
    text = str(raw or "").strip().replace("-", "")
    if len(text) != 4 or not text.isdigit():
        return None
    month, day = int(text[:2]), int(text[2:])
    if month < 1 or month > 12 or day < 1 or day > 31:
        return None
    return month, day


def _solar_date(year: int, md: str) -> date | None:
    parsed = _parse_md(md)
    if not parsed:
        return None
    month, day = parsed
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _lunar_date(year: int, md: str) -> date | None:
    parsed = _parse_md(md)
    if not parsed:
        return None
    month, day = parsed
    solar = cal.lunar2solar(year, month, day)
    if not isinstance(solar, dict):
        return None
    try:
        return date(solar["cYear"], solar["cMonth"], solar["cDay"])
    except (KeyError, TypeError, ValueError):
        return None


def resolve_rule_date(
    item: dict[str, Any],
    today: date,
    festival_lookup: dict[str, date] | Callable[[str], date | None],
) -> tuple[date | None, list[str]]:
    name = str(item.get("name") or "").strip()
    raw_date = str(item.get("date") or "").strip()
    solar = item.get("solar", True)
    if isinstance(solar, str):
        solar = solar.lower() not in ("false", "0", "no")

    if name:
        if callable(festival_lookup):
            target = festival_lookup(name)
        else:
            target = festival_lookup.get(name)
        if not target:
            return None, []
        return target, [name]

    if raw_date:
        target = (
            _solar_date(today.year, raw_date)
            if solar
            else _lunar_date(today.year, raw_date)
        )
        if not target:
            return None, []
        return target, [raw_date]
    return None, []


def match_notify_rules(
    rules: dict[str, Any] | None,
    today: date,
    options: dict[str, Any] | None,
    festival_lookup: dict[str, date] | Callable[[str], date | None],
) -> list[dict[str, Any]]:
    if not rules or not isinstance(rules, dict):
        return []
    _ = options
    grouped: dict[int, list[str]] = {}
    for key, items in rules.items():
        day_keys = {str(x).strip() for x in str(key).split("|") if str(x).strip()}
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            target, names = resolve_rule_date(item, today, festival_lookup)
            if not target or not names:
                continue
            diff = (target - today).days
            if str(diff) not in day_keys:
                continue
            grouped.setdefault(diff, [])
            for n in names:
                if n not in grouped[diff]:
                    grouped[diff].append(n)
    return [{"days": days, "names": names} for days, names in sorted(grouped.items())]


def build_festival_lookup(
    data: dict[str, Any],
    today: date,
    options: dict[str, Any] | None = None,
) -> dict[str, date]:
    lookup: dict[str, date] = {}
    year = today.year
    options = options or {}

    for item in data.get("today") or []:
        if isinstance(item, dict) and item.get("todayName"):
            lookup[str(item["todayName"])] = today

    for item in data.get("next") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        days = item.get("days")
        if name is None or days is None:
            continue
        try:
            lookup[str(name)] = today + timedelta(days=int(days))
        except (TypeError, ValueError):
            continue

    for cat_item in (data.get("next_by_category") or {}).values():
        if not isinstance(cat_item, dict):
            continue
        name = cat_item.get("name")
        days = cat_item.get("days")
        if name is None or days is None:
            continue
        try:
            lookup[str(name)] = today + timedelta(days=int(days))
        except (TypeError, ValueError):
            continue

    for row in load_json("sftv.json") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        md = str(row.get("date") or "").replace("-", "")
        target = _solar_date(year, md)
        if name and target and name not in lookup:
            lookup[str(name)] = target

    for row in load_json("lftv.json") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        md = str(row.get("date") or "").replace("-", "")
        target = _lunar_date(year, md)
        if name and target and name not in lookup:
            lookup[str(name)] = target

    for item in options.get(CONF_LEGAL) or []:
        if not isinstance(item, dict):
            continue
        name = item.get(CONF_ITEM_NAME)
        md = str(item.get(CONF_ITEM_DATE) or "").replace("-", "")
        target = _solar_date(year, md)
        if name and target:
            lookup[str(name)] = target

    for item in options.get(CONF_BIRTHDAYS) or []:
        if not isinstance(item, dict):
            continue
        name = item.get(CONF_ITEM_NAME)
        raw = str(item.get(CONF_ITEM_DATE) or "")
        parts = raw.split("-")
        if not name or len(parts) < 3:
            continue
        md = f"{parts[1]}{parts[2]}"
        try:
            btype = int(item.get(CONF_ITEM_TYPE, BIRTHDAY_TYPE_LUNAR))
        except (TypeError, ValueError):
            btype = BIRTHDAY_TYPE_LUNAR
        target = (
            _solar_date(year, md)
            if btype == BIRTHDAY_TYPE_SOLAR
            else _lunar_date(year, md)
        )
        if target and target < today:
            target = (
                _solar_date(year + 1, md)
                if btype == BIRTHDAY_TYPE_SOLAR
                else _lunar_date(year + 1, md)
            )
        if target:
            lookup[str(name)] = target

    for item in options.get(CONF_ANNIVERSARIES) or []:
        if not isinstance(item, dict):
            continue
        name = item.get(CONF_ITEM_NAME)
        raw = str(item.get(CONF_ITEM_DATE) or "")
        parts = raw.split("-")
        if not name or len(parts) < 3:
            continue
        md = f"{parts[1]}{parts[2]}"
        target = _solar_date(year, md)
        if target and target < today:
            target = _solar_date(year + 1, md)
        if target:
            lookup[str(name)] = target

    return lookup


def format_notify_messages(matches: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in matches:
        days = item.get("days")
        names = item.get("names") or []
        label = ",".join(str(n) for n in names if n)
        if not label:
            continue
        if days == 0:
            lines.append(f"今天是{label}🎉")
        else:
            lines.append(f"· {label}: {days}天")
    return "\n".join(lines)
