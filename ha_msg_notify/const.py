from homeassistant.const import Platform

DOMAIN = "ha_msg_notify"
MANUFACTURER = "狂欢马克思"

PLATFORMS = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BUTTON,
]

CONF_NAME = "name"
CONF_CHANNELS = "channels"
CONF_CHANNEL_ID = "channel_id"
CONF_CHANNEL_NAME = "channel_name"
CONF_CHANNEL_TYPE = "channel_type"
CONF_TARGET = "target"
CONF_ENABLED = "enabled"
CONF_ADD_TO_CAROUSEL = "add_to_carousel"
DEFAULT_ADD_TO_CAROUSEL = False

CONF_RESOURCE = "resource"
CONF_SECRET = "secret"
CONF_URL = "url"
CONF_COMMAND = "command"
CONF_METHOD = "method"
CONF_SERVER = "server"
CONF_PORT = "port"
CONF_TIMEOUT = "timeout"
CONF_SENDER = "sender"
CONF_ENCRYPTION = "encryption"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_RECIPIENT = "recipient"
CONF_SENDER_NAME = "sender_name"

CONF_CAROUSEL_INTERVAL = "carousel_interval"
CONF_CAROUSEL_ENABLED = "carousel_enabled"
CONF_MAX_MESSAGES = "max_messages"
CONF_MESSAGE_MODE = "message_mode"

CHANNEL_NOTIFY = "notify"
CHANNEL_WEWORK = "wework_robot"
CHANNEL_DINGTALK = "dingtalk"
CHANNEL_FEISHU = "feishu"
CHANNEL_SMTP = "smtp"
CHANNEL_REST = "rest_command"
CHANNEL_SHELL = "shell_command"
CHANNEL_ANNOUNCE = "announce"
CHANNEL_DISPLAY = "display"

WEBHOOK_CHANNELS = frozenset({CHANNEL_WEWORK, CHANNEL_DINGTALK, CHANNEL_FEISHU})
NOTIFY_SERVICE_CHANNELS = frozenset(
    {CHANNEL_WEWORK, CHANNEL_DINGTALK, CHANNEL_FEISHU, CHANNEL_SMTP}
)

WEBHOOK_URL_TEMPLATES = {
    CHANNEL_WEWORK: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}",
    CHANNEL_DINGTALK: "https://oapi.dingtalk.com/robot/send?access_token={key}",
    CHANNEL_FEISHU: "https://open.feishu.cn/open-apis/bot/v2/hook/{key}",
}


def build_webhook_url(channel_type: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        return value
    if value.startswith(("http://", "https://")):
        return value
    template = WEBHOOK_URL_TEMPLATES.get(channel_type)
    if not template:
        return value
    return template.format(key=value)

METHOD_GET = "get"
METHOD_POST = "post"
METHOD_PUT = "put"
METHOD_DELETE = "delete"
DEFAULT_REST_METHOD = METHOD_GET
DEFAULT_REST_TIMEOUT = 10

ENCRYPTION_STARTTLS = "starttls"
ENCRYPTION_TLS = "tls"
ENCRYPTION_NONE = "none"

MODE_APPEND = "append"
MODE_REPLACE = "replace"

DEFAULT_CAROUSEL_INTERVAL = 5
DEFAULT_CAROUSEL_ENABLED = True
DEFAULT_MAX_MESSAGES = 20
DEFAULT_MESSAGE_MODE = MODE_APPEND
DEFAULT_EMPTY_MESSAGE = "暂无消息"
DEFAULT_EMPTY_SOURCE = "系统"
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_TIMEOUT = 30
DEFAULT_SMTP_ENCRYPTION = ENCRYPTION_STARTTLS
DEFAULT_SENDER_NAME = "Home Assistant"

STORAGE_VERSION = 1

SERVICE_SEND = "send"
SERVICE_CAROUSEL = "carousel"
SERVICE_CLEAR = "clear"
SERVICE_REMOVE = "remove"
