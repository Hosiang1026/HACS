from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Union

from ._tables import LUNAR_INFO, STERM_INFO

SOLAR_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
ANIMALS = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]
SOLAR_TERM = [
    "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑",
    "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
]
NSTR1 = ["日", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
NSTR2 = ["初", "十", "廿", "卅"]
NSTR3 = ["正", "二", "三", "四", "五", "六", "七", "八", "九", "十", "冬", "腊"]

_UTC = timezone.utc
_EPOCH = datetime(1970, 1, 1, tzinfo=_UTC)


def _ymd(year: int, month: int, day: int) -> date:
    return date(year, month, 1) + timedelta(days=day - 1)


def _js_utc(year: int, month_index: int, day: int) -> datetime:
    y = year
    m = month_index
    while m >= 12:
        y += 1
        m -= 12
    while m < 0:
        y -= 1
        m += 12
    return datetime(y, m + 1, 1, tzinfo=_UTC) + timedelta(days=day - 1)


def _js_weekday(d: date) -> int:
    return d.isoweekday() % 7


def l_year_days(y: int) -> int:
    total = 348
    i = 0x8000
    while i > 0x8:
        total += 1 if (LUNAR_INFO[y - 1900] & i) else 0
        i >>= 1
    return total + leap_days(y)


def leap_months(y: int) -> int:
    return LUNAR_INFO[y - 1900] & 0xF


def leap_days(y: int) -> int:
    if leap_months(y):
        return 30 if (LUNAR_INFO[y - 1900] & 0x10000) else 29
    return 0


def month_days(y: int, m: int) -> int:
    if m > 12 or m < 1:
        return -1
    return 30 if (LUNAR_INFO[y - 1900] & (0x10000 >> m)) else 29


def solar_days(y: int, m: int) -> int:
    if m > 12 or m < 1:
        return -1
    ms = m - 1
    if ms == 1:
        return 29 if ((y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)) else 28
    return SOLAR_MONTH[ms]


def to_gan_zhi_year(l_year: int) -> str:
    gan_key = (l_year - 3) % 10
    zhi_key = (l_year - 3) % 12
    if gan_key == 0:
        gan_key = 10
    if zhi_key == 0:
        zhi_key = 12
    return GAN[gan_key - 1] + ZHI[zhi_key - 1]


def to_astro(c_month: int, c_day: int) -> str:
    s = "魔羯水瓶双鱼白羊金牛双子巨蟹狮子处女天秤天蝎射手魔羯"
    arr = [20, 19, 21, 21, 21, 22, 23, 23, 23, 23, 22, 22]
    start = c_month * 2 - (2 if c_day < arr[c_month - 1] else 0)
    return s[start : start + 2] + "座"


def to_gan_zhi(offset: int) -> str:
    return GAN[offset % 10] + ZHI[offset % 12]


def get_term(y: int, n: int) -> int:
    if y < 1900 or y > 2100:
        return -1
    if n < 1 or n > 24:
        return -1
    table = STERM_INFO[y - 1900]
    info = [str(int(table[i : i + 5], 16)) for i in range(0, 30, 5)]
    calday = []
    for part in info:
        calday.extend([part[0:1], part[1:3], part[3:4], part[4:6]])
    return int(calday[n - 1])


def to_china_month(m: int) -> Union[str, int]:
    if m > 12 or m < 1:
        return -1
    return NSTR3[m - 1] + "月"


def to_china_day(d: int) -> str:
    if d == 10:
        return "初十"
    if d == 20:
        return "二十"
    if d == 30:
        return "三十"
    return NSTR2[d // 10] + NSTR1[d % 10]


def get_animal(y: int) -> str:
    return ANIMALS[(y - 4) % 12]


def solar2lunar(y: Optional[int] = None, m: Optional[int] = None, d: Optional[int] = None) -> Any:
    if y is None:
        today = date.today()
        y, m, d = today.year, today.month, today.day
    else:
        y, m, d = int(y), int(m), int(d)

    if y < 1900 or y > 2100:
        return -1
    if y == 1900 and m == 1 and d < 31:
        return -1

    obj_date = date(y, m, d)
    y, m, d = obj_date.year, obj_date.month, obj_date.day

    offset = (
        _js_utc(obj_date.year, obj_date.month - 1, obj_date.day)
        - _js_utc(1900, 0, 31)
    ).days

    i = 1900
    temp = 0
    while i < 2101 and offset > 0:
        temp = l_year_days(i)
        offset -= temp
        i += 1
    if offset < 0:
        offset += temp
        i -= 1

    today_obj = date.today()
    is_today = today_obj.year == y and today_obj.month == m and today_obj.day == d

    n_week = _js_weekday(obj_date)
    c_week = NSTR1[n_week]
    if n_week == 0:
        n_week = 7

    year = i
    leap = leap_months(i)
    is_leap = False

    i = 1
    while i < 13 and offset > 0:
        if leap > 0 and i == (leap + 1) and not is_leap:
            i -= 1
            is_leap = True
            temp = leap_days(year)
        else:
            temp = month_days(year, i)
        if is_leap and i == (leap + 1):
            is_leap = False
        offset -= temp
        i += 1

    if offset == 0 and leap > 0 and i == leap + 1:
        if is_leap:
            is_leap = False
        else:
            is_leap = True
            i -= 1
    if offset < 0:
        offset += temp
        i -= 1

    month = i
    day = offset + 1
    sm = m - 1
    gz_y = to_gan_zhi_year(year)

    first_node = get_term(y, m * 2 - 1)
    second_node = get_term(y, m * 2)

    gz_m = to_gan_zhi((y - 1900) * 12 + m + 11)
    if d >= first_node:
        gz_m = to_gan_zhi((y - 1900) * 12 + m + 12)

    is_term = False
    term = None
    if first_node == d:
        is_term = True
        term = SOLAR_TERM[m * 2 - 2]
    if second_node == d:
        is_term = True
        term = SOLAR_TERM[m * 2 - 1]

    day_cyclical = (_js_utc(y, sm, 1) - _EPOCH).days + 25567 + 10
    gz_d = to_gan_zhi(day_cyclical + d - 1)
    astro = to_astro(m, d)

    return {
        "lYear": year,
        "lMonth": month,
        "lDay": day,
        "Animal": get_animal(year),
        "IMonthCn": ("闰" if is_leap else "") + to_china_month(month),
        "IDayCn": to_china_day(day),
        "cYear": y,
        "cMonth": m,
        "cDay": d,
        "gzYear": gz_y,
        "gzMonth": gz_m,
        "gzDay": gz_d,
        "isToday": is_today,
        "isLeap": is_leap,
        "nWeek": n_week,
        "ncWeek": "星期" + c_week,
        "isTerm": is_term,
        "Term": term,
        "astro": astro,
    }


def lunar2solar_offset(y: int, m: int, d: int, is_leap_month: bool = False) -> int:
    is_leap_month = bool(is_leap_month)
    leap_month = leap_months(y)

    if is_leap_month and leap_month != m:
        return -1
    if (y == 2100 and m == 12 and d > 1) or (y == 1900 and m == 1 and d < 31):
        return -1

    day = month_days(y, m)
    _day = day
    if is_leap_month:
        _day = leap_days(y)

    if y < 1900 or y > 2100:
        return -1
    if d > _day:
        d = _day

    offset = 0
    for i in range(1900, y):
        offset += l_year_days(i)

    is_add = False
    for i in range(1, m):
        leap = leap_months(y)
        if not is_add:
            if leap <= i and leap > 0:
                offset += leap_days(y)
                is_add = True
        offset += month_days(y, i)

    if is_leap_month:
        offset += day

    return offset


def lunar2solar(y: int, m: int, d: int, is_leap_month: bool = False) -> Any:
    offset = lunar2solar_offset(y, m, d, is_leap_month)
    if offset == -1:
        return -1
    stmap = _js_utc(1900, 1, 30)
    cal_obj = stmap + timedelta(days=offset + d - 31)
    return {
        "cYear": cal_obj.year,
        "cMonth": cal_obj.month,
        "cDay": cal_obj.day,
    }


def conversion(s: str) -> Optional[str]:
    try:
        y = int(s[0:4])
        m = int(s[5:7])
        d = int(s[8:10])
    except (TypeError, ValueError, IndexError):
        return None
    solar = lunar2solar(y, m, d)
    if not isinstance(solar, dict):
        return None
    return f"{solar['cYear']:04d}-{solar['cMonth']:02d}-{solar['cDay']:02d}"


def conversion_term(year, month_str, num) -> Optional[str]:
    day = get_term(int(year), int(num))
    if day < 0:
        return None
    term_day = f"{day:02d}" if day >= 10 else f"0{day}"
    return f"{year}-{month_str}-{term_day}"


def conversion_parent_date(year, month, weeks, nums) -> Optional[str]:
    year = int(year)
    month_i = int(month)
    weeks = int(weeks)
    nums = int(nums)
    month_s = str(month) if isinstance(month, str) else f"{month_i:02d}"

    start_date = date(year, month_i, 1)
    day = _js_weekday(start_date)
    if day == 0:
        day = 7

    if month_i == 12:
        days = 31
    else:
        days = (date(year, month_i + 1, 1) - timedelta(days=1)).day

    y_rem = days % 7
    if 7 - day >= y_rem:
        zhou = days // 7 + 1
    else:
        zhou = days // 7 + 2

    end_date_wd = _js_weekday(date(year, month_i, days))
    if end_date_wd == 0:
        zhou -= 1

    times_array = [0] * max(zhou, 1)
    times_array[0] = 1 + (nums - day)
    for i in range(1, zhou):
        times_array[i] = times_array[0] + 7 * i

    array = []
    for item in times_array:
        if item > 0 and item <= days:
            array.append(f"{year}-{month_s}-{item:02d}")

    if not array:
        return None
    if len(array) > weeks - 1:
        return array[weeks - 1]
    return array[-1]


def sum_time_to_now(target: str, now: str) -> int:
    t = date.fromisoformat(target.replace("/", "-"))
    n = date.fromisoformat(now.replace("/", "-"))
    return abs((t - n).days)


def diff_time_to_daily(now: str, target: str) -> int:
    n = date.fromisoformat(now.replace("/", "-"))
    t = date.fromisoformat(target.replace("/", "-"))
    return abs((n - t).days)


def get_text_length(s: str) -> int:
    length = 0
    for ch in s:
        code = ord(ch)
        if 0 <= code <= 127:
            length += 1
        else:
            length += 2
    return length


def calculate_san_fu_dates(year: int) -> Optional[list]:
    if not (1999 < year < 2100):
        return None

    objvalue = year - 2000
    objvalue2 = objvalue
    if objvalue > 80:
        objvalue -= 80
    if objvalue > 40:
        objvalue -= 40
    objvalue = int(objvalue / 4)
    if objvalue2 % 2 == 1:
        objvalue += 5
    num = 11 - objvalue
    date6 = 10 if num > 1 else 20
    date1 = date6 + num
    date2 = date1 + 10
    date3 = 10 if date1 > 18 else 20
    date4 = date2 + date3 - 31
    return [
        {
            "name": "初伏",
            "startDate": _ymd(year, 7, date1),
            "endDate": _ymd(year, 7, date1 + date3 - 1),
            "days": date3,
        },
        {
            "name": "中伏",
            "startDate": _ymd(year, 7, date2),
            "endDate": _ymd(year, 7, date2 + date3 - 1),
            "days": date3,
        },
        {
            "name": "末伏",
            "startDate": _ymd(year, 8, date4),
            "endDate": _ymd(year, 8, date4 + 9),
            "days": 10,
        },
    ]


def calculate_mei_yu_season(
    year: int,
    mang_zhong_date: date,
    xiao_shu_date: date,
) -> Optional[dict]:
    if not (1999 < year < 2100):
        return None
    if not isinstance(mang_zhong_date, date) or not isinstance(xiao_shu_date, date):
        return None

    start_day = mang_zhong_date + timedelta(days=6)

    day_of_week = _js_weekday(xiao_shu_date)
    if day_of_week == 6:
        end_day = xiao_shu_date
    else:
        days_to_add = 6 - day_of_week
        end_day = xiao_shu_date + timedelta(days=days_to_add)

    duration = (end_day - start_day).days + 1
    return {
        "startDate": start_day,
        "endDate": end_day,
        "duration": duration,
    }


def calculate_san_jiu_season(year: int, dongzhi_date: date) -> Optional[list]:
    if not (1999 < year < 2100):
        return None
    if not isinstance(dongzhi_date, date):
        return None

    names = ["一九", "二九", "三九", "四九"]
    result = []
    for i in range(1, 5):
        start_day = dongzhi_date + timedelta(days=(i - 1) * 9)
        end_day = dongzhi_date + timedelta(days=i * 9 - 1)
        result.append({
            "name": names[i - 1],
            "startDate": start_day,
            "endDate": end_day,
        })
    return result
