from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.utils import formataddr
import hashlib
import hmac
import json
import logging
import smtplib
import time
from typing import Any
from urllib.parse import quote_plus

from aiohttp import ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.notify.const import ATTR_MESSAGE, ATTR_TITLE
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
import voluptuous as vol

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
    CONF_CHANNELS,
    CONF_COMMAND,
    CONF_ADD_TO_CAROUSEL,
    CONF_ENABLED,
    CONF_CHANNEL_TYPE,
    CONF_ENCRYPTION,
    CONF_MAX_MESSAGES,
    CONF_MESSAGE_MODE,
    CONF_METHOD,
    CONF_NAME,
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
    DEFAULT_EMPTY_MESSAGE,
    DEFAULT_EMPTY_SOURCE,
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
    MODE_REPLACE,
    NOTIFY_SERVICE_CHANNELS,
    STORAGE_VERSION,
    WEBHOOK_CHANNELS,
    build_webhook_url,
)

_LOGGER = logging.getLogger(__name__)
_NOTIFY_DOMAIN = "notify"
_REST_DOMAIN = "rest_command"
_SHELL_DOMAIN = "shell_command"
_NOTIFY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
    },
    extra=vol.ALLOW_EXTRA,
)
_ACTION_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


class MsgNotifyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN)
        self.hass = hass
        self.entry = entry
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}_{entry.entry_id}",
        )
        self._messages: list[dict[str, str]] = []
        self._index = 0
        self._unsub_carousel = None
        self._suppress_reload = 0
        self._channel_services: set[tuple[str, str]] = set()

    @property
    def instance_name(self) -> str:
        return self.entry.data.get(CONF_NAME) or self.entry.title

    @property
    def channels(self) -> list[dict[str, Any]]:
        return list(self.entry.options.get(CONF_CHANNELS) or [])

    @property
    def messages(self) -> list[dict[str, str]]:
        return list(self._messages)

    def cfg(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, default)

    def _sync_entry(self) -> None:
        entry = self.hass.config_entries.async_get_entry(self.entry.entry_id)
        if entry:
            self.entry = entry

    def channel_by_id(self, channel_id: str) -> dict[str, Any] | None:
        for channel in self.channels:
            if channel.get(CONF_CHANNEL_ID) == channel_id:
                return channel
        return None

    def enabled_channels(self, channel_ids: list[str] | None = None) -> list[dict[str, Any]]:
        selected = set(channel_ids) if channel_ids else None
        out: list[dict[str, Any]] = []
        for channel in self.channels:
            cid = channel.get(CONF_CHANNEL_ID)
            if not cid or not channel.get(CONF_ENABLED, True):
                continue
            if selected is not None and cid not in selected:
                continue
            out.append(channel)
        return out

    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._messages = list(stored.get("messages") or [])
        self._index = int(stored.get("index") or 0)
        self._refresh_data()
        self._schedule_carousel()
        self.async_sync_channel_services()

    async def async_shutdown(self) -> None:
        if self._unsub_carousel:
            self._unsub_carousel()
            self._unsub_carousel = None
        self.async_clear_channel_services()
        await self._persist()

    def _service_domain(self, channel_type: str) -> str | None:
        if channel_type in NOTIFY_SERVICE_CHANNELS:
            return _NOTIFY_DOMAIN
        if channel_type == CHANNEL_REST:
            return _REST_DOMAIN
        if channel_type == CHANNEL_SHELL:
            return _SHELL_DOMAIN
        return None

    def _wanted_channel_services(self) -> set[tuple[str, str]]:
        wanted: set[tuple[str, str]] = set()
        for channel in self.channels:
            cid = channel.get(CONF_CHANNEL_ID)
            ctype = channel.get(CONF_CHANNEL_TYPE)
            domain = self._service_domain(ctype or "")
            if cid and domain and channel.get(CONF_ENABLED, True):
                wanted.add((domain, cid))
        return wanted

    def _make_channel_handler(self, channel_id: str):
        async def _handle(call: ServiceCall) -> None:
            await self.async_send(
                title=call.data.get(ATTR_TITLE),
                message=call.data.get(ATTR_MESSAGE, ""),
                channels=[channel_id],
            )

        return _handle

    @callback
    def async_sync_channel_services(self) -> None:
        wanted = self._wanted_channel_services()
        for domain, service in list(self._channel_services):
            if (domain, service) not in wanted:
                if self.hass.services.has_service(domain, service):
                    self.hass.services.async_remove(domain, service)
                self._channel_services.discard((domain, service))
        for domain, service in wanted:
            if (domain, service) in self._channel_services:
                continue
            if self.hass.services.has_service(domain, service):
                _LOGGER.warning("%s.%s 已存在，跳过注册", domain, service)
                continue
            schema = _NOTIFY_SCHEMA if domain == _NOTIFY_DOMAIN else _ACTION_SCHEMA
            self.hass.services.async_register(
                domain,
                service,
                self._make_channel_handler(service),
                schema=schema,
            )
            self._channel_services.add((domain, service))

    @callback
    def async_clear_channel_services(self) -> None:
        for domain, service in list(self._channel_services):
            if self.hass.services.has_service(domain, service):
                self.hass.services.async_remove(domain, service)
            self._channel_services.discard((domain, service))

    # keep old names as aliases for callers
    def async_sync_notify_services(self) -> None:
        self.async_sync_channel_services()

    def async_clear_notify_services(self) -> None:
        self.async_clear_channel_services()

    async def _persist(self) -> None:
        await self._store.async_save(
            {"messages": self._messages, "index": self._index}
        )

    def _refresh_data(self) -> None:
        total = len(self._messages)
        if total == 0:
            self.async_set_updated_data(
                {
                    "current_message": DEFAULT_EMPTY_MESSAGE,
                    "current_source": DEFAULT_EMPTY_SOURCE,
                    "message_time": "",
                    "message_count": 0,
                    "messages": [],
                    "index": 0,
                }
            )
            return
        if self._index >= total:
            self._index = 0
        current = self._messages[self._index]
        self.async_set_updated_data(
            {
                "current_message": current.get("content") or DEFAULT_EMPTY_MESSAGE,
                "current_source": current.get("source") or DEFAULT_EMPTY_SOURCE,
                "message_time": current.get("timestamp") or "",
                "message_count": total,
                "messages": list(self._messages),
                "index": self._index,
            }
        )

    def _schedule_carousel(self) -> None:
        if self._unsub_carousel:
            self._unsub_carousel()
            self._unsub_carousel = None
        if not self.cfg(CONF_CAROUSEL_ENABLED, DEFAULT_CAROUSEL_ENABLED):
            return
        if len(self._messages) <= 1:
            return
        interval = int(self.cfg(CONF_CAROUSEL_INTERVAL, DEFAULT_CAROUSEL_INTERVAL))
        interval = max(interval, 1)
        self._unsub_carousel = async_track_point_in_time(
            self.hass,
            self._async_carousel_tick,
            dt_util.utcnow() + timedelta(seconds=interval),
        )

    @callback
    def _async_carousel_tick(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_advance_carousel())

    async def async_advance_carousel(self) -> None:
        if len(self._messages) <= 1:
            self._schedule_carousel()
            return
        self._index = (self._index + 1) % len(self._messages)
        self._refresh_data()
        await self._persist()
        self._schedule_carousel()

    async def async_add_message(self, content: str, source: str) -> None:
        item = {
            "content": content,
            "source": source or DEFAULT_EMPTY_SOURCE,
            "timestamp": dt_util.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        mode = self.cfg(CONF_MESSAGE_MODE, DEFAULT_MESSAGE_MODE)
        if mode == MODE_REPLACE:
            self._messages = [item]
            self._index = 0
        else:
            self._messages.append(item)
            max_messages = int(self.cfg(CONF_MAX_MESSAGES, DEFAULT_MAX_MESSAGES))
            if len(self._messages) > max_messages:
                overflow = len(self._messages) - max_messages
                self._messages = self._messages[overflow:]
            self._index = len(self._messages) - 1
        self._refresh_data()
        await self._persist()
        self._schedule_carousel()

    async def async_clear_messages(self) -> None:
        self._messages = []
        self._index = 0
        self._refresh_data()
        await self._persist()
        self._schedule_carousel()

    async def async_remove_message(self, index: int) -> None:
        if index < 0 or index >= len(self._messages):
            return
        self._messages.pop(index)
        if not self._messages:
            self._index = 0
        elif self._index > index:
            self._index -= 1
        elif self._index >= len(self._messages):
            self._index = 0
        self._refresh_data()
        await self._persist()
        self._schedule_carousel()

    async def async_send(
        self,
        *,
        title: str | None = None,
        message: str | None = None,
        channels: list[str] | None = None,
        carousel: bool = False,
        source: str | None = None,
        content: str | None = None,
    ) -> None:
        body = (message or content or "").replace("\\n", "\n")
        display_content = (content or message or title or "").replace("\\n", "\n")
        src = source or title or DEFAULT_EMPTY_SOURCE
        targets = self.enabled_channels(channels)
        add_carousel = carousel
        for channel in targets:
            await self._async_dispatch(channel, title, body, display_content)
            if channel.get(CONF_ADD_TO_CAROUSEL, DEFAULT_ADD_TO_CAROUSEL):
                add_carousel = True
        if add_carousel and display_content:
            await self.async_add_message(display_content, src)

    async def async_carousel(self, content: str, source: str | None = None) -> None:
        await self.async_add_message(
            content.replace("\\n", "\n"), source or DEFAULT_EMPTY_SOURCE
        )

    async def _async_dispatch(
        self,
        channel: dict[str, Any],
        title: str | None,
        message: str,
        display_content: str,
    ) -> None:
        channel_type = channel.get(CONF_CHANNEL_TYPE)
        try:
            if channel_type in WEBHOOK_CHANNELS:
                await self._async_send_webhook(channel, title, message)
            elif channel_type == CHANNEL_SMTP:
                await self._async_send_smtp(channel, title, message)
            elif channel_type == CHANNEL_REST:
                await self._async_send_rest(channel)
            elif channel_type == CHANNEL_SHELL:
                await self._async_send_shell(channel)
            elif channel_type == CHANNEL_NOTIFY:
                target = channel.get(CONF_TARGET)
                if target:
                    await self._async_send_notify(target, title, message)
            elif channel_type == CHANNEL_ANNOUNCE:
                target = channel.get(CONF_TARGET)
                text = display_content or message or title or ""
                if target and text:
                    await self._async_announce(target, text)
            elif channel_type == CHANNEL_DISPLAY:
                target = channel.get(CONF_TARGET)
                text = display_content or message or title or ""
                if target and text:
                    await self._async_display(target, text)
        except Exception:
            _LOGGER.exception(
                "channel dispatch failed: %s", channel.get(CONF_CHANNEL_ID)
            )

    async def _async_send_rest(self, channel: dict[str, Any]) -> None:
        url = (channel.get(CONF_URL) or "").strip()
        if not url:
            return
        method = str(channel.get(CONF_METHOD) or DEFAULT_REST_METHOD).lower()
        timeout = int(channel.get(CONF_TIMEOUT, DEFAULT_REST_TIMEOUT))
        session = async_get_clientsession(self.hass)
        async with session.request(
            method, url, timeout=ClientTimeout(total=timeout)
        ) as resp:
            if resp.status >= 400:
                body = await resp.text()
                _LOGGER.error(
                    "rest_command %s failed: %s %s",
                    channel.get(CONF_CHANNEL_ID),
                    resp.status,
                    body,
                )

    async def _async_send_shell(self, channel: dict[str, Any]) -> None:
        command = (channel.get(CONF_COMMAND) or "").strip()
        if not command:
            return
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await process.communicate()
        if process.returncode and process.returncode != 0:
            _LOGGER.error(
                "shell_command %s failed(%s): %s",
                channel.get(CONF_CHANNEL_ID),
                process.returncode,
                stderr.decode(errors="ignore"),
            )

    def _webhook_payload(
        self, channel_type: str, title: str | None, message: str
    ) -> dict[str, Any]:
        content = f"{title}\n{message}" if title else message
        if channel_type == CHANNEL_FEISHU:
            return {"msg_type": "text", "content": {"text": content}}
        return {"msgtype": "text", "text": {"content": content}}

    def _dingtalk_url(self, resource: str, secret: str) -> str:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        sign = quote_plus(base64.b64encode(digest))
        sep = "&" if "?" in resource else "?"
        return f"{resource}{sep}timestamp={timestamp}&sign={sign}"

    def _feishu_sign(self, secret: str) -> tuple[str, str]:
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{secret}"
        digest = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        return timestamp, base64.b64encode(digest).decode("utf-8")

    async def _async_send_webhook(
        self, channel: dict[str, Any], title: str | None, message: str
    ) -> None:
        resource = build_webhook_url(
            channel.get(CONF_CHANNEL_TYPE) or CHANNEL_WEWORK,
            channel.get(CONF_RESOURCE) or "",
        )
        if not resource:
            return
        channel_type = channel.get(CONF_CHANNEL_TYPE) or CHANNEL_WEWORK
        secret = (channel.get(CONF_SECRET) or "").strip()
        url = resource
        payload = self._webhook_payload(channel_type, title, message)
        if channel_type == CHANNEL_DINGTALK and secret:
            url = self._dingtalk_url(resource, secret)
        elif channel_type == CHANNEL_FEISHU and secret:
            timestamp, sign = self._feishu_sign(secret)
            payload["timestamp"] = timestamp
            payload["sign"] = sign
        session = async_get_clientsession(self.hass)
        async with session.post(url, json=payload) as resp:
            body = await resp.text()
            if resp.status >= 400:
                _LOGGER.error(
                    "%s webhook failed: %s %s", channel_type, resp.status, body
                )
                return
            try:
                result = json.loads(body) if body else {}
            except Exception:
                return
            if not isinstance(result, dict):
                return
            err = result.get("errcode", result.get("code"))
            if err not in (None, 0, "0"):
                _LOGGER.error("%s webhook error: %s", channel_type, result)

    async def _async_send_smtp(
        self, channel: dict[str, Any], title: str | None, message: str
    ) -> None:
        server = (channel.get(CONF_SERVER) or "").strip()
        sender = (channel.get(CONF_SENDER) or "").strip()
        recipients = _as_list(channel.get(CONF_RECIPIENT))
        if not server or not sender or not recipients:
            return
        port = int(channel.get(CONF_PORT, DEFAULT_SMTP_PORT))
        timeout = int(channel.get(CONF_TIMEOUT, DEFAULT_SMTP_TIMEOUT))
        encryption = channel.get(CONF_ENCRYPTION, DEFAULT_SMTP_ENCRYPTION)
        username = (channel.get(CONF_USERNAME) or "").strip()
        password = channel.get(CONF_PASSWORD) or ""
        sender_name = (channel.get(CONF_SENDER_NAME) or DEFAULT_SENDER_NAME).strip()

        mail = MIMEText(message or "", "plain", "utf-8")
        mail["Subject"] = title or ""
        mail["From"] = formataddr((sender_name, sender))
        mail["To"] = ", ".join(recipients)

        def _send() -> None:
            if encryption == ENCRYPTION_TLS:
                client: smtplib.SMTP = smtplib.SMTP_SSL(server, port, timeout=timeout)
            else:
                client = smtplib.SMTP(server, port, timeout=timeout)
                if encryption == ENCRYPTION_STARTTLS:
                    client.starttls()
                elif encryption != ENCRYPTION_NONE:
                    client.starttls()
            try:
                if username:
                    client.login(username, password)
                client.sendmail(sender, recipients, mail.as_string())
            finally:
                client.quit()

        await self.hass.async_add_executor_job(_send)

    async def _async_send_notify(
        self, target: str, title: str | None, message: str
    ) -> None:
        action = target if "." in target else f"notify.{target}"
        domain, service = action.split(".", 1)
        data: dict[str, Any] = {"message": message}
        if title:
            data["title"] = title
        if self.hass.services.has_service(domain, service):
            await self.hass.services.async_call(
                domain, service, data, blocking=False
            )
        elif domain == "notify" and self.hass.states.get(action):
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": action, "title": title or "", "message": message},
                blocking=False,
            )

    async def _async_announce(self, target: str | list[str], message: str) -> None:
        players = _as_list(target)
        if self.hass.services.has_service("xiaomi_miot", "intelligent_speaker"):
            for player in players:
                await self.hass.services.async_call(
                    "xiaomi_miot",
                    "intelligent_speaker",
                    {"entity_id": player, "text": message},
                    blocking=False,
                )
            return
        tts_ids = self.hass.states.async_entity_ids("tts")
        if tts_ids and self.hass.services.has_service("tts", "speak"):
            for player in players:
                await self.hass.services.async_call(
                    "tts",
                    "speak",
                    {"media_player_entity_id": player, "message": message},
                    target={"entity_id": tts_ids[0]},
                    blocking=False,
                )

    async def _async_display(self, target: str | list[str], message: str) -> None:
        entity_id = _as_list(target)[0] if isinstance(target, list) else target
        if not entity_id:
            return
        domain = entity_id.split(".", 1)[0]
        if domain == "text":
            await self.hass.services.async_call(
                "text",
                "set_value",
                {"entity_id": entity_id, "value": message},
                blocking=False,
            )
        elif domain == "input_text":
            await self.hass.services.async_call(
                "input_text",
                "set_value",
                {"entity_id": entity_id, "value": message},
                blocking=False,
            )

    async def async_set_channel_enabled(self, channel_id: str, enabled: bool) -> None:
        channels = []
        changed = False
        for channel in self.channels:
            item = dict(channel)
            if item.get(CONF_CHANNEL_ID) == channel_id:
                item[CONF_ENABLED] = enabled
                changed = True
            channels.append(item)
        if not changed:
            return
        options = {**self.entry.options, CONF_CHANNELS: channels}
        self._suppress_reload += 1
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self._sync_entry()
        self.async_sync_notify_services()
        self._refresh_data()

    async def async_update_option(self, key: str, value: Any) -> None:
        options = {**self.entry.options, key: value}
        self._suppress_reload += 1
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self._sync_entry()
        if key in (CONF_CAROUSEL_INTERVAL, CONF_CAROUSEL_ENABLED):
            self._schedule_carousel()
