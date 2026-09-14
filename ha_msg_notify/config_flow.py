from __future__ import annotations

from copy import deepcopy
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)
from homeassistant.util import slugify

from .const import (
    CHANNEL_ANNOUNCE,
    CHANNEL_DINGTALK,
    CHANNEL_DISPLAY,
    CHANNEL_FEISHU,
    CHANNEL_NOTIFY,
    CHANNEL_REST,
    CHANNEL_SHELL,
    CHANNEL_SMTP,
    CHANNEL_WEWORK,
    CONF_CAROUSEL_ENABLED,
    CONF_CAROUSEL_INTERVAL,
    CONF_CHANNEL_ID,
    CONF_CHANNEL_NAME,
    CONF_CHANNEL_TYPE,
    CONF_CHANNELS,
    CONF_COMMAND,
    CONF_ADD_TO_CAROUSEL,
    CONF_ENABLED,
    CONF_ENCRYPTION,
    CONF_MAX_MESSAGES,
    CONF_MESSAGE_MODE,
    CONF_METHOD,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_RECIPIENT,
    CONF_RESOURCE,
    CONF_SECRET,
    CONF_SENDER,
    CONF_SENDER_NAME,
    CONF_SERVER,
    CONF_TARGET,
    CONF_TIMEOUT,
    CONF_URL,
    CONF_USERNAME,
    DEFAULT_ADD_TO_CAROUSEL,
    DEFAULT_CAROUSEL_ENABLED,
    DEFAULT_CAROUSEL_INTERVAL,
    DEFAULT_MAX_MESSAGES,
    DEFAULT_MESSAGE_MODE,
    DEFAULT_REST_METHOD,
    DEFAULT_REST_TIMEOUT,
    DEFAULT_SENDER_NAME,
    DEFAULT_SMTP_ENCRYPTION,
    DEFAULT_SMTP_PORT,
    DEFAULT_SMTP_TIMEOUT,
    DOMAIN,
    ENCRYPTION_NONE,
    ENCRYPTION_STARTTLS,
    ENCRYPTION_TLS,
    METHOD_DELETE,
    METHOD_GET,
    METHOD_POST,
    METHOD_PUT,
    MODE_APPEND,
    MODE_REPLACE,
    WEBHOOK_CHANNELS,
    build_webhook_url,
)
from .coordinator import MsgNotifyCoordinator
from .localize import selector_options, tr

_CHANNEL_TYPES = [
    CHANNEL_WEWORK,
    CHANNEL_DINGTALK,
    CHANNEL_FEISHU,
    CHANNEL_SMTP,
    CHANNEL_REST,
    CHANNEL_SHELL,
    CHANNEL_NOTIFY,
    CHANNEL_ANNOUNCE,
    CHANNEL_DISPLAY,
]
_MESSAGE_MODES = [MODE_APPEND, MODE_REPLACE]
_ENCRYPTIONS = [ENCRYPTION_STARTTLS, ENCRYPTION_TLS, ENCRYPTION_NONE]
_REST_METHODS = [METHOD_GET, METHOD_POST, METHOD_PUT, METHOD_DELETE]
_SLUG_RE = re.compile(r"^[a-z0-9_]+$")


