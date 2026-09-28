"""Const file for ha_xiaomi_cloud."""
from homeassistant.const import Platform

DOMAIN = "ha_xiaomi_cloud"
INTEGRATION_MANUFACTURER = "狂欢马克思"
INTEGRATION_HUB_SUFFIX = "_hub"

# 小米 API 中 google = GCJ-02，与高德地图一致
COORDINATE_GCJ02 = "google"

CONF_PASS_TOKEN = "pass_token"
CONF_USER_ID = "user_id"
CONF_DEVICE_ID = "device_id"
CONF_VERIFY_CODE = "verify_code"

FLAG_PHONE = 4
FLAG_EMAIL = 8

CONF_AMAP_KEY = "amap_key"
CONF_AMAP_ENABLED = "amap_enabled"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_MAX_INTERVAL = "max_interval"
CONF_COMMUTE_ENABLED = "commute_enabled"
CONF_COMMUTE_ZONES = "commute_zones"
CONF_ACTIVITY_ENTITY = "activity_entity"

COMMUTE_MODE_DRIVING = "driving"
COMMUTE_MODE_BICYCLING = "bicycling"
ACTIVITY_BIKE = ("在家", "公司")
ACTIVITY_DRIVE = ("外出", "外地")
COMMUTE_BIKE_MAX_KM = 10
HOME_EXIT_BUFFER_M = 200
# 高德个人开发者免费额度约 5000 次/日，预留余量
AMAP_DAILY_LIMIT = 4500

DEFAULT_AMAP_ENABLED = False
DEFAULT_UPDATE_INTERVAL = 3
DEFAULT_MAX_INTERVAL = 3
DEFAULT_COMMUTE_ENABLED = False
DEFAULT_COMMUTE_ZONES: list[str] = []
DEFAULT_ACTIVITY_ENTITY: list[str] = []

OPTION_KEYS = frozenset(
    {
        CONF_UPDATE_INTERVAL,
        CONF_MAX_INTERVAL,
        CONF_COMMUTE_ENABLED,
        CONF_COMMUTE_ZONES,
        CONF_ACTIVITY_ENTITY,
        CONF_AMAP_ENABLED,
        CONF_AMAP_KEY,
    }
)


def default_options() -> dict:
    return {
        CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
        CONF_MAX_INTERVAL: DEFAULT_MAX_INTERVAL,
        CONF_COMMUTE_ENABLED: DEFAULT_COMMUTE_ENABLED,
        CONF_COMMUTE_ZONES: list(DEFAULT_COMMUTE_ZONES),
        CONF_ACTIVITY_ENTITY: list(DEFAULT_ACTIVITY_ENTITY),
        CONF_AMAP_ENABLED: DEFAULT_AMAP_ENABLED,
        CONF_AMAP_KEY: "",
    }


PLATFORMS = [Platform.BUTTON, Platform.DEVICE_TRACKER, Platform.SENSOR, Platform.TEXT]


def activity_entities(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item or "").strip()]
