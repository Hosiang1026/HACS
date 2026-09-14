from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import calendar_cn as cal
from .almanac_engine import compute_almanac
from .const import (
    ANNIVERSARY_TYPE_LUNAR,
    ANNIVERSARY_TYPE_SOLAR,
    ANNIVERSARY_TYPE_SUM,
    BIRTHDAY_TYPE_LUNAR,
    BIRTHDAY_TYPE_SOLAR,
    CONF_ANNIVERSARIES,
    CONF_BIRTHDAYS,
    CONF_LEGAL,
    CONF_LICENSES,
    CONF_NEAR_ANNIVERSARY_DAYS,
    CONF_NEAR_BIRTHDAY_DAYS,
    CONF_NEAR_FESTIVAL_DAYS,
    CONF_NEAR_LICENSE_DAYS,
    DEFAULT_NEAR_ANNIVERSARY_DAYS,
    DEFAULT_NEAR_BIRTHDAY_DAYS,
    DEFAULT_NEAR_FESTIVAL_DAYS,
    DEFAULT_NEAR_LICENSE_DAYS,
    STATE_HOLIDAY,
    STATE_REPAIR,
    STATE_REST,
    STATE_WEEKEND,
    STATE_WORKDAY,
)
from .month_grid import build_month_grid

_DATA = Path(__file__).parent / "data"


def load_json(name: str) -> list:
    path = _DATA / name
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def default_licenses() -> list[dict[str, Any]]:
    return _default_items("default_licenses.json")


def default_anniversaries() -> list[dict[str, Any]]:
    return _default_items("default_anniversaries.json")


def default_birthdays() -> list[dict[str, Any]]:
    return _default_items("default_birthdays.json")


def _default_items(name: str) -> list[dict[str, Any]]:
    items = load_json(name)
    out = []
    for item in items:
        row = dict(item)
        row.setdefault("id", str(uuid.uuid4()))
        out.append(row)
    return out


def _parse_date(s: str) -> date:
    return datetime.strptime(str(s).replace("/", "-")[:10], "%Y-%m-%d").date()


def _try_parse_date(s: str) -> date | None:
    try:
        return _parse_date(s)
    except (TypeError, ValueError):
        return None


