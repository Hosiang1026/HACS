from datetime import timedelta

from homeassistant.const import UnitOfLength, UnitOfSpeed, UnitOfTime, UnitOfVolume

try:
    from homeassistant.const import UnitOfCurrency

    UNIT_CNY = UnitOfCurrency.CNY
except (ImportError, AttributeError):
    UNIT_CNY = "CNY"

UNIT_L = UnitOfVolume.LITERS
UNIT_KM = UnitOfLength.KILOMETERS
UNIT_M = UnitOfLength.METERS
UNIT_KMH = UnitOfSpeed.KILOMETERS_PER_HOUR
UNIT_DAY = UnitOfTime.DAYS
UNIT_MIN = UnitOfTime.MINUTES
try:
    UNIT_YEAR = UnitOfTime.YEARS
except AttributeError:
    UNIT_YEAR = "y"
UNIT_CNY_PER_L = f"{UNIT_CNY}/L"
UNIT_CNY_PER_KM = f"{UNIT_CNY}/km"
UNIT_L_PER_100KM = f"{UNIT_L}/100km"

DOMAIN = "ha_car_stats"

PROVINCE_CODE_MAPPING = {
    "北京": "bj",
    "天津": "tj",
    "河北": "he",
    "山西": "sx",
    "内蒙古": "nm",
    "辽宁": "ln",
    "吉林": "jl",
    "黑龙江": "hl",
    "上海": "sh",
    "江苏": "js",
    "浙江": "zj",
    "安徽": "ah",
    "福建": "fj",
    "江西": "jx",
    "山东": "sd",
    "河南": "ha",
    "湖北": "hb",
    "湖南": "hn",
    "广东": "gd",
    "广西": "gx",
    "海南": "hi",
    "重庆": "cq",
    "四川": "sc",
    "贵州": "gz",
    "云南": "yn",
    "西藏": "xz",
    "陕西": "sn",
    "甘肃": "gs",
    "青海": "qh",
    "宁夏": "nx",
    "新疆": "xj",
}
PROVINCES = list(PROVINCE_CODE_MAPPING.keys())

SURVEILLANCE_INFO_INTERVAL = timedelta(days=1)
LOGIN_ONCE_INTERVAL = timedelta(days=1)
GET_KEEPALIVE_INTERVAL = timedelta(minutes=15)
API_BACKOFF_MAX = timedelta(hours=2)
API_RATE_LIMIT_COOLDOWN = timedelta(hours=2)
REQUEST_TIMEOUT = 30

QR_CODE_API_URL = "https://gab.122.gov.cn/eapp/qrCode/loginQrCodeImg"
QR_CODE_QUERY_URL = "https://gab.122.gov.cn/eapp/qrCode/queryQRCode"
QR_POLL_INTERVAL = 2
QR_POLL_TIMEOUT = 180

DEFAULT_PRICES = {92: 7.50, 95: 8.00, 98: 9.00}
PRICE_KEYS = {
    92: ("92", "92#", "gas92", "price_92", "92号", "92号汽油"),
    95: ("95", "95#", "gas95", "price_95", "95号", "95号汽油"),
    98: ("98", "98#", "gas98", "price_98", "98号", "98号汽油"),
}

DEFAULT_TANK = 60
DEFAULT_MAINT_KM = 10000
DEFAULT_MAINT_DAYS = 365

CONF_ACCESS_TOKEN = "accessToken"
CONF_JSESSIONID = "JSESSIONID-L"
CONF_ACW_TC = "acw_tc"
CONF_SF = "sf"
CONF_URL = "url"
CONF_LOGIN_AT = "login_at"
CONF_ACCOUNT_NAME = "account_name"
CONF_PROVINCE_NAME = "province_name"
CONF_VEHICLE_INDEX = "vehicle_index"
CONF_NAME = "name"
CONF_ODOMETER_ENTITY = "odometer_entity"
CONF_FUEL_PRICE_ENTITY = "fuel_price_entity"
CONF_ODOMETER = "odometer"
CONF_FUEL_PRICE = "fuel_price"
CONF_FUEL_GRADE = "fuel_grade"
CONF_TANK_CAPACITY = "tank_capacity"
CONF_MAINT_KM = "maint_interval_km"
CONF_MAINT_DAYS = "maint_interval_days"
CONF_PURCHASE_DATE = "purchase_date"
CONF_INSPECT_EXPIRY = "inspect_expiry"
CONF_MAINT_DATE = "maint_date"
CONF_MAINT_ODO = "maint_odometer"
CONF_BATTERY_REPLACE_DATE = "battery_replace_date"
CONF_NOTIFY_ENABLE = "car_notify"
CONF_NOTIFY = "notify"
CONF_ANNOUNCE = "announce"
CONF_NOTIFY_VIOLATION = "notify_violation"
CONF_NOTIFY_YEARLY = "notify_yearly"
CONF_NOTIFY_MAINT = "notify_maint"
CONF_NOTIFY_INSURANCE = "notify_insurance"
CONF_NOTIFY_INSPECT = "notify_inspect"
CONF_NOTIFY_LICENSE = "notify_license"
CONF_INSURANCE_EXPIRY = "insurance_expiry"
CONF_EXPIRE_DAYS = "expire_notify_days"
DEFAULT_NOTIFY_ENABLE = False
DEFAULT_NOTIFY_VIOLATION = False
DEFAULT_NOTIFY_YEARLY = True
DEFAULT_NOTIFY_MAINT = False
DEFAULT_NOTIFY_INSURANCE = False
DEFAULT_NOTIFY_INSPECT = False
DEFAULT_NOTIFY_LICENSE = False
DEFAULT_EXPIRE_DAYS = 30

