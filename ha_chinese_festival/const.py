from homeassistant.const import Platform

DOMAIN = "ha_chinese_festival"

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.DATE]

CONF_NOTIFY = "notify"
CONF_NOTIFY_CALENDAR = "notify_calendar"
CONF_NOTIFY_FESTIVAL = "notify_festival"
CONF_NOTIFY_MEMORIAL = "notify_memorial"
CONF_NOTIFY_LICENSE = "notify_license"
CONF_NOTIFY_CALENDAR_TIME = "notify_calendar_time"
CONF_NOTIFY_FESTIVAL_TIME = "notify_festival_time"
CONF_NOTIFY_MEMORIAL_TIME = "notify_memorial_time"
CONF_NOTIFY_LICENSE_TIME = "notify_license_time"
CONF_NEAR_FESTIVAL_DAYS = "near_festival_days"
CONF_NEAR_LICENSE_DAYS = "near_license_days"
CONF_NEAR_BIRTHDAY_DAYS = "near_birthday_days"
CONF_NEAR_ANNIVERSARY_DAYS = "near_anniversary_days"
CONF_HOLIDAY_AUTO = "holiday_auto"
CONF_LANGUAGE = "language"
CONF_AI_ENABLED = "ai_enabled"
CONF_AI_API_URL = "ai_api_url"
CONF_AI_API_KEY = "ai_api_key"
CONF_AI_MODEL = "ai_model"
CONF_NOTIFY_RULES = "notify_rules"
CONF_NOTIFY_RULES_ENABLED = "notify_rules_enabled"
CONF_INTENT_ENABLED = "intent_enabled"

AI_MODELS = [
    "deepseek-r1",
    "deepseek-v3.1",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4o",
    "gpt-5",
    "gpt-4.1",
]

CONF_LICENSES = "licenses"
CONF_ANNIVERSARIES = "anniversaries"
CONF_BIRTHDAYS = "birthdays"
CONF_LEGAL = "legal"

CONF_ITEM_ID = "id"
CONF_ITEM_NAME = "name"
CONF_ITEM_DATE = "date"
CONF_ITEM_TYPE = "type"
CONF_ITEM_KIND = "item_kind"
CONF_FREEWAY = "freeway"
CONF_REPAIR = "repair"
CONF_HOLIDAY = "holiday"

ITEM_KIND_LICENSE = "license"
ITEM_KIND_BIRTHDAY = "birthday"
ITEM_KIND_ANNIVERSARY = "anniversary"
ITEM_KIND_LEGAL = "legal"

ITEM_KINDS = [
    ITEM_KIND_LICENSE,
    ITEM_KIND_BIRTHDAY,
    ITEM_KIND_ANNIVERSARY,
    ITEM_KIND_LEGAL,
]

ITEM_KIND_TO_KEY = {
    ITEM_KIND_LICENSE: CONF_LICENSES,
    ITEM_KIND_BIRTHDAY: CONF_BIRTHDAYS,
    ITEM_KIND_ANNIVERSARY: CONF_ANNIVERSARIES,
    ITEM_KIND_LEGAL: CONF_LEGAL,
}

NEXT_CATEGORIES = (
    "sftv",
    "lftv",
    "term",
    "special",
    "internation",
    "seasonal",
    "legal",
    "birthday",
    "anniversary",
)

NEXT_OBJECT_IDS = {
    "sftv": "next_solar",
    "lftv": "next_lunar",
    "term": "next_term",
    "special": "next_special",
    "internation": "next_intl",
    "seasonal": "next_seasonal",
    "legal": "next_legal",
    "birthday": "next_birthday",
    "anniversary": "next_anniversary",
}

ALMANAC_KEYS = (
    "suit",
    "avoid",
    "eight_char",
    "hour",
    "clash",
    "moon_phase",
    "solar_term",
    "taboo",
    "good_spirit",
    "bad_spirit",
    "fetus",
    "tone",
    "triad",
    "hexad",
    "grade",
    "zodiac_sign",
    "season",
)

ALMANAC_MAIN = frozenset(
    {"suit", "avoid", "eight_char", "hour", "clash", "moon_phase", "solar_term"}
)

DEFAULT_NOTIFY_CALENDAR = True
DEFAULT_NOTIFY_FESTIVAL = True
DEFAULT_NOTIFY_MEMORIAL = True
DEFAULT_NOTIFY_LICENSE = True
DEFAULT_NOTIFY_CALENDAR_TIME = "08:00:00"
DEFAULT_NOTIFY_FESTIVAL_TIME = "08:00:00"
DEFAULT_NOTIFY_MEMORIAL_TIME = "08:00:00"
DEFAULT_NOTIFY_LICENSE_TIME = "08:00:00"
DEFAULT_NEAR_FESTIVAL_DAYS = 8
DEFAULT_NEAR_LICENSE_DAYS = 31
DEFAULT_NEAR_BIRTHDAY_DAYS = 7
DEFAULT_NEAR_ANNIVERSARY_DAYS = 7
DEFAULT_HOLIDAY_AUTO = True
DEFAULT_LANGUAGE = "zh-Hans"
DEFAULT_AI_ENABLED = False
DEFAULT_AI_API_URL = "https://api.chatanywhere.tech"
DEFAULT_AI_API_KEY = ""
DEFAULT_AI_MODEL = "deepseek-r1"
DEFAULT_NOTIFY_RULES: dict = {}
DEFAULT_NOTIFY_RULES_ENABLED = False
DEFAULT_INTENT_ENABLED = True

STATE_WORKDAY = "workday"
STATE_HOLIDAY = "holiday"
STATE_WEEKEND = "weekend"
STATE_REST = "rest"
STATE_REPAIR = "repair"

ANNIVERSARY_TYPE_SUM = 0
ANNIVERSARY_TYPE_SOLAR = 1
ANNIVERSARY_TYPE_LUNAR = 2

BIRTHDAY_TYPE_LUNAR = 0
BIRTHDAY_TYPE_SOLAR = 1
