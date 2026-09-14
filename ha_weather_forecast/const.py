from homeassistant.const import Platform

DOMAIN = "ha_weather_forecast"
VERSION = "1.0.1"
FRONTEND_URL_BASE = f"/{DOMAIN}/frontend"

PLATFORMS = [
    Platform.SENSOR,
    Platform.WEATHER,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

CONF_NOTIFY = "notify"
CONF_ANNOUNCE = "announce"
CONF_NOTIFY_ENABLED = "notify_enabled"
CONF_NOTIFY_START = "notify_start"
CONF_NOTIFY_END = "notify_end"
CONF_ANNOUNCE_ENABLED = "announce_enabled"

CONF_ENABLED = "enabled"
CONF_PROVIDER = "provider"
CONF_INSTANCES = "instances"
CONF_INTERVAL = "interval"
CONF_NAME = "name"
CONF_SLUG = "slug"
CONF_LOCATION = "location"
CONF_DISTRICT = "district"
CONF_API_KEY = "api_key"
CONF_API_HOST = "api_host"
CONF_FORECAST_DAYS = "forecast_days"
CONF_INDICES_ENABLED = "indices_enabled"
CONF_NOTIFY_ALARM = "notify_alarm"
CONF_NOTIFY_RAIN = "notify_rain"

PROVIDER_TIANQI = "tianqi"
PROVIDER_QWEATHER = "qweather"
PROVIDER_CAIYUN = "caiyun"

DEFAULT_NAME = "天气预报"
DEFAULT_NOTIFY_ENABLED = True
DEFAULT_NOTIFY_START = "08:00:00"
DEFAULT_NOTIFY_END = "22:00:00"
DEFAULT_WEATHER_INTERVAL = 5
DEFAULT_WEATHER_IDLE_INTERVAL = 60
DEFAULT_FORECAST_DAYS = 7

WEATHER_PEAK_WINDOWS = (
    ((7, 0), (9, 0)),
    ((18, 0), (20, 0)),
)

MANUFACTURER = "狂欢马克思"
