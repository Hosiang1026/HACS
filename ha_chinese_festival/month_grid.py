from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import calendar_cn as cal
from .const import ANNIVERSARY_TYPE_LUNAR, ANNIVERSARY_TYPE_SOLAR, BIRTHDAY_TYPE_LUNAR, BIRTHDAY_TYPE_SOLAR

_DATA = Path(__file__).parent / "data"
_WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")


def _load_json(name: str) -> list:
    path = _DATA / name
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _md(d: date) -> str:
    return d.strftime("%m-%d")


def _load_maps() -> tuple[dict[str, str], dict[str, str]]:
    solar: dict[str, str] = {}
    for item in _load_json("sftv.json") + _load_json("internation.json"):
        if isinstance(item, dict) and item.get("date") and item.get("name"):
            solar.setdefault(str(item["date"]), str(item["name"]))
    lunar: dict[str, str] = {}
    for item in _load_json("lftv.json"):
        if isinstance(item, dict) and item.get("date") and item.get("name"):
            lunar.setdefault(str(item["date"]), str(item["name"]))
    return solar, lunar


def _legal_marks(legal: list | None, year: int) -> dict[str, str]:
    marks: dict[str, str] = {}
    if not isinstance(legal, list):
        return marks
    for el in legal:
        if not isinstance(el, dict):
            continue
        holiday = el.get("holiday") or 0
        repair = el.get("repair") or 0
        if isinstance(holiday, list):
            for md in holiday:
                marks[f"{year}-{md}"] = "holiday"
        if isinstance(repair, list):
            for md in repair:
                marks[f"{year}-{md}"] = "repair"
    return marks


def _event_mds(
    birthdays: list | None, anniversaries: list | None, year: int
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def add(ymd: str | None, name: str) -> None:
        if not ymd or not name:
            return
        out.setdefault(ymd, []).append(name)

    if isinstance(birthdays, list):
        for el in birthdays:
            if not isinstance(el, dict):
                continue
            bdate = str(el.get("date") or "")
            parts = bdate.split("-")
            if len(parts) < 3:
                continue
            md = f"{parts[1]}-{parts[2]}"
            try:
                btype = int(el.get("type", BIRTHDAY_TYPE_LUNAR))
            except (TypeError, ValueError):
                btype = BIRTHDAY_TYPE_LUNAR
            for y in (year - 1, year, year + 1):
                if btype == BIRTHDAY_TYPE_SOLAR:
                    add(f"{y}-{md}", str(el.get("name") or ""))
                else:
                    add(cal.conversion(f"{y}-{md}"), str(el.get("name") or ""))

    if isinstance(anniversaries, list):
        for el in anniversaries:
            if not isinstance(el, dict):
                continue
            adate = str(el.get("date") or "")
            parts = adate.split("-")
            if len(parts) < 3:
                continue
            try:
                atype = int(el.get("type", ANNIVERSARY_TYPE_SOLAR))
            except (TypeError, ValueError):
                atype = ANNIVERSARY_TYPE_SOLAR
            if atype not in (ANNIVERSARY_TYPE_SOLAR, ANNIVERSARY_TYPE_LUNAR):
                continue
            md = f"{parts[1]}-{parts[2]}"
            name = str(el.get("name") or "")
            for y in (year - 1, year, year + 1):
                if atype == ANNIVERSARY_TYPE_LUNAR:
                    add(cal.conversion(f"{y}-{md}"), name)
                else:
                    add(f"{y}-{md}", name)
    return out


def _tap_summary(tap: date) -> tuple[dict[str, Any], dict[str, Any]]:
    lunar = cal.solar2lunar(tap.year, tap.month, tap.day)
    if not isinstance(lunar, dict):
        lunar = {}
    solar = {
        "year": tap.year,
        "month": tap.month,
        "day": tap.day,
        "date": tap.strftime("%Y-%m-%d"),
        "weekday": f"星期{_WEEKDAYS[tap.weekday()]}",
        "astro": lunar.get("astro") or "",
    }
    lunar_sum = {
        "year": lunar.get("gzYear") or "",
        "animal": lunar.get("Animal") or "",
        "month": lunar.get("IMonthCn") or "",
        "day": lunar.get("IDayCn") or "",
        "text": f"{lunar.get('IMonthCn', '')}{lunar.get('IDayCn', '')}",
        "full": (
            f"{lunar.get('gzYear', '')}{lunar.get('Animal', '')}年"
            f"{lunar.get('IMonthCn', '')}{lunar.get('IDayCn', '')}"
            if lunar
            else ""
        ),
        "term": lunar.get("Term") or "",
    }
    return solar, lunar_sum


def build_month_grid(
    year: int,
    month: int,
    birthdays,
    anniversaries,
    legal,
    tap_date: date,
) -> dict[str, Any]:
    first = date(year, month, 1)
    start = first - timedelta(days=first.weekday())
    solar_map, lunar_map = _load_maps()
    legal_map = _legal_marks(legal, year)
    legal_map.update(_legal_marks(legal, year - 1))
    legal_map.update(_legal_marks(legal, year + 1))
    event_map = _event_mds(birthdays, anniversaries, year)

    dates: list[str] = []
    in_month: list[bool] = []
    lunar_text: list[str] = []
    jieqi_text: list[str | None] = []
    solar_festival: list[str | None] = []
    lunar_festival: list[str | None] = []
    holiday_mark: list[str | None] = []
    birthday_mark: list[list[str]] = []

    for i in range(42):
        d = start + timedelta(days=i)
        ymd = d.strftime("%Y-%m-%d")
        info = cal.solar2lunar(d.year, d.month, d.day)
        if not isinstance(info, dict):
            info = {}
        lmd = f"{info.get('lMonth', 0):02d}-{info.get('lDay', 0):02d}" if info else ""
        dates.append(ymd)
        in_month.append(d.month == month)
        lunar_text.append(
            f"{info.get('IMonthCn', '')}{info.get('IDayCn', '')}" if info else ""
        )
        jieqi_text.append(info.get("Term") or None)
        solar_festival.append(solar_map.get(_md(d)))
        lunar_festival.append(lunar_map.get(lmd) if lmd else None)
        holiday_mark.append(legal_map.get(ymd))
        birthday_mark.append(event_map.get(ymd, []))

    tap_solar, tap_lunar = _tap_summary(tap_date)
    return {
        "year": year,
        "month": month,
        "days_in_month": calendar.monthrange(year, month)[1],
        "dates": dates,
        "in_month": in_month,
        "lunar_text": lunar_text,
        "jieqi_text": jieqi_text,
        "solar_festival": solar_festival,
        "lunar_festival": lunar_festival,
        "holiday_mark": holiday_mark,
        "birthday_mark": birthday_mark,
        "tap_solar": tap_solar,
        "tap_lunar": tap_lunar,
    }
