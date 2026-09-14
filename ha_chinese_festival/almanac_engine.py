from __future__ import annotations

import math
import re
from datetime import date, datetime, time
from typing import Any

_FILTERS = {
    "上表章",
    "上册",
    "颁诏",
    "修置产室",
    "举正直",
    "选将",
    "宣政事",
    "冠带",
    "上官",
    "临政",
    "竖柱上梁",
    "修仓库",
    "营建",
    "穿井",
    "伐木",
    "畋猎",
    "招贤",
    "酝酿",
    "乘船渡水",
    "解除",
    "缮城郭",
    "筑堤防",
    "修宫室",
    "安碓硙",
    "纳采",
    "针刺",
    "平治道涂",
    "裁制",
    "修饰垣墙",
    "塞穴",
    "庆赐",
    "破屋坏垣",
    "鼓铸",
    "启攒",
    "开仓",
    "纳畜",
    "牧养",
    "经络",
    "安抚边境",
    "布政事",
    "覃恩",
    "雪冤",
    "出师",
}
_TEXT_PATTERN = re.compile(r"\[.*?\]|[,;，；]")
_BLACKLIST = re.compile(r"黄道|黑道|日|-|、|(?<!^)开")
_ZODIAC = {
    "鼠",
    "牛",
    "虎",
    "兔",
    "龙",
    "蛇",
    "马",
    "羊",
    "猴",
    "鸡",
    "狗",
    "猪",
    "建",
    "除",
    "满",
    "平",
    "定",
    "执",
    "破",
    "危",
    "成",
    "收",
    "开",
    "闭",
}
_SHICHEN = (
    "子时",
    "丑时",
    "寅时",
    "卯时",
    "辰时",
    "巳时",
    "午时",
    "未时",
    "申时",
    "酉时",
    "戌时",
    "亥时",
)
_MARKS = ("初", "一", "二", "三", "四", "五", "六", "七")
_PHASE_THRESHOLDS = (
    (0.5, "朔月"),
    (6.5, "峨眉月"),
    (7.5, "上弦月"),
    (13.5, "渐盈凸月"),
    (14.5, "满月"),
    (20.5, "渐亏凸月"),
    (21.5, "下弦月"),
    (27.5, "残月"),
    (float("inf"), "朔月"),
)
_PHASE_DESC = {
    "朔月": "月亮完全不可见，为农历每月初一。",
    "峨眉月": "月亮呈细弧形，东方傍晚可见。",
    "上弦月": "月亮外侧发亮，呈现半圆形。",
    "渐盈凸月": "月亮大部分可见，接近圆形。",
    "满月": "月亮完整可见，呈现圆形。",
    "渐亏凸月": "月亮开始减亏，仍近似圆形。",
    "下弦月": "月亮内侧发亮，呈现半圆形。",
    "残月": "月亮呈细弧形，清晨西方可见。",
}


def _clean_text(text: Any) -> str:
    if text is None:
        return ""
    raw = text if isinstance(text, str) else " ".join(str(x) for x in text)
    filtered = _BLACKLIST.sub("", raw)
    words = [
        w
        for w in _TEXT_PATTERN.sub(" ", filtered).split()
        if (len(w) > 1 or w in _ZODIAC) and w not in _FILTERS
    ]
    return " ".join(words[:10]).strip()


def _calc_level_name(good_count: int, bad_count: int) -> str:
    r = good_count / max(bad_count, 1)
    if r >= 3.0:
        return "上上"
    if r >= 2.0:
        return "上"
    if r >= 1.5:
        return "上次"
    if r >= 1.0:
        return "中上"
    if r >= 0.8:
        return "中"
    if r >= 0.5:
        return "中次"
    if r >= 0.3:
        return "下"
    return "下下"