def _select(hass: HomeAssistant | None, key: str, values: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=selector_options(hass, key, values),
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _get(src: dict, key: str, default: Any) -> Any:
    if key in src and src[key] not in (None, ""):
        return src[key]
    return default


def _notify_options(hass: HomeAssistant | None) -> list[str]:
    names: set[str] = set()
    if hass:
        for name in hass.services.async_services().get("notify", {}):
            if name != "send_message":
                names.add(f"notify.{name}")
        names.update(hass.states.async_entity_ids("notify"))
    return sorted(names)


def _global_fields(hass: HomeAssistant | None = None) -> dict[Any, Any]:
    return {
        vol.Required(CONF_NAME): TextSelector(),
        vol.Required(CONF_CAROUSEL_INTERVAL): NumberSelector(
            NumberSelectorConfig(min=1, max=3600, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_CAROUSEL_ENABLED): BooleanSelector(),
        vol.Required(CONF_MAX_MESSAGES): NumberSelector(
            NumberSelectorConfig(min=1, max=100, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_MESSAGE_MODE): _select(hass, "message_mode", _MESSAGE_MODES),
    }


def _global_values(defaults: dict[str, Any], hass: Any = None) -> dict[str, Any]:
    return {
        CONF_NAME: _get(defaults, CONF_NAME, tr(hass, "default_name") if hass else "通知管理"),
        CONF_CAROUSEL_INTERVAL: _get(
            defaults, CONF_CAROUSEL_INTERVAL, DEFAULT_CAROUSEL_INTERVAL
        ),
        CONF_CAROUSEL_ENABLED: _get(
            defaults, CONF_CAROUSEL_ENABLED, DEFAULT_CAROUSEL_ENABLED
        ),
        CONF_MAX_MESSAGES: _get(defaults, CONF_MAX_MESSAGES, DEFAULT_MAX_MESSAGES),
        CONF_MESSAGE_MODE: _get(defaults, CONF_MESSAGE_MODE, DEFAULT_MESSAGE_MODE),
    }


def _global_options(src: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = existing or {}
    return {
        CONF_CAROUSEL_INTERVAL: int(
            src.get(CONF_CAROUSEL_INTERVAL, existing.get(CONF_CAROUSEL_INTERVAL, DEFAULT_CAROUSEL_INTERVAL))
        ),
        CONF_CAROUSEL_ENABLED: bool(
            src.get(CONF_CAROUSEL_ENABLED, existing.get(CONF_CAROUSEL_ENABLED, DEFAULT_CAROUSEL_ENABLED))
        ),
        CONF_MAX_MESSAGES: int(
            src.get(CONF_MAX_MESSAGES, existing.get(CONF_MAX_MESSAGES, DEFAULT_MAX_MESSAGES))
        ),
        CONF_MESSAGE_MODE: src.get(
            CONF_MESSAGE_MODE, existing.get(CONF_MESSAGE_MODE, DEFAULT_MESSAGE_MODE)
        ),
    }


def _target_selector(channel_type: str, hass: HomeAssistant | None) -> Any:
    if channel_type == CHANNEL_NOTIFY:
        return SelectSelector(
            SelectSelectorConfig(
                options=_notify_options(hass),
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    if channel_type == CHANNEL_ANNOUNCE:
        return EntitySelector(
            EntitySelectorConfig(domain="media_player", multiple=True)
        )
    return EntitySelector(
        EntitySelectorConfig(domain=["text", "input_text"])
    )


def _channel_base_fields(hass: HomeAssistant | None = None) -> dict[Any, Any]:
    return {
        vol.Required(CONF_CHANNEL_NAME): TextSelector(),
        vol.Required(CONF_CHANNEL_ID): TextSelector(TextSelectorConfig(type="text")),
        vol.Required(CONF_CHANNEL_TYPE): _select(hass, "channel_type", _CHANNEL_TYPES),
        vol.Required(CONF_ENABLED): BooleanSelector(),
        vol.Required(CONF_ADD_TO_CAROUSEL): BooleanSelector(),
    }


def _extract_webhook_key(channel_type: str, resource: str) -> str:
    resource = (resource or "").strip()
    if not resource:
        return resource
    if not resource.startswith(("http://", "https://")):
        return resource
    parsed = urlparse(resource)
    query = parse_qs(parsed.query)
    if channel_type == CHANNEL_WEWORK:
        keys = query.get("key") or []
        if keys:
            return keys[0]
    elif channel_type == CHANNEL_DINGTALK:
        tokens = query.get("access_token") or []
        if tokens:
            return tokens[0]
    elif channel_type == CHANNEL_FEISHU:
        marker = "/hook/"
        if marker in parsed.path:
            return parsed.path.split(marker, 1)[1].strip("/")
    return ""


def _channel_config_fields(
    channel_type: str, hass: HomeAssistant | None = None
) -> dict[Any, Any]:
    if channel_type in WEBHOOK_CHANNELS:
        fields: dict[Any, Any] = {
            vol.Required(CONF_RESOURCE): TextSelector(
                TextSelectorConfig(type="password")
            ),
        }
        if channel_type in (CHANNEL_DINGTALK, CHANNEL_FEISHU):
            fields[vol.Optional(CONF_SECRET)] = TextSelector(
                TextSelectorConfig(type="password")
            )
        return fields
    if channel_type == CHANNEL_REST:
        return {
            vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type="url")),
            vol.Required(CONF_METHOD, default=DEFAULT_REST_METHOD): _select(
                hass, "method", _REST_METHODS
            ),
            vol.Required(CONF_TIMEOUT, default=DEFAULT_REST_TIMEOUT): NumberSelector(
                NumberSelectorConfig(min=1, max=300, step=1, mode=NumberSelectorMode.BOX)
            ),
        }
    if channel_type == CHANNEL_SHELL:
        return {
            vol.Required(CONF_COMMAND): TextSelector(
                TextSelectorConfig(multiline=True)
            ),
        }
    if channel_type == CHANNEL_SMTP:
        return {
            vol.Required(CONF_SERVER): TextSelector(),
            vol.Required(CONF_PORT): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_TIMEOUT): NumberSelector(
                NumberSelectorConfig(min=1, max=300, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(CONF_SENDER): TextSelector(TextSelectorConfig(type="email")),
            vol.Required(CONF_ENCRYPTION): _select(hass, "encryption", _ENCRYPTIONS),
            vol.Required(CONF_USERNAME): TextSelector(),
            vol.Required(CONF_PASSWORD): TextSelector(TextSelectorConfig(type="password")),
            vol.Required(CONF_RECIPIENT): TextSelector(
                TextSelectorConfig(multiple=True, type="email")
            ),
            vol.Optional(CONF_SENDER_NAME, default=DEFAULT_SENDER_NAME): TextSelector(),
        }
    return {
        vol.Required(CONF_TARGET): _target_selector(channel_type, hass),
    }


def _channel_base_values(defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults = defaults or {}
    values: dict[str, Any] = {
        CONF_CHANNEL_TYPE: _get(defaults, CONF_CHANNEL_TYPE, CHANNEL_WEWORK),
        CONF_ENABLED: _get(defaults, CONF_ENABLED, True),
        CONF_ADD_TO_CAROUSEL: _get(
            defaults, CONF_ADD_TO_CAROUSEL, DEFAULT_ADD_TO_CAROUSEL
        ),
    }
    for key in (CONF_CHANNEL_NAME, CONF_CHANNEL_ID):
        val = _get(defaults, key, None)
        if val is not None:
            values[key] = val
    return values


def _channel_config_values(
    channel_type: str, defaults: dict[str, Any] | None = None
) -> dict[str, Any]:
    defaults = defaults or {}
    if channel_type in WEBHOOK_CHANNELS:
        values: dict[str, Any] = {}
        resource = _get(defaults, CONF_RESOURCE, None)
        if resource is not None:
            values[CONF_RESOURCE] = _extract_webhook_key(channel_type, str(resource))
        secret = _get(defaults, CONF_SECRET, None)
        if secret is not None:
            values[CONF_SECRET] = secret
        return values
    if channel_type == CHANNEL_REST:
        values = {
            CONF_METHOD: _get(defaults, CONF_METHOD, DEFAULT_REST_METHOD),
            CONF_TIMEOUT: int(_get(defaults, CONF_TIMEOUT, DEFAULT_REST_TIMEOUT)),
        }
        val = _get(defaults, CONF_URL, None)
        if val is not None:
            values[CONF_URL] = val
        return values
    if channel_type == CHANNEL_SHELL:
        values = {}
        val = _get(defaults, CONF_COMMAND, None)
        if val is not None:
            values[CONF_COMMAND] = val
        return values
    if channel_type == CHANNEL_SMTP:
        values = {
            CONF_PORT: int(_get(defaults, CONF_PORT, DEFAULT_SMTP_PORT)),
            CONF_TIMEOUT: int(_get(defaults, CONF_TIMEOUT, DEFAULT_SMTP_TIMEOUT)),
            CONF_ENCRYPTION: _get(defaults, CONF_ENCRYPTION, DEFAULT_SMTP_ENCRYPTION),
            CONF_SENDER_NAME: _get(defaults, CONF_SENDER_NAME, DEFAULT_SENDER_NAME),
        }
        for key in (
            CONF_SERVER,
            CONF_SENDER,
            CONF_USERNAME,
            CONF_PASSWORD,
            CONF_RECIPIENT,
        ):
            val = _get(defaults, key, None)
            if val is not None:
                values[key] = val
        return values
    values = {}
    val = _get(defaults, CONF_TARGET, None)
    if val is not None:
        values[CONF_TARGET] = val
    return values


def _valid_channel_id(value: str) -> bool:
    return bool(_SLUG_RE.match(value))


def _message_label(index: int, msg: dict[str, Any]) -> str:
    source = str(msg.get("source") or "").strip()
    timestamp = str(msg.get("timestamp") or "").strip()
    text = f"{source}{timestamp}" if source or timestamp else ""
    return f"[{index}] {text}" if text else f"[{index}]"


def _normalize_recipients(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,;\s]+", value.strip())
        return [p for p in parts if p]
    return [str(v).strip() for v in value if str(v).strip()]


def _normalize_channel(base: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config or {}
    src = {**base, **config}
    channel_id = slugify(str(src[CONF_CHANNEL_ID]).strip()) or str(src[CONF_CHANNEL_ID]).strip()
    channel_type = src[CONF_CHANNEL_TYPE]
    channel: dict[str, Any] = {
        CONF_CHANNEL_ID: channel_id,
        CONF_CHANNEL_NAME: str(src[CONF_CHANNEL_NAME]).strip(),
        CONF_CHANNEL_TYPE: channel_type,
        CONF_ENABLED: bool(src.get(CONF_ENABLED, True)),
        CONF_ADD_TO_CAROUSEL: bool(
            src.get(CONF_ADD_TO_CAROUSEL, DEFAULT_ADD_TO_CAROUSEL)
        ),
    }
    if channel_type in WEBHOOK_CHANNELS:
        resource = str((config or {}).get(CONF_RESOURCE) or "").strip()
        if not resource:
            resource = str(base.get(CONF_RESOURCE) or "").strip()
        channel[CONF_RESOURCE] = build_webhook_url(channel_type, resource)
        if channel_type in (CHANNEL_DINGTALK, CHANNEL_FEISHU):
            secret = str((config or {}).get(CONF_SECRET) or "").strip()
            if not secret:
                secret = str(base.get(CONF_SECRET) or "").strip()
            if secret:
                channel[CONF_SECRET] = secret
    elif channel_type == CHANNEL_REST:
        channel[CONF_URL] = str(src.get(CONF_URL) or "").strip()
        channel[CONF_METHOD] = str(
            src.get(CONF_METHOD) or DEFAULT_REST_METHOD
        ).lower()
        channel[CONF_TIMEOUT] = int(src.get(CONF_TIMEOUT, DEFAULT_REST_TIMEOUT))
    elif channel_type == CHANNEL_SHELL:
        channel[CONF_COMMAND] = str(src.get(CONF_COMMAND) or "").strip()
    elif channel_type == CHANNEL_SMTP:
        channel[CONF_SERVER] = str(src.get(CONF_SERVER) or "").strip()
        channel[CONF_PORT] = int(src.get(CONF_PORT, DEFAULT_SMTP_PORT))
        channel[CONF_TIMEOUT] = int(src.get(CONF_TIMEOUT, DEFAULT_SMTP_TIMEOUT))
        channel[CONF_SENDER] = str(src.get(CONF_SENDER) or "").strip()
        channel[CONF_ENCRYPTION] = src.get(CONF_ENCRYPTION, DEFAULT_SMTP_ENCRYPTION)
        channel[CONF_USERNAME] = str(src.get(CONF_USERNAME) or "").strip()
        channel[CONF_PASSWORD] = str(src.get(CONF_PASSWORD) or "")
        channel[CONF_RECIPIENT] = _normalize_recipients(src.get(CONF_RECIPIENT))
        channel[CONF_SENDER_NAME] = str(
            src.get(CONF_SENDER_NAME) or DEFAULT_SENDER_NAME
        ).strip()
    else:
        target = src.get(CONF_TARGET)
        if isinstance(target, list):
            target = target[0] if len(target) == 1 else target
        channel[CONF_TARGET] = target
    return channel


class MsgNotifyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._global: dict[str, Any] = {}
        self._channels: list[dict[str, Any]] = []
        self._pending: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_global_fields(self.hass)),
                    _global_values({}, self.hass),
                ),
            )
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self._global = {CONF_NAME: user_input[CONF_NAME], **_global_options(user_input)}
        return await self.async_step_channel()

    async def async_step_channel(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="channel",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_channel_base_fields(self.hass)),
                    _channel_base_values(),
                ),
            )
        channel_id = slugify(str(user_input[CONF_CHANNEL_ID]).strip()) or str(
            user_input[CONF_CHANNEL_ID]
        ).strip()
        if not _valid_channel_id(channel_id):
            errors[CONF_CHANNEL_ID] = "invalid_channel_id"
        ids = {c[CONF_CHANNEL_ID] for c in self._channels}
        if channel_id in ids:
            errors[CONF_CHANNEL_ID] = "already_channel"
        if errors:
            return self.async_show_form(
                step_id="channel",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_channel_base_fields(self.hass)),
                    user_input,
                ),
                errors=errors,
            )
        self._pending = dict(user_input)
        return await self.async_step_channel_config()

    async def async_step_channel_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        channel_type = self._pending[CONF_CHANNEL_TYPE]
        if user_input is None:
            return self.async_show_form(
                step_id="channel_config",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_channel_config_fields(channel_type, self.hass)),
                    _channel_config_values(channel_type),
                ),
            )
        channel = _normalize_channel(self._pending, user_input)
        self._channels.append(channel)
        return self.async_create_entry(
            title=self._global[CONF_NAME],
            data={CONF_NAME: self._global[CONF_NAME]},
            options={
                **{k: v for k, v in self._global.items() if k != CONF_NAME},
                CONF_CHANNELS: self._channels,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return MsgNotifyOptionsFlow()


class MsgNotifyOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._edit_id: str | None = None
        self._pending: dict[str, Any] = {}

    def _entry_fallback(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "carousel",
                "add_channel",
                "edit_channel",
                "remove_channel",
                "remove_message",
            ],
        )

    def _coordinator(self) -> MsgNotifyCoordinator | None:
        data = (self.hass.data.get(DOMAIN) or {}).get(self.config_entry.entry_id)
        return data.get("coordinator") if data else None

    async def async_step_carousel(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = self._entry_fallback()
        if user_input is not None:
            options = {**self.config_entry.options}
            options.update(_global_options(user_input, self.config_entry.options))
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="carousel",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_CAROUSEL_INTERVAL): NumberSelector(
                            NumberSelectorConfig(
                                min=1, max=3600, step=1, mode=NumberSelectorMode.BOX
                            )
                        ),
                        vol.Required(CONF_CAROUSEL_ENABLED): BooleanSelector(),
                        vol.Required(CONF_MAX_MESSAGES): NumberSelector(
                            NumberSelectorConfig(
                                min=1, max=100, step=1, mode=NumberSelectorMode.BOX
                            )
                        ),
                        vol.Required(CONF_MESSAGE_MODE): _select(
                            self.hass, "message_mode", _MESSAGE_MODES
                        ),
                    }
                ),
                {
                    CONF_CAROUSEL_INTERVAL: _get(
                        current, CONF_CAROUSEL_INTERVAL, DEFAULT_CAROUSEL_INTERVAL
                    ),
                    CONF_CAROUSEL_ENABLED: _get(
                        current, CONF_CAROUSEL_ENABLED, DEFAULT_CAROUSEL_ENABLED
                    ),
                    CONF_MAX_MESSAGES: _get(
                        current, CONF_MAX_MESSAGES, DEFAULT_MAX_MESSAGES
                    ),
                    CONF_MESSAGE_MODE: _get(
                        current, CONF_MESSAGE_MODE, DEFAULT_MESSAGE_MODE
                    ),
                },
            ),
        )

    async def async_step_add_channel(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="add_channel",
                data_schema=vol.Schema(_channel_base_fields(self.hass)),
            )
        channel_id = slugify(str(user_input[CONF_CHANNEL_ID]).strip()) or str(
            user_input[CONF_CHANNEL_ID]
        ).strip()
        channels = list(self.config_entry.options.get(CONF_CHANNELS) or [])
        if not _valid_channel_id(channel_id):
            errors[CONF_CHANNEL_ID] = "invalid_channel_id"
        if channel_id in {c.get(CONF_CHANNEL_ID) for c in channels}:
            errors[CONF_CHANNEL_ID] = "already_channel"
        if errors:
            return self.async_show_form(
                step_id="add_channel",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_channel_base_fields(self.hass)),
                    user_input,
                ),
                errors=errors,
            )
        self._pending = dict(user_input)
        return await self.async_step_add_channel_config()

    async def async_step_add_channel_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        channel_type = self._pending[CONF_CHANNEL_TYPE]
        if user_input is None:
            return self.async_show_form(
                step_id="add_channel_config",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_channel_config_fields(channel_type, self.hass)),
                    _channel_config_values(channel_type),
                ),
            )
        channel = _normalize_channel(self._pending, user_input)
        channels = list(self.config_entry.options.get(CONF_CHANNELS) or [])
        channels.append(channel)
        options = {**self.config_entry.options, CONF_CHANNELS: channels}
        return self.async_create_entry(title="", data=options)

    async def async_step_edit_channel(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        channels = list(self.config_entry.options.get(CONF_CHANNELS) or [])
        if not channels:
            return self.async_abort(reason="no_channels")
        if user_input is None:
            options = [
                {
                    "value": c[CONF_CHANNEL_ID],
                    "label": c.get(CONF_CHANNEL_NAME) or c[CONF_CHANNEL_ID],
                }
                for c in channels
            ]
            return self.async_show_form(
                step_id="edit_channel",
                data_schema=vol.Schema(
                    {
                        vol.Required("channel"): SelectSelector(
                            SelectSelectorConfig(options=options)
                        )
                    }
                ),
            )
        self._edit_id = user_input["channel"]
        current = next(
            (c for c in channels if c.get(CONF_CHANNEL_ID) == self._edit_id), {}
        )
        return self.async_show_form(
            step_id="edit_form",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_channel_base_fields(self.hass)),
                _channel_base_values(current),
            ),
        )

    async def async_step_edit_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        channels = list(self.config_entry.options.get(CONF_CHANNELS) or [])
        current = next(
            (c for c in channels if c.get(CONF_CHANNEL_ID) == self._edit_id), {}
        )
        if user_input is None:
            if not current:
                return await self.async_step_edit_channel()
            return self.async_show_form(
                step_id="edit_form",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_channel_base_fields(self.hass)),
                    _channel_base_values(current),
                ),
            )
        errors: dict[str, str] = {}
        channel_id = slugify(str(user_input[CONF_CHANNEL_ID]).strip()) or str(
            user_input[CONF_CHANNEL_ID]
        ).strip()
        others = {
            c.get(CONF_CHANNEL_ID)
            for c in channels
            if c.get(CONF_CHANNEL_ID) != self._edit_id
        }
        if not _valid_channel_id(channel_id):
            errors[CONF_CHANNEL_ID] = "invalid_channel_id"
        if channel_id in others:
            errors[CONF_CHANNEL_ID] = "already_channel"
        if errors:
            return self.async_show_form(
                step_id="edit_form",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_channel_base_fields(self.hass)),
                    user_input,
                ),
                errors=errors,
            )
        self._pending = {**current, **user_input}
        return await self.async_step_edit_channel_config()

    async def async_step_edit_channel_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        channel_type = self._pending[CONF_CHANNEL_TYPE]
        if user_input is None:
            return self.async_show_form(
                step_id="edit_channel_config",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(_channel_config_fields(channel_type, self.hass)),
                    _channel_config_values(channel_type, self._pending),
                ),
            )
        channel = _normalize_channel(self._pending, user_input)
        channels = list(self.config_entry.options.get(CONF_CHANNELS) or [])
        updated = []
        for item in channels:
            if item.get(CONF_CHANNEL_ID) == self._edit_id:
                updated.append(channel)
            else:
                updated.append(item)
        options = {**self.config_entry.options, CONF_CHANNELS: updated}
        return self.async_create_entry(title="", data=options)

    async def async_step_remove_channel(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        channels = list(self.config_entry.options.get(CONF_CHANNELS) or [])
        if not channels:
            return self.async_abort(reason="no_channels")
        if user_input is not None:
            cid = user_input["channel"]
            channels = [c for c in channels if c.get(CONF_CHANNEL_ID) != cid]
            options = deepcopy(dict(self.config_entry.options))
            options[CONF_CHANNELS] = channels
            return self.async_create_entry(title="", data=options)
        options = [
            {
                "value": c[CONF_CHANNEL_ID],
                "label": c.get(CONF_CHANNEL_NAME) or c[CONF_CHANNEL_ID],
            }
            for c in channels
        ]
        return self.async_show_form(
            step_id="remove_channel",
            data_schema=vol.Schema(
                {
                    vol.Required("channel"): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_remove_message(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        coordinator = self._coordinator()
        messages = coordinator.messages if coordinator else []
        if not messages:
            return self.async_abort(reason="no_messages")
        if user_input is not None:
            await coordinator.async_remove_message(int(user_input["message"]))
            return self.async_create_entry(
                title="", data=dict(self.config_entry.options)
            )
        options = [
            {"value": str(i), "label": _message_label(i, msg)}
            for i, msg in enumerate(messages)
        ]
        return self.async_show_form(
            step_id="remove_message",
            data_schema=vol.Schema(
                {
                    vol.Required("message"): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )
