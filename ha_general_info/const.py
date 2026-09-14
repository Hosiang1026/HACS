from homeassistant.const import Platform

DOMAIN = "ha_general_info"
STORAGE_VERSION = 1
VERSION = "1.0.0"

PLATFORMS = [
    Platform.SENSOR,
    Platform.BUTTON,
]

CONF_NOTIFY = "notify"
CONF_ANNOUNCE = "announce"
CONF_NOTIFY_ENABLED = "notify_enabled"
CONF_NOTIFY_START = "notify_start"
CONF_NOTIFY_END = "notify_end"
CONF_ANNOUNCE_ENABLED = "announce_enabled"

CONF_MODULES = "modules"
CONF_ENABLED = "enabled"
CONF_PROVIDER = "provider"
CONF_INTERVAL = "interval"
CONF_NAME = "name"
CONF_TYPES = "types"
CONF_ITEMS = "items"
CONF_CUSTOM_URL = "custom_url"
CONF_TRACK_LOW = "track_low"
CONF_SYMBOLS = "symbols"
CONF_TRADING_ONLY = "trading_only"
CONF_FEEDS = "feeds"
CONF_LIMIT = "limit"
CONF_NOTIFY_LOW = "notify_low"
CONF_NOTIFY_CHANGE_PCT = "notify_change_pct"
CONF_NOTIFY_ON_CHANGE = "notify_on_change"
CONF_PREDICT_ENABLED = "predict_enabled"
CONF_SANJIN_NECKLACE = "sanjin_necklace"
CONF_SANJIN_BRACELET = "sanjin_bracelet"
CONF_SANJIN_RING = "sanjin_ring"

MODULE_LOTTERY = "lottery"
MODULE_METAL = "metal"
MODULE_STOCK = "stock"
MODULE_NEWS = "news"
MODULE_MEDIA = "media"

MODULES = (
    MODULE_LOTTERY,
    MODULE_METAL,
    MODULE_STOCK,
    MODULE_NEWS,
    MODULE_MEDIA,
)

PROVIDER_CWL = "cwl"
PROVIDER_HUANGJINJIAGE = "huangjinjiage"
PROVIDER_CUSTOM = "custom"
PROVIDER_SINA = "sina"
PROVIDER_TENCENT = "tencent"
PROVIDER_RSS = "rss"
PROVIDER_DOUBAN = "douban"
PROVIDER_NETEASE = "netease_toplist"

LOTTERY_SSQ = "ssq"
LOTTERY_3D = "3d"
LOTTERY_KL8 = "kl8"
LOTTERY_QLC = "qlc"
LOTTERY_TYPES = (LOTTERY_SSQ, LOTTERY_3D, LOTTERY_KL8, LOTTERY_QLC)

METAL_GOLD = "gold"
METAL_SILVER = "silver"
METAL_SHOP = "shop"
METAL_BANK = "bank"
METAL_ITEMS = (METAL_GOLD, METAL_SILVER, METAL_SHOP, METAL_BANK)

DEFAULT_NAME = "综合资讯"
DEFAULT_NOTIFY_ENABLED = True
DEFAULT_NOTIFY_START = "08:00:00"
DEFAULT_NOTIFY_END = "22:00:00"
DEFAULT_LOTTERY_INTERVAL = 5
DEFAULT_LOTTERY_PREDICT = True
DEFAULT_LOTTERY_HISTORY = 50
DEFAULT_METAL_INTERVAL = 1440
DEFAULT_SANJIN_NECKLACE = 15.0
DEFAULT_SANJIN_BRACELET = 25.0
DEFAULT_SANJIN_RING = 5.0
DEFAULT_NEWS_INTERVAL = 0
DEFAULT_STOCK_INTERVAL = 5
DEFAULT_STOCK_PEAK_INTERVAL = 1
DEFAULT_STOCK_ACTIVE_INTERVAL = 5
DEFAULT_MEDIA_INTERVAL = 720

# 新闻默认早晚各一次
NEWS_UPDATE_SLOTS = (
    (7, 30),
    (18, 30),
)

# A股关注：开盘/尾盘高峰，其余交易时段常规，午休与周末休眠
STOCK_SESSION_START = (9, 15)
STOCK_SESSION_END = (15, 0)
STOCK_PEAK_WINDOWS = (
    ((9, 15), (10, 0)),
    ((14, 30), (15, 0)),
)
STOCK_ACTIVE_WINDOWS = (
    ((10, 0), (11, 30)),
    ((13, 0), (14, 30)),
)

# 福彩开奖：weekday 周一=0 … 周日=6；开奖约 21:15
LOTTERY_DRAW_WEEKDAYS = {
    "ssq": (1, 3, 6),
    "3d": (0, 1, 2, 3, 4, 5, 6),
    "kl8": (0, 1, 2, 3, 4, 5, 6),
    "qlc": (0, 2, 4),
}
LOTTERY_DRAW_WINDOW_START = (21, 10)
LOTTERY_DRAW_WINDOW_END = (22, 30)
DEFAULT_NEWS_LIMIT = 10
DEFAULT_NEWS_FEEDS = [
    "https://www.ithome.com/rss/",
    "https://sspai.com/feed",
    "https://www.chinanews.com.cn/rss/scroll-news.xml",
]
DEFAULT_STOCK_CHANGE_PCT = 5.0

MANUFACTURER = "狂欢马克思"
