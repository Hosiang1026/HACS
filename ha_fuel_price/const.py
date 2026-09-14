from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ha_fuel_price"
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

CONF_PROVINCES = "provinces"
CONF_PROVINCE_NAME = "province_name"
CONF_PROVINCE_CODE = "province_code"
CONF_NOTIFY_LOW = "notify_low"
CONF_NOTIFY_ENABLE = "notify_enable"
CONF_NOTIFY_DAILY = "notify_daily"
CONF_NOTIFY_WEEKEND = "notify_weekend"
CONF_NOTIFY = "notify"
CONF_FILL_LITERS = "fill_liters"

DEFAULT_NAME = "燃油价格"
FETCH_HOUR = 0
FETCH_MINUTE = 15
DEFAULT_NOTIFY_ENABLE = True
DEFAULT_NOTIFY_DAILY = False
DEFAULT_NOTIFY_WEEKEND = True
DEFAULT_NOTIFY_LOW = False
DEFAULT_FILL_LITERS = 60.0
NEAR_LOW_DELTA = 0.1


def normalize_fill_liters(raw: object) -> float:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_FILL_LITERS
    if value < 0:
        return 0.0
    return round(value, 2)


STORAGE_KEY = f"{DOMAIN}_low_prices"
STORAGE_VERSION = 1

FUEL_92 = "92"
FUEL_95 = "95"
FUEL_98 = "98"
FUEL_0 = "0"

FUEL_TYPES = (FUEL_92, FUEL_95, FUEL_98, FUEL_0)

FUEL_LABELS = {
    FUEL_92: "92号汽油",
    FUEL_95: "95号汽油",
    FUEL_98: "98号汽油",
    FUEL_0: "0号柴油",
}

FUEL_ICONS = {
    FUEL_92: "mdi:gas-station",
    FUEL_95: "mdi:gas-station",
    FUEL_98: "mdi:gas-station",
    FUEL_0: "mdi:fuel",
}

BASE_URL = "http://m.qiyoujiage.com"
PROVINCE_URL = "http://m.qiyoujiage.com/{code}.shtml"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

PROVINCE_CODES: dict[str, str] = {
    "北京": "beijing",
    "天津": "tianjin",
    "上海": "shanghai",
    "重庆": "chongqing",
    "河北": "hebei",
    "山西": "shanxi",
    "辽宁": "liaoning",
    "吉林": "jilin",
    "黑龙江": "heilongjiang",
    "江苏": "jiangsu",
    "浙江": "zhejiang",
    "安徽": "anhui",
    "福建": "fujian",
    "江西": "jiangxi",
    "山东": "shandong",
    "河南": "henan",
    "湖北": "hubei",
    "湖南": "hunan",
    "广东": "guangdong",
    "广西": "guangxi",
    "海南": "hainan",
    "四川": "sichuan",
    "贵州": "guizhou",
    "云南": "yunnan",
    "西藏": "xizang",
    "陕西": "shanxi-3",
    "甘肃": "gansu",
    "青海": "qinghai",
    "宁夏": "ningxia",
    "新疆": "xinjiang",
    "内蒙古": "neimenggu",
}

PROVINCE_OPTIONS = [
    {"value": code, "label": name} for name, code in PROVINCE_CODES.items()
]

CODE_TO_NAME = {code: name for name, code in PROVINCE_CODES.items()}