def _shichen(h: int, m: int) -> str:
    i = 0 if h == 23 else (h + 1) // 2 % 12
    start = 23 if h == 23 else (h // 2) * 2 + 1
    k = ((h - start) * 60 + m) // 15
    return f"{_SHICHEN[i]}{'初' if k == 0 else _MARKS[min(7, k)]}刻"


def _cn_number(n: int) -> str:
    if 1 <= n <= 10:
        return ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"][n - 1]
    if 11 <= n <= 19:
        return f"十{_cn_number(n - 10)}"
    if n == 20:
        return "二十"
    return f"二十{_cn_number(n - 20)}"


def _night_moon_name(d: int) -> str:
    special = {15: "望月", 16: "既望月", 17: "立待月", 18: "居待月", 19: "寝待月", 30: "晦月"}
    return special.get(d, f"{_cn_number(d)}夜月")


def _moon_wuxing(d: int) -> str:
    return next(e for t, e in ((6, "水"), (11, "木"), (16, "火"), (22, "金"), (float("inf"), "土")) if d <= t)


def _moon_luck(d: int) -> str:
    table = {
        "大吉": {1, 3, 8, 11, 15, 16, 23, 28},
        "吉": {2, 7, 13, 18, 22, 27, 29, 30},
        "平": {5, 9, 10, 14, 20, 24, 25},
        "凶": {4, 6, 12, 17, 19, 21, 26},
    }
    for luck, days in table.items():
        if d in days:
            return luck
    return "平吉"


def _lunar_day_num(lunar_day_cn: str) -> int:
    mapping = {}
    for i in range(1, 31):
        if i <= 10:
            mapping[f"初{_cn_number(i)}"] = i
        elif i < 20:
            mapping[f"十{_cn_number(i - 10)}"] = i
        elif i == 20:
            mapping["二十"] = i
        else:
            mapping[f"廿{_cn_number(i - 20)}"] = i
    mapping["三十"] = 30
    return mapping.get(lunar_day_cn, 1)


def _moon_phase(dt: datetime, lunar_day: int) -> tuple[str, dict[str, Any]]:
    y, m, d = dt.year, dt.month, dt.day
    h, mi, s = dt.hour, dt.minute, dt.second
    yy, mm = y, m
    if mm <= 2:
        yy -= 1
        mm += 12
    a = yy // 100
    b = 2 - a + a // 4
    jd = (
        int(365.25 * (yy + 4716))
        + int(30.6001 * (mm + 1))
        + d
        + b
        - 1524.5
        + (h + mi / 60 + s / 3600) / 24
    )
    phase = (jd - 2451550.1) / 29.530588853
    moon_age = phase * 29.530588853 % 29.530588853
    D = 297.8501921 + 445267.1114034 * ((jd - 2451545.0) / 36525)
    i = math.degrees(math.acos(math.cos(math.radians(D))))
    phase_percent = (1 + math.cos(math.radians(i))) / 2 * 100
    name = next(p for t, p in _PHASE_THRESHOLDS if moon_age < t)
    attrs = {
        "月龄": f"{moon_age:.1f} 天",
        "夜月": _night_moon_name(lunar_day),
        "照亮度": f"{phase_percent:.1f}%",
        "月相说明": _PHASE_DESC.get(name, ""),
        "阴阳": "阴" if lunar_day > 15 else "阳",
        "五行": _moon_wuxing(lunar_day),
        "吉凶": _moon_luck(lunar_day),
    }
    return name, attrs


def _process_solar_terms(solar_terms_dict: dict, month: int, day: int) -> str:
    terms = sorted(solar_terms_dict.items(), key=lambda x: (x[1][0], x[1][1]))
    for i, (term, (m, d)) in enumerate(terms):
        if i == len(terms) - 1 and (m < month or (m == month and d <= day)):
            return term
        if i < len(terms) - 1:
            nm, nd = terms[i + 1][1]
            if (m < month or (m == month and d <= day)) and (
                nm > month or (nm == month and nd > day)
            ):
                return term
        if i == 0 and (m > month or (m == month and d > day)):
            return terms[-1][0]
    return ""


def compute_almanac(d: date) -> dict[str, Any]:
    try:
        import cnlunar
    except Exception:
        return {}
    try:
        now = datetime.now()
        dt = datetime.combine(d, now.time() if d == now.date() else time(12, 0))
        lunar = cnlunar.Lunar(dt, godType="8char")
        good = list(getattr(lunar, "goodThing", []) or [])
        bad = list(getattr(lunar, "badThing", []) or [])
        good_gods = list(getattr(lunar, "goodGodName", []) or [])
        bad_gods = list(getattr(lunar, "badGodName", []) or [])
        level = getattr(lunar, "todayLevelName", None)
        if not level or level == "无":
            level = _calc_level_name(len(good_gods), len(bad_gods))
        term = _process_solar_terms(
            getattr(lunar, "thisYearSolarTermsDic", {}) or {}, d.month, d.day
        )
        lunar_day = _lunar_day_num(getattr(lunar, "lunarDayCn", "") or "")
        yue_xiang, yue_xiang_attrs = _moon_phase(dt, lunar_day)
        peng = ""
        try:
            peng = _clean_text("".join(lunar.get_pengTaboo(long=4, delimit=" ")))
        except Exception:
            pass
        nayin = ""
        try:
            nayin = lunar.get_nayin() or ""
        except Exception:
            pass
        tai = ""
        try:
            tai = lunar.get_fetalGod() or ""
        except Exception:
            pass
        return {
            "suit": _clean_text(" ".join(good)) or "暂无",
            "avoid": _clean_text(" ".join(bad)) or "暂无",
            "eight_char": f"{lunar.year8Char} {lunar.month8Char} {lunar.day8Char} {lunar.twohour8Char}",
            "hour": _shichen(dt.hour, dt.minute),
            "clash": getattr(lunar, "chineseZodiacClash", "") or "",
            "moon_phase": yue_xiang,
            "solar_term": term,
            "taboo": peng,
            "good_spirit": _clean_text(" ".join(good_gods)),
            "bad_spirit": _clean_text(" ".join(bad_gods)),
            "fetus": tai,
            "tone": nayin,
            "triad": _clean_text(" ".join(getattr(lunar, "zodiacMark3List", []) or [])),
            "hexad": getattr(lunar, "zodiacMark6", "") or "",
            "grade": level,
            "zodiac_sign": getattr(lunar, "starZodiac", "") or "",
            "season": getattr(lunar, "lunarSeason", "") or "",
            "moon_phase_attrs": yue_xiang_attrs,
        }
    except Exception:
        return {}