CONF_ENABLE_12123 = "enable_12123"
CONF_ENABLE_AMAP = "enable_amap"
CONF_AMAP_KEY = "amap_key"
CONF_AMAP_SESSIONID = "amap_sessionid"
CONF_AMAP_PARAMDATA = "amap_paramdata"
CONF_AMAP_TID = "amap_tid"
CONF_AMAP_LOGIN_AT = "amap_login_at"
CONF_PLATE = "plate"
CONF_OWNERS = "owners"
CONF_POLL_ACTIVE = "poll_active_minutes"
CONF_POLL_EXCLUDE_ZONES = "poll_exclude_zones"
CONF_ADDRESSAPI = "addressapi"
CONF_ADDRESSAPI_KEY = "api_key"
CONF_PRIVATE_KEY = "private_key"
CONF_ADDRESS_DISTANCE = "address_distance"
CONF_COMMUTE_ZONE = "commute_zone"
CONF_COMMUTE_SPEED = "commute_speed"
CONF_COMMUTE_INTERVAL = "commute_interval"
CONF_NOTIFY_LEAVE = "notify_leave"
CONF_NOTIFY_ARRIVE = "notify_arrive"
CONF_MAP_GCJ_LAT = "map_gcj_lat"
CONF_MAP_GCJ_LNG = "map_gcj_lng"
CONF_MAP_BD_LAT = "map_bd_lat"
CONF_MAP_BD_LNG = "map_bd_lng"

DEFAULT_POLL_ACTIVE = 30
DEFAULT_ADDRESS_DISTANCE = 50
DEFAULT_COMMUTE_SPEED = 30
DEFAULT_COMMUTE_INTERVAL = 20
AMAP_API_HOST = "http://ts.amap.com/ws/tservice/internal/link/mobile/get?ent=2&in="

KEY_PARKING_TIME = "parkingtime"
KEY_SPEED = "speed"
KEY_ADDRESS = "address"
KEY_NAVISTATUS = "navistatus"
KEY_CARSTATUS = "carstatus"
KEY_DRIVETIME = "drivetime"
KEY_COMMUTE_DISTANCE = "commute_distance"
KEY_COMMUTE_TIME = "commute_time"
KEY_NAVI_DEST = "navi_dest"
KEY_COMMUTE_TOLL = "commute_toll"
KEY_TRAFFIC_LIGHTS = "traffic_lights"
KEY_COURSE = "course"
KEY_RESTRICT_TAIL = "restrict_tail"
KEY_QUERYTIME = "querytime"
KEY_AMAP_CALLS = "api_calls"

AMAP_DEFAULT_SENSORS = (
    KEY_PARKING_TIME,
    KEY_SPEED,
    KEY_ADDRESS,
    KEY_NAVISTATUS,
    KEY_CARSTATUS,
    KEY_DRIVETIME,
    KEY_COMMUTE_DISTANCE,
    KEY_COMMUTE_TIME,
    KEY_NAVI_DEST,
    KEY_COMMUTE_TOLL,
    KEY_TRAFFIC_LIGHTS,
    KEY_COURSE,
    KEY_RESTRICT_TAIL,
    KEY_QUERYTIME,
    KEY_AMAP_CALLS,
)

VIOLATION_POINTS_MAP = {
    "不按规定停车": 0,
    "驾驶机动车不按交通信号灯指示通行的": 6,
    "人行道不停车让行的": 3,
    "违反禁止标线指示": 3,
    "驾驶校车、中型以上载客载货汽车、危险物品运输车辆以外的机动车在高速公路上行驶超过规定时速百分之二十以上未达到百分之五十的": 6,
    "驾驶校车、中型以上载客载货汽车、危险物品运输车辆以外的机动车在城市快速路上行驶超过规定时速百分之二十以上未达到百分之五十的": 6,
    "驾驶校车、中型以上载客载货汽车、危险物品运输车辆以外的机动车在高速公路以外的道路上行驶超过规定时速百分之十以上未达到百分之二十的": 0,
    "不按导向车道行驶": 0,
    "驾驶校车、中型以上载客载货汽车、危险物品运输车辆以外的机动车在高速公路、城市快速路以外的道路上行驶超过规定时速百分之二十以上未达到百分之五十的": 3,
}

ERROR_MESSAGES = {
    "connection_error": "网络连接错误，请检查网络",
    "server_error": "服务器错误，请稍后重试",
    "invalid_response": "服务器响应格式错误",
    "unknown_error": "未知错误",
    "no_image_data": "未获取到二维码图片",
    "session_lost": "会话丢失，请重新配置",
    "session_recreate_failed": "重新创建会话失败，请重试",
    "incomplete_auth": "认证信息不完整，请重试",
    "please_scan": "请扫描二维码",
    "second_request_failed": "第二次请求失败，请重试",
    "second_request_error": "第二次请求异常，请重试",
    "no_redirect_url": "操作失败: 未获取到重定向URL",
    "auth_failed": "认证过程中获取用户信息失败",
    "missing_cookies": "登录认证失败，未获取到必需的认证信息",
    "no_vehicles": "未获取到车辆列表",
}