def _fmt(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _fmt_md(d: date) -> str:
    return d.strftime("%m-%d")


def _format_almanac_lines(almanac: dict[str, Any]) -> list[str]:
    if not isinstance(almanac, dict) or not almanac:
        return []
    pairs = (
        ("eight_char", "八字"),
        ("hour", "时辰"),
        ("clash", "冲煞"),
        ("suit", "宜"),
        ("avoid", "忌"),
        ("moon_phase", "月相"),
        ("solar_term", "节气"),
        ("grade", "吉凶"),
        ("season", "季节"),
        ("taboo", "彭祖百忌"),
        ("good_spirit", "吉神"),
        ("bad_spirit", "凶煞"),
        ("fetus", "胎神"),
        ("tone", "纳音"),
        ("triad", "三合"),
        ("hexad", "六合"),
        ("zodiac_sign", "黄历星座"),
    )
    lines = ["📜黄历"]
    for key, label in pairs:
        val = str(almanac.get(key) or "").strip()
        if not val or val == "暂无":
            continue
        lines.append(f"· {label}: {val}")
    return lines if len(lines) > 1 else []


def _date_header(now_s: str, lunar: dict[str, Any], year_diff: int) -> str:
    if lunar:
        return (
            f"{now_s} {lunar.get('ncWeek', '')} {lunar.get('astro', '')}\n"
            f"{lunar.get('gzYear', '')}{lunar.get('Animal', '')}年"
            f"{lunar.get('IMonthCn', '')}{lunar.get('IDayCn', '')} 第{year_diff}天"
        )
    return now_s


def _today_notify_line(item: dict[str, Any]) -> str:
    name = item.get("todayName") or ""
    tdate = item.get("todayDate") or ""
    tcontent = item.get("todayContent") or ""
    if name and tdate and tcontent:
        return f"今天是{name}🎉 \n{tcontent} {tdate} \n"
    if name and tdate:
        return f"今天是{name}🎉 \n{tcontent} \n"
    if name:
        return f"今天是{name}🎉 \n"
    return ""


def get_easter_date(year: int) -> str:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return f"{year}-{month:02d}-{day:02d}"


def compute(
    options: dict[str, Any],
    today: date | None = None,
    *,
    holiday_provider: Any = None,
    tap_date: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    tap = tap_date or today
    year = today.year
    md = today.strftime("%m-%d")
    now_s = _fmt(today)
    lunar = cal.solar2lunar(year, today.month, today.day)
    if not isinstance(lunar, dict):
        lunar = {}

    try:
        near_fest = int(options.get(CONF_NEAR_FESTIVAL_DAYS, DEFAULT_NEAR_FESTIVAL_DAYS))
    except (TypeError, ValueError):
        near_fest = DEFAULT_NEAR_FESTIVAL_DAYS
    try:
        near_lic = int(options.get(CONF_NEAR_LICENSE_DAYS, DEFAULT_NEAR_LICENSE_DAYS))
    except (TypeError, ValueError):
        near_lic = DEFAULT_NEAR_LICENSE_DAYS
    try:
        near_bday = int(options.get(CONF_NEAR_BIRTHDAY_DAYS, DEFAULT_NEAR_BIRTHDAY_DAYS))
    except (TypeError, ValueError):
        near_bday = DEFAULT_NEAR_BIRTHDAY_DAYS
    try:
        near_anni = int(
            options.get(CONF_NEAR_ANNIVERSARY_DAYS, DEFAULT_NEAR_ANNIVERSARY_DAYS)
        )
    except (TypeError, ValueError):
        near_anni = DEFAULT_NEAR_ANNIVERSARY_DAYS

    content: list[str] = []
    today_arr: list[dict] = []
    lately_arr: list[dict] = []
    int_all: list[dict] = []
    tips: list[str] = []
    seasonal_tips: list[str] = []
    today_license: list[str] = []
    end_license: list[str] = []
    love_content: str | None = None

    year_diff = cal.diff_time_to_daily(now_s, _pick_new_year_solar(now_s, year)) + 1

    anniversaries = options.get(CONF_ANNIVERSARIES) or []
    birthdays = options.get(CONF_BIRTHDAYS) or []
    licenses = options.get(CONF_LICENSES) or []
    legal = options.get(CONF_LEGAL) or []
    if not isinstance(anniversaries, list):
        anniversaries = []
    if not isinstance(birthdays, list):
        birthdays = []
    if not isinstance(licenses, list):
        licenses = []
    if not isinstance(legal, list):
        legal = []
    anniversaries = [x for x in anniversaries if isinstance(x, dict)]
    birthdays = [x for x in birthdays if isinstance(x, dict)]
    licenses = [x for x in licenses if isinstance(x, dict)]
    legal = [x for x in legal if isinstance(x, dict)]
    sftv = load_json("sftv.json")
    lftv = load_json("lftv.json")
    term = load_json("term.json")
    special = load_json("special.json")
    internation = load_json("internation.json")

    marriage = load_json("marriage.json")
    love_content, love_items = _anniversaries(
        anniversaries,
        now_s,
        year,
        today_arr,
        lately_arr,
        marriage,
    )
    _birthdays(birthdays, now_s, lunar, year, today_arr, lately_arr)
    day_info = _legal(
        legal,
        now_s,
        md,
        year,
        today_arr,
        lately_arr,
        tips,
    )
    if holiday_provider is not None:
        day_info = _merge_day_info(day_info, holiday_provider, today, legal, md)
    if day_info.get("day_type") == STATE_WORKDAY and today.weekday() >= 5:
        day_info["day_type"] = STATE_WEEKEND
    _lftv(lftv, now_s, year, today_arr, lately_arr)
    _term(term, now_s, year, today_arr, lately_arr)
    _internation(internation, now_s, year, today_arr, lately_arr)
    _sftv(sftv, now_s, year, today_arr, int_all)
    _special(special, now_s, year, today_arr, int_all)
    _easter(now_s, year, today_arr, int_all)

    if int_all:
        min_obj = min(int_all, key=lambda x: x["tempTime"])
        lately_arr.append(min_obj)

    seasonal_arr: list[dict] = []
    _meiyu(now_s, year, seasonal_tips, seasonal_arr)
    _sanfu(now_s, year, seasonal_tips, seasonal_arr)
    _sijiu(now_s, year, seasonal_tips, seasonal_arr)
    _licenses(licenses, now_s, near_lic, today_license, end_license)

    content.append("📆重要节日 \n")
    if today_arr:
        today_lines = []
        for item in today_arr:
            if item.get("category") in ("birthday", "anniversary", "term"):
                continue
            line = _today_notify_line(item)
            if line:
                today_lines.append(line)
        today_lines.sort(key=len)
        content.extend(today_lines)

    fest_lately = [
        x
        for x in lately_arr
        if x.get("category") not in ("birthday", "anniversary", "term")
    ]
    content_extra: list[str] = []
    min_temp = min((x["tempTime"] for x in fest_lately), default=None)
    min_temp_arr: list[str] = []
    if min_temp is not None:
        for item in fest_lately:
            if item["tempTime"] == min_temp:
                min_temp_arr.append(f"* {item['tempName']}: {item['tempTime']}天")
            else:
                content_extra.append(f"· {item['tempName']}: {item['tempTime']}天")
        if min_temp_arr:
            content.append("📌距离下一个节日")
            min_temp_arr.sort(key=len)
            min_temp_arr[-1] = min_temp_arr[-1] + "\n"
            content.extend(min_temp_arr)

    content.extend(tips)
    if content_extra:
        content_extra.sort(key=cal.get_text_length)
        content.extend(content_extra)

    license_lines: list[str] = []
    if today_license or end_license:
        license_lines.append("💳证件有效期 \n")
        if today_license:
            today_license.sort(key=cal.get_text_length)
            license_lines.extend(today_license)
        if end_license:
            end_license.sort(key=cal.get_text_length)
            license_lines.extend(end_license)
    license_content = "\n".join(license_lines).strip()
    festival_content = "\n".join(content).strip()

    next_name = ""
    next_days = min_temp if min_temp is not None else None
    if min_temp is not None:
        for item in fest_lately:
            if item["tempTime"] == min_temp:
                next_name = item["tempName"]
                break

    next_by_category: dict[str, dict] = {}
    for item in lately_arr + int_all + seasonal_arr:
        cat = item.get("category")
        if not cat:
            continue
        cur = next_by_category.get(cat)
        if cur is None or item["tempTime"] < cur["days"]:
            next_by_category[cat] = {
                "name": item["tempName"],
                "days": item["tempTime"],
            }
    if seasonal_arr:
        best_s = min(seasonal_arr, key=lambda x: x["tempTime"])
        next_by_category["seasonal"] = {
            "name": best_s["tempName"],
            "days": best_s["tempTime"],
        }

    nearest_license_days = None
    license_items = []
    for lic in licenses:
        ld = lic.get("date")
        parsed = _try_parse_date(ld) if ld else None
        if not parsed:
            continue
        if today > parsed:
            continue
        days = cal.diff_time_to_daily(now_s, ld)
        license_items.append({"name": lic.get("name"), "date": ld, "days": days})
        if nearest_license_days is None or days < nearest_license_days:
            nearest_license_days = days

    fest_only = [
        x
        for x in lately_arr
        if x.get("category") not in ("birthday", "anniversary", "term")
    ]
    fest_min = min((x["tempTime"] for x in fest_only), default=None)
    fest_today = [
        x
        for x in today_arr
        if x.get("category") not in ("birthday", "anniversary", "term")
    ]
    has_near_festival = (
        bool(fest_today)
        or (fest_min is not None and fest_min <= near_fest)
        or bool(tips)
    )
    has_near_license = bool(today_license)
    bday_next = next_by_category.get("birthday") or {}
    bday_days = bday_next.get("days")
    today_bday = [x for x in today_arr if x.get("category") == "birthday"]
    today_anni = [x for x in today_arr if x.get("category") == "anniversary"]
    has_near_birthday = bool(today_bday) or (
        bday_days is not None and bday_days <= near_bday
    )
    birthday_content = ""
    if today_bday:
        birthday_content = _today_notify_line(today_bday[0]).strip()
    elif bday_next.get("name") is not None and bday_days is not None:
        birthday_content = f"· {bday_next['name']}: {bday_days}天"

    anni_next = next_by_category.get("anniversary") or {}
    anni_days = anni_next.get("days")
    has_near_anniversary = bool(today_anni) or (
        anni_days is not None and anni_days <= near_anni
    )
    anniversary_content = ""
    if today_anni:
        anniversary_content = _today_notify_line(today_anni[0]).strip()
    elif anni_next.get("name") is not None and anni_days is not None:
        anniversary_content = f"· {anni_next['name']}: {anni_days}天"

    memorial_parts: list[str] = []
    today_mem_lines = []
    for item in today_bday + today_anni:
        line = _today_notify_line(item)
        if line:
            today_mem_lines.append(line)
    today_mem_lines.sort(key=len)
    memorial_parts.extend(today_mem_lines)
    mem_lately = [
        x
        for x in lately_arr
        if x.get("category") in ("birthday", "anniversary")
    ]
    mem_min = min((x["tempTime"] for x in mem_lately), default=None)
    mem_extra: list[str] = []
    if mem_min is not None:
        mem_min_arr: list[str] = []
        for item in mem_lately:
            if item["tempTime"] == mem_min:
                mem_min_arr.append(f"* {item['tempName']}: {item['tempTime']}天")
            else:
                mem_extra.append(f"· {item['tempName']}: {item['tempTime']}天")
        if mem_min_arr:
            memorial_parts.append("📌距离下一个节日")
            mem_min_arr.sort(key=len)
            mem_min_arr[-1] = mem_min_arr[-1] + "\n"
            memorial_parts.extend(mem_min_arr)
    if mem_extra:
        mem_extra.sort(key=cal.get_text_length)
        memorial_parts.extend(mem_extra)
    if love_content:
        memorial_parts.append(love_content)
    memorial_content = "\n".join(memorial_parts).strip()
    has_near_memorial = bool(
        has_near_birthday or has_near_anniversary or love_content
    )

    holiday_plan: dict[str, Any] = {}
    if holiday_provider is not None:
        try:
            holiday_plan = holiday_provider.nearest_holiday_plan(today) or {}
        except Exception:
            holiday_plan = {}

    almanac = compute_almanac(tap)
    month_grid = build_month_grid(
        tap.year, tap.month, birthdays, anniversaries, legal, tap
    )

    calendar_blocks: list[str] = [_date_header(now_s, lunar, year_diff)]

    day_block: list[str] = []
    if day_info.get("day_type") == STATE_HOLIDAY:
        day_label = f"⛱今天放假: {day_info.get('day_name') or '节假日'}"
        if day_info.get("holiday_day"):
            day_label += f"（第{day_info['holiday_day']}天）"
        day_block.append(day_label)
    elif day_info.get("day_type") == STATE_WEEKEND:
        day_block.append("今天周末")
    elif day_info.get("day_type") == STATE_REST:
        day_block.append("今天休息")
    elif day_info.get("day_type") == STATE_REPAIR:
        repair_name = day_info.get("day_name") or ""
        day_block.append(
            f"📟今天{repair_name}补班，努力工作！" if repair_name else "📟今天补班，努力工作！"
        )
    else:
        day_block.append("今天工作日")
    if day_info.get("freeway"):
        day_block.append("· 高速通行: 免费")
    calendar_blocks.append("\n".join(day_block))

    term_lines: list[str] = ["🌤二十四节气"]
    today_term = lunar.get("Term") if lunar else None
    if not today_term:
        for item in today_arr:
            if item.get("category") == "term" and item.get("todayName"):
                today_term = item.get("todayName")
                break
    if today_term:
        term_lines.append(f"· 今天节气: {today_term}")
    term_next = next_by_category.get("term") or {}
    if term_next.get("name") is not None and term_next.get("days") is not None:
        term_lines.append(f"· {term_next['name']}: {term_next['days']}天")
    if len(term_lines) > 1:
        calendar_blocks.append("\n".join(term_lines))

    if seasonal_tips:
        tip_lines = ["🌿时令提示"]
        tip_lines.extend(str(x).rstrip() for x in seasonal_tips if str(x).strip())
        calendar_blocks.append("\n".join(tip_lines))

    almanac_lines = _format_almanac_lines(almanac)
    if almanac_lines:
        calendar_blocks.append("\n".join(almanac_lines))

    calendar_content = "\n\n".join(calendar_blocks).strip()

    lunar_text = ""
    if lunar:
        lunar_text = (
            f"{lunar.get('gzYear', '')}{lunar.get('Animal', '')}年"
            f"{lunar.get('IMonthCn', '')}{lunar.get('IDayCn', '')}"
        )

    return {
        "festival_content": festival_content,
        "calendar_content": calendar_content,
        "license_content": license_content,
        "birthday_content": birthday_content,
        "anniversary_content": anniversary_content,
        "memorial_content": memorial_content,
        "love_content": love_content,
        "love_items": love_items,
        "love_days": max((x["days"] for x in love_items), default=None),
        "love_name": (
            max(love_items, key=lambda x: x["days"]).get("name") if love_items else None
        ),
        "today": today_arr,
        "next": [{"name": x["tempName"], "days": x["tempTime"]} for x in lately_arr],
        "tips": tips,
        "next_name": next_name,
        "next_days": next_days,
        "next_by_category": next_by_category,
        "day_type": day_info["day_type"],
        "day_name": day_info["day_name"],
        "freeway": day_info["freeway"],
        "holiday_day": day_info["holiday_day"],
        "is_holiday": bool(day_info.get("is_holiday")),
        "is_repair": day_info["day_type"] == STATE_REPAIR,
        "license_items": license_items,
        "license_near": [
            x for x in license_items if x["days"] < near_lic
        ],
        "nearest_license_days": nearest_license_days,
        "has_near_festival": has_near_festival,
        "has_near_license": has_near_license,
        "has_near_birthday": has_near_birthday,
        "has_near_anniversary": has_near_anniversary,
        "has_near_memorial": has_near_memorial,
        "holiday_plan": holiday_plan,
        "almanac": almanac,
        "month_grid": month_grid,
        "tap_date": _fmt(tap),
        "lunar": lunar,
        "solar_date": now_s,
        "weekday": lunar.get("ncWeek"),
        "astro": lunar.get("astro"),
        "lunar_date": lunar_text,
        "year_day": year_diff,
        "animal": lunar.get("Animal"),
        "gz_year": lunar.get("gzYear"),
        "gz_month": lunar.get("gzMonth"),
        "gz_day": lunar.get("gzDay"),
        "term": lunar.get("Term"),
        "count_festival": (
            len(sftv) + len(lftv) + len(term) + len(special) + len(internation) + len(legal) + 1
        ),
        "count_festival_detail": {
            "sftv": len(sftv),
            "lftv": len(lftv),
            "term": len(term),
            "special": len(special),
            "internation": len(internation),
            "legal": len(legal),
            "easter": 1,
        },
        "count_license": len(licenses),
        "count_birthday": len(birthdays),
        "count_anniversary": len(anniversaries),
    }


def _merge_day_info(
    day_info: dict[str, Any],
    provider: Any,
    today: date,
    legal: list,
    md: str,
) -> dict[str, Any]:
    info = dict(day_info)
    try:
        dtype = int(provider.get_day_type(today))
    except Exception:
        info["is_holiday"] = False
        return info
    if dtype == 2:
        info["day_type"] = STATE_HOLIDAY
    elif dtype == 1:
        info["day_type"] = (
            STATE_WEEKEND if today.weekday() >= 5 else STATE_REST
        )
    elif today.weekday() >= 5:
        info["day_type"] = STATE_REPAIR
    else:
        info["day_type"] = STATE_WORKDAY
    info["is_holiday"] = dtype == 2
    for el in legal:
        if not isinstance(el, dict):
            continue
        repair = el.get("repair") or 0
        if isinstance(repair, list) and md in repair:
            info["day_type"] = STATE_REPAIR
            info["is_holiday"] = False
            info["day_name"] = el.get("name") or info.get("day_name") or ""
        holiday = el.get("holiday") or 0
        if isinstance(holiday, list) and md in holiday:
            info["day_name"] = el.get("name") or info.get("day_name") or ""
            try:
                info["freeway"] = int(el.get("freeway") or info.get("freeway") or 0)
            except (TypeError, ValueError):
                pass
    return info


def _pick_new_year_solar(now_s: str, year: int) -> str:
    festival = "01-01"
    candidates = [
        cal.conversion(f"{year - 2}-{festival}"),
        cal.conversion(f"{year - 1}-{festival}"),
        cal.conversion(f"{year}-{festival}"),
        cal.conversion(f"{year + 1}-{festival}"),
        cal.conversion(f"{year + 2}-{festival}"),
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return f"{year}-01-01"
    res = candidates[0]
    now_d = _parse_date(now_s)
    for cand in candidates[1:]:
        parsed = _try_parse_date(cand)
        if parsed and now_d >= parsed:
            res = cand
    return res


def _anniversaries(arr, now_s, year, today_arr, lately_arr, marriage):
    loves: list[str] = []
    love_items: list[dict[str, Any]] = []
    if not arr:
        return None, love_items
    temp_name = None
    temp_time = None
    for el in arr:
        try:
            name = el.get("name") or ""
            adate = el.get("date") or ""
            atype = int(el.get("type", ANNIVERSARY_TYPE_SOLAR))
            parts = adate.split("-")
            if len(parts) < 3:
                continue
            ay, am, ad = parts[0], parts[1], parts[2]
            md = f"{am}-{ad}"
            if atype == ANNIVERSARY_TYPE_SUM:
                days = cal.sum_time_to_now(adate, now_s)
                label = str(name).strip() or "恋爱"
                loves.append(f"💘我们在一起恋爱: {days}天")
                love_items.append({"name": label, "date": adate, "days": days})
                continue
            next_d = f"{year + 1}-{md}"
            if atype == ANNIVERSARY_TYPE_LUNAR:
                next_d = cal.conversion(next_d)
                if not next_d:
                    continue
            res = next_d
            cur = f"{year}-{md}"
            if atype == ANNIVERSARY_TYPE_LUNAR:
                cur = cal.conversion(cur)
                if not cur:
                    continue
            cur_d = _try_parse_date(cur)
            if cur_d and _parse_date(now_s) <= cur_d:
                res = cur
            pre = f"{year - 1}-{md}"
            if atype == ANNIVERSARY_TYPE_LUNAR:
                pre = cal.conversion(pre)
                if not pre:
                    continue
            pre_d = _try_parse_date(pre)
            if pre_d and _parse_date(now_s) <= pre_d:
                res = pre
            if not _try_parse_date(res):
                continue
            diff = cal.diff_time_to_daily(now_s, res)
            if diff == 0:
                ann_year = int(ay)
                if atype == ANNIVERSARY_TYPE_LUNAR:
                    solar = cal.conversion(adate)
                    if not solar:
                        continue
                    ann_year = int(solar.split("-")[0])
                diff_year = year - ann_year
                today_date = "<" + adate.replace("-", ".") + ">"
                today_content = f" {diff_year}周年快乐"
                if name == "结婚纪念日":
                    for m in marriage:
                        if int(m.get("age", -1)) == diff_year:
                            today_content = f"{m['name']}-{diff_year}周年快乐"
                today_arr.append(
                    {
                        "todayName": name,
                        "todayDate": today_date,
                        "todayContent": today_content,
                        "category": "anniversary",
                    }
                )
            elif diff > 0 and (temp_time is None or diff < temp_time):
                temp_name, temp_time = name, diff
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if temp_name is not None and temp_time is not None:
        lately_arr.append(
            {"tempName": temp_name, "tempTime": temp_time, "category": "anniversary"}
        )
    return ("\n".join(loves) if loves else None), love_items


def _birthdays(arr, now_s, lunar, year, today_arr, lately_arr):
    if not arr:
        return
    temp_name = None
    temp_time = None
    now_d = _parse_date(now_s)
    for el in arr:
        try:
            name = el.get("name") or ""
            bdate = el.get("date") or ""
            parts = bdate.split("-")
            if len(parts) < 3:
                continue
            by, bm, bd = parts[0], parts[1], parts[2]
            md = f"{bm}-{bd}"
            try:
                btype = int(el.get("type", BIRTHDAY_TYPE_LUNAR))
            except (TypeError, ValueError):
                btype = BIRTHDAY_TYPE_LUNAR
            if btype == BIRTHDAY_TYPE_SOLAR:
                res = f"{year + 1}-{md}"
                cur = f"{year}-{md}"
                pre = f"{year - 1}-{md}"
                if now_d <= (_try_parse_date(cur) or now_d):
                    if _try_parse_date(cur):
                        res = cur
                if _try_parse_date(pre) and now_d <= _try_parse_date(pre):
                    res = pre
            else:
                res = cal.conversion(f"{year + 1}-{md}")
                cur = cal.conversion(f"{year}-{md}")
                if not res or not cur:
                    continue
                cur_d = _try_parse_date(cur)
                if cur_d and now_d <= cur_d:
                    res = cur
                pre = cal.conversion(f"{year - 1}-{md}")
                if pre:
                    pre_d = _try_parse_date(pre)
                    if pre_d and now_d <= pre_d:
                        res = pre
            if not _try_parse_date(res):
                continue
            diff = cal.diff_time_to_daily(now_s, res)
            if diff == 0:
                age = year - int(by)
                today_arr.append(
                    {
                        "todayName": name,
                        "todayDate": "<" + bdate.replace("-", ".") + ">",
                        "todayContent": f"{age}岁{lunar.get('astro', '')}",
                        "category": "birthday",
                    }
                )
            elif diff > 0 and (temp_time is None or diff < temp_time):
                temp_name, temp_time = name, diff
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if temp_name is not None and temp_time is not None:
        lately_arr.append(
            {"tempName": temp_name, "tempTime": temp_time, "category": "birthday"}
        )


def _legal(arr, now_s, md, year, today_arr, lately_arr, tips):
    info = {
        "day_type": STATE_WORKDAY,
        "day_name": "",
        "freeway": 0,
        "holiday_day": 0,
        "is_holiday": False,
    }
    if not arr:
        return info
    temp_name = None
    temp_time = None
    now_d = _parse_date(now_s)
    for el in arr:
        try:
            name = el.get("name") or ""
            ldate = el.get("date") or ""
            freeway = int(el.get("freeway") or 0)
            holiday = el.get("holiday") or 0
            repair = el.get("repair") or 0
            exist_holiday = False
            if holiday != 0 and isinstance(holiday, list):
                exist_holiday = md in holiday
                if exist_holiday and holiday:
                    first = f"{year}-{holiday[0]}"
                    if not _try_parse_date(first):
                        continue
                    holiday_diff = cal.sum_time_to_now(first, now_s)
                    tips.append("⛱祝大家假期愉快！")
                    tips.append(f"* {name}放假: 第{holiday_diff + 1}天 ")
                    tips.append(
                        "* 全国高速通行: 免费 \n"
                        if freeway == 1
                        else "* 全国高速通行: 收费 \n"
                    )
                    info.update(
                        {
                            "day_type": STATE_HOLIDAY,
                            "day_name": name,
                            "freeway": freeway,
                            "holiday_day": holiday_diff + 1,
                            "is_holiday": True,
                        }
                    )
            if repair != 0 and isinstance(repair, list) and md in repair:
                tips.append(f"📟今天{name}补班，努力工作！\n ")
                info.update(
                    {
                        "day_type": STATE_REPAIR,
                        "day_name": name,
                        "freeway": freeway,
                        "is_holiday": False,
                    }
                )
            parts = ldate.split("-")
            if len(parts) < 2:
                continue
            month, day = int(parts[0]), int(parts[1])
            cur_year_date = date(year, month, day)
            if cur_year_date >= now_d:
                next_legal = f"{year}-{parts[0]}-{parts[1]}"
            else:
                next_legal = f"{year + 1}-{parts[0]}-{parts[1]}"
            if not _try_parse_date(next_legal):
                continue
            diff = max(0, cal.diff_time_to_daily(now_s, next_legal))
            if diff == 0:
                today_arr.append(
                    {"todayName": name, "todayDate": "", "todayContent": ""}
                )
            elif diff > 0 and (temp_time is None or diff < temp_time):
                temp_name, temp_time = name, diff
            if holiday != 0 and isinstance(holiday, list) and holiday:
                start_h = holiday[0]
                end_h = holiday[-1]
                num = len(holiday)
                if not _try_parse_date(f"{year}-{start_h}"):
                    continue
                if diff + num < 15:
                    if num == 1:
                        tips.append(f"⏳距离{name}放假还有{diff}天 ")
                        tips.append(
                            "* 高速通行: 免费" if freeway == 1 else "* 高速通行: 收费"
                        )
                        if repair != 0 and isinstance(repair, list):
                            tips.append(f"* 补班{len(repair)}天: {'、'.join(repair)}")
                        if num > 2:
                            tips.append(f"* 假期{num}天: {start_h} ~ {end_h}\n")
                        else:
                            tips.append(f"* 假期{num}天: {'、'.join(holiday)}\n")
                    elif not exist_holiday:
                        start_year = f"{year}-{start_h}"
                        start_parsed = _try_parse_date(start_year)
                        if start_parsed and start_parsed < now_d:
                            start_year = f"{year + 1}-{start_h}"
                        if not _try_parse_date(start_year):
                            continue
                        start_diff = max(0, cal.diff_time_to_daily(now_s, start_year))
                        if start_diff > 0:
                            tips.append(f"⏳距离{name}放假还有{start_diff}天")
                            tips.append(
                                "* 高速通行: 免费" if freeway == 1 else "* 高速通行: 收费"
                            )
                            if repair != 0 and isinstance(repair, list):
                                tips.append(
                                    f"* 补班{len(repair)}天: {'、'.join(repair)}"
                                )
                            if num > 2:
                                tips.append(f"* 假期{num}天: {start_h} ~ {end_h}\n")
                            else:
                                tips.append(f"* 假期{num}天: {'、'.join(holiday)}\n")
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if temp_name is not None and temp_time is not None:
        lately_arr.append(
            {"tempName": temp_name, "tempTime": temp_time, "category": "legal"}
        )
    return info


def _lftv(arr, now_s, year, today_arr, lately_arr):
    if not arr:
        return
    temp_name = None
    temp_time = None
    for el in arr:
        try:
            name = el.get("name") or ""
            ldate = el.get("date") or ""
            res = cal.conversion(f"{year + 1}-{ldate}")
            cur = cal.conversion(f"{year}-{ldate}")
            if not res or not cur:
                continue
            cur_d = _try_parse_date(cur)
            if cur_d and _parse_date(now_s) <= cur_d:
                res = cur
            pre = cal.conversion(f"{year - 1}-{ldate}")
            if pre:
                pre_d = _try_parse_date(pre)
                if pre_d and _parse_date(now_s) <= pre_d:
                    res = pre
            if not _try_parse_date(res):
                continue
            diff = cal.diff_time_to_daily(now_s, res)
            if diff == 0:
                today_arr.append(
                    {"todayName": name, "todayDate": "", "todayContent": ""}
                )
            elif diff > 0 and (temp_time is None or diff < temp_time):
                temp_name, temp_time = name, diff
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if temp_name is not None and temp_time is not None:
        lately_arr.append(
            {"tempName": temp_name, "tempTime": temp_time, "category": "lftv"}
        )


def _term(arr, now_s, year, today_arr, lately_arr):
    if not arr:
        return
    temp_name = None
    temp_time = None
    temp_sort = 0
    for el in arr:
        try:
            sort = int(el.get("sort") or 0)
            name = el.get("name") or ""
            month = el.get("month") or "01"
            term_num = sort + 2 if sort <= 22 else sort - 22
            res = cal.conversion_term(year + 1, month, term_num)
            cur = cal.conversion_term(year, month, term_num)
            if not res or not cur:
                continue
            cur_d = _try_parse_date(cur)
            if cur_d and _parse_date(now_s) <= cur_d:
                res = cur
            pre = cal.conversion_term(year - 1, month, term_num)
            if pre:
                pre_d = _try_parse_date(pre)
                if pre_d and _parse_date(now_s) <= pre_d:
                    res = pre
            if not _try_parse_date(res):
                continue
            diff = cal.diff_time_to_daily(now_s, res)
            if diff == 0:
                today_arr.append(
                    {
                        "todayName": name,
                        "todayDate": "",
                        "todayContent": "",
                        "category": "term",
                    }
                )
            elif diff > 0 and (temp_time is None or diff < temp_time):
                temp_sort, temp_name, temp_time = sort, name, diff
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if temp_name is not None and temp_time is not None:
        lately_arr.append(
            {
                "tempName": f"第{temp_sort}个节气{temp_name}",
                "tempTime": temp_time,
                "category": "term",
            }
        )


def _internation(arr, now_s, year, today_arr, lately_arr):
    if not arr:
        return
    temp_name = None
    temp_time = None
    now_d = _parse_date(now_s)
    for el in arr:
        try:
            name = el.get("name") or ""
            idate = el.get("date") or ""
            parts = idate.split("-")
            if len(parts) < 2:
                continue
            nxt = f"{year}-{parts[0]}-{parts[1]}"
            nxt_d = _try_parse_date(nxt)
            if not nxt_d:
                continue
            if now_d > nxt_d:
                nxt = f"{year + 1}-{parts[0]}-{parts[1]}"
                if not _try_parse_date(nxt):
                    continue
            diff = cal.diff_time_to_daily(now_s, nxt)
            if diff == 0:
                today_arr.append(
                    {"todayName": name, "todayDate": "", "todayContent": ""}
                )
            elif diff > 0 and (temp_time is None or diff < temp_time):
                temp_name, temp_time = name, diff
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if temp_name is not None and temp_time is not None:
        lately_arr.append(
            {"tempName": temp_name, "tempTime": temp_time, "category": "internation"}
        )


def _sftv(arr, now_s, year, today_arr, int_all):
    if not arr:
        return
    temp_name = None
    temp_time = None
    now_d = _parse_date(now_s)
    for el in arr:
        try:
            name = el.get("name") or ""
            sdate = el.get("date") or ""
            parts = sdate.split("-")
            if len(parts) < 2:
                continue
            nxt = f"{year}-{parts[0]}-{parts[1]}"
            nxt_d = _try_parse_date(nxt)
            if not nxt_d:
                continue
            if now_d > nxt_d:
                nxt = f"{year + 1}-{parts[0]}-{parts[1]}"
                if not _try_parse_date(nxt):
                    continue
            diff = cal.diff_time_to_daily(now_s, nxt)
            if diff == 0:
                today_arr.append(
                    {"todayName": name, "todayDate": "", "todayContent": ""}
                )
            elif diff > 0 and (temp_time is None or diff < temp_time):
                temp_name, temp_time = name, diff
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if temp_name is not None and temp_time is not None:
        int_all.append(
            {"tempName": temp_name, "tempTime": temp_time, "category": "sftv"}
        )


def _special(arr, now_s, year, today_arr, int_all):
    if not arr:
        return
    temp_name = None
    temp_time = None
    now_d = _parse_date(now_s)
    for el in arr:
        try:
            name = el.get("name") or ""
            sdate = el.get("date") or ""
            parts = sdate.split("/")
            if len(parts) < 3:
                continue
            month, week, nums = parts[0], parts[1], parts[2]
            nxt = cal.conversion_parent_date(year, month, week, nums)
            if not nxt:
                continue
            nxt_d = _try_parse_date(nxt)
            if not nxt_d:
                continue
            if now_d > nxt_d:
                nxt = cal.conversion_parent_date(year + 1, month, week, nums)
            if not nxt or not _try_parse_date(nxt):
                continue
            diff = cal.diff_time_to_daily(now_s, nxt)
            if diff == 0:
                today_arr.append(
                    {"todayName": name, "todayDate": "", "todayContent": ""}
                )
            elif diff > 0 and (temp_time is None or diff < temp_time):
                temp_name, temp_time = name, diff
        except (TypeError, ValueError, KeyError, IndexError):
            continue
    if temp_name is not None and temp_time is not None:
        int_all.append(
            {"tempName": temp_name, "tempTime": temp_time, "category": "special"}
        )


def _easter(now_s, year, today_arr, int_all):
    res = get_easter_date(year + 1)
    cur = get_easter_date(year)
    if _parse_date(now_s) <= _parse_date(cur):
        res = cur
    pre = get_easter_date(year - 1)
    if _parse_date(now_s) <= _parse_date(pre):
        res = pre
    diff = cal.diff_time_to_daily(now_s, res)
    if diff == 0:
        today_arr.append({"todayName": "复活节", "todayDate": "", "todayContent": ""})
    elif diff > 0:
        int_all.append(
            {"tempName": "复活节", "tempTime": diff, "category": "special"}
        )


def _push_seasonal(candidates: list[dict], name: str, days: int) -> None:
    candidates.append({"tempName": name, "tempTime": days, "category": "seasonal"})


def _sanfu(now_s, year, tips, seasonal_arr):
    now_d = _parse_date(now_s)
    all_dates = (cal.calculate_san_fu_dates(year) or []) + (
        cal.calculate_san_fu_dates(year + 1) or []
    )
    tip = ""
    best = None
    for item in all_dates:
        start_s = _fmt(item["startDate"])
        if item["startDate"] <= now_d <= item["endDate"]:
            days = cal.sum_time_to_now(start_s, now_s)
            tip = f"🔅夏季三伏天-【{item['name']}】第{days + 1}天，请大家注意避暑。\n"
            best = (f"三伏-{item['name']}", 0)
            break
        diff = cal.diff_time_to_daily(now_s, start_s)
        if diff <= 0:
            continue
        if best is None or diff < best[1]:
            best = (f"三伏-{item['name']}", diff)
        if not tip and diff < 8:
            tip = (
                f"⏳距离夏季三伏天-【{item['name']}】还有{diff}天"
                f"（持续{item['days']}天：{_fmt_md(item['startDate'])} ~ {_fmt_md(item['endDate'])}）\n"
            )
    if tip:
        tips.append(tip)
    if best:
        _push_seasonal(seasonal_arr, best[0], best[1])


def _sijiu(now_s, year, tips, seasonal_arr):
    dz_this = cal.conversion_term(year, "12", 24)
    dz_last = cal.conversion_term(year - 1, "12", 24)
    dz_next = cal.conversion_term(year + 1, "12", 24)
    if not dz_this or not dz_last:
        return
    all_dates = (cal.calculate_san_jiu_season(year - 1, _parse_date(dz_last)) or []) + (
        cal.calculate_san_jiu_season(year, _parse_date(dz_this)) or []
    )
    if dz_next:
        all_dates += cal.calculate_san_jiu_season(year + 1, _parse_date(dz_next)) or []
    tip = ""
    now_d = _parse_date(now_s)
    best = None
    for item in all_dates:
        start_s = _fmt(item["startDate"])
        end_s = _fmt(item["endDate"])
        if item["startDate"] <= now_d <= item["endDate"]:
            days = cal.sum_time_to_now(start_s, now_s)
            tip = (
                f"❄冬季四九天-【{item['name']}】第{days + 1}天，"
                f"一九二九不出手，三九四九冰上走，请大家注意保暖。\n"
            )
            best = (f"四九-{item['name']}", 0)
            break
        diff = cal.diff_time_to_daily(now_s, start_s)
        if diff <= 0:
            continue
        if best is None or diff < best[1]:
            best = (f"四九-{item['name']}", diff)
        if not tip and diff < 8:
            tip = (
                f"⏳距离冬季四九天-【{item['name']}】还有{diff}天"
                f"（持续9天：{start_s} ~ {end_s}）\n"
            )
    if tip:
        tips.append(tip)
    if best:
        _push_seasonal(seasonal_arr, best[0], best[1])


def _meiyu(now_s, year, tips, seasonal_arr):
    now_d = _parse_date(now_s)
    best = None
    tip = ""
    for y in (year, year + 1):
        mang = cal.conversion_term(y, "06", 11)
        xiao = cal.conversion_term(y, "07", 13)
        if not mang or not xiao:
            continue
        mang_d = _try_parse_date(mang)
        xiao_d = _try_parse_date(xiao)
        if not mang_d or not xiao_d:
            continue
        season = cal.calculate_mei_yu_season(y, mang_d, xiao_d)
        if not season:
            continue
        start_s = _fmt(season["startDate"])
        end_s = _fmt(season["endDate"])
        if season["startDate"] <= now_d <= season["endDate"]:
            days = cal.sum_time_to_now(start_s, now_s)
            left = cal.sum_time_to_now(end_s, now_s)
            tip = (
                f"🌧梅雨季第{days + 1}天，阴雨持续连绵，高温高湿，"
                f"距离出梅还有{left + 1}天。\n"
            )
            best = ("梅雨", 0)
            break
        diff = cal.diff_time_to_daily(now_s, start_s)
        if diff <= 0:
            continue
        if best is None or diff < best[1]:
            best = ("梅雨", diff)
        if not tip and diff < 8:
            tip = (
                f"⏳距离梅雨季还有{diff}天（持续{season['duration']}天："
                f"{_fmt_md(season['startDate'])} ~ {_fmt_md(season['endDate'])}）\n"
            )
    if tip:
        tips.append(tip)
    if best:
        _push_seasonal(seasonal_arr, best[0], best[1])


def _licenses(arr, now_s, near_days, today_license, end_license):
    now_d = _parse_date(now_s)
    for el in arr:
        name = el.get("name") or ""
        ldate = el.get("date") or ""
        parsed = _try_parse_date(ldate) if ldate else None
        if not parsed:
            continue
        if now_d > parsed:
            continue
        diff = cal.diff_time_to_daily(now_s, ldate)
        if diff < near_days:
            if diff == 0:
                today_license.append(f"· {name}🚨 \n 今天到期，请尽快处理\n")
            else:
                today_license.append(
                    f"· {name}🚨 \n <{ldate.replace('-', '.')}> \n {diff}天后到期，请及时处理\n"
                )
        else:
            end_license.append(f"· {name}: {diff}天")
