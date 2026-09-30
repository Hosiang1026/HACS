from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "ha_honor_cloud"
MANUFACTURER = "狂欢马克思"
HUB_NAME = "荣耀云服务"
HUB_MODEL = "ha_honor_cloud"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_BASE_URL = "service_base_url"
CONF_SESSION_KEY = "session_key"
CONF_API_KEY = "api_key"
CONF_AMAP_API_KEY = "amap_api_key"
CONF_AMAP_DAILY_LIMIT = "amap_daily_limit"
CONF_ENABLE_AMAP = "enable_amap"
CONF_COMMUTE_ENABLED = "commute_enabled"
CONF_COMMUTE_ZONES = "commute_zones"
CONF_ACTIVITY_ENTITY = "activity_entity"

COMMUTE_MODE_DRIVING = "driving"
COMMUTE_MODE_BICYCLING = "bicycling"
ACTIVITY_BIKE = ("在家", "公司")
ACTIVITY_DRIVE = ("外出", "外地")
COMMUTE_BIKE_MAX_KM = 10
HOME_EXIT_BUFFER_M = 200

CONF_INTERVAL = "interval"
CONF_DEVICE_FILTER = "device_filter"
CONF_USE_PAGE_LOCATION = "use_page_location"

DEFAULT_INTERVAL = 180
LOW_BATTERY_PERCENT = 10
DEFAULT_USE_PAGE_LOCATION = True
DEFAULT_AMAP_DAILY_LIMIT = 4500
DEFAULT_ENABLE_AMAP = False
DEFAULT_COMMUTE_ENABLED = False
DEFAULT_COMMUTE_ZONES: list[str] = []
DEFAULT_ACTIVITY_ENTITY: list[str] = []

PLATFORMS = [
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.TEXT,
]

API_STATUS = "/status"
API_LOGIN = "/login"
API_SYNC = "/sync"

ATTR_ACCURACY = "accuracy"
ATTR_BATTERY = "battery"
ATTR_ADDRESS = "address"
ATTR_GCJ02_LAT = "gcj02_lat"
ATTR_GCJ02_LNG = "gcj02_lng"
ATTR_RAW = "raw"
ATTR_DEVICE_NAME = "device_name"
ATTR_LAST_UPDATE = "last_update"

DEVICE_CLASS_BATTERY = "battery"
DEVICE_CLASS_TIMESTAMP = "timestamp"

ICON_DEVICE_TRACKER = "mdi:cellphone"
ICON_BATTERY = "mdi:battery"
ICON_SYNC = "mdi:sync"
ICON_LOGIN = "mdi:login"
ICON_CLOCK = "mdi:clock"
ICON_COUNTER = "mdi:counter"
