from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .advanced_notify import (
    build_festival_lookup,
    format_notify_messages,
    match_notify_rules,
)
from .ai_fortune import fetch_ai_fortune
from .const import (
    CONF_AI_API_KEY,
    CONF_AI_ENABLED,
    CONF_AI_MODEL,
    CONF_BIRTHDAYS,
    CONF_HOLIDAY_AUTO,
    CONF_LANGUAGE,
    CONF_NOTIFY,
    CONF_NOTIFY_CALENDAR,
    CONF_NOTIFY_CALENDAR_TIME,
    CONF_NOTIFY_FESTIVAL,
    CONF_NOTIFY_FESTIVAL_TIME,
    CONF_NOTIFY_LICENSE,
    CONF_NOTIFY_LICENSE_TIME,
    CONF_NOTIFY_MEMORIAL,
    CONF_NOTIFY_MEMORIAL_TIME,
    CONF_NOTIFY_RULES,
    CONF_NOTIFY_RULES_ENABLED,
    DEFAULT_AI_ENABLED,
    DEFAULT_AI_MODEL,
    DEFAULT_HOLIDAY_AUTO,
    DEFAULT_LANGUAGE,
    DEFAULT_NOTIFY_CALENDAR,
    DEFAULT_NOTIFY_CALENDAR_TIME,
    DEFAULT_NOTIFY_FESTIVAL,
    DEFAULT_NOTIFY_FESTIVAL_TIME,
    DEFAULT_NOTIFY_LICENSE,
    DEFAULT_NOTIFY_LICENSE_TIME,
    DEFAULT_NOTIFY_MEMORIAL,
    DEFAULT_NOTIFY_MEMORIAL_TIME,
    DEFAULT_NOTIFY_RULES,
    DEFAULT_NOTIFY_RULES_ENABLED,
    DOMAIN,
)
from .festival_engine import compute, format_merged_notify
from .holiday_provider import HolidayProvider
from .text_util import convert_obj, convert_text

_LOGGER = logging.getLogger(__name__)

_INVALID_MSG = frozenset({"", "unknown", "unavailable", "none", "null"})


def _parse_hm(raw: Any, default: str) -> tuple[int, int]:
    text = str(raw or default)
    parts = text.split(":")
    try:
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        dparts = default.split(":")
        return int(dparts[0]), int(dparts[1])


def _valid_message(text: Any) -> str | None:
    if text is None:
        return None
    body = str(text).replace("\\n", "\n").strip()
    if not body or body.lower() in _INVALID_MSG:
        return None
    return body


def _next_birthday_item(opts: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
    birthdays = opts.get(CONF_BIRTHDAYS) or []
    if not isinstance(birthdays, list) or not birthdays:
        return None
    for row in data.get("today") or []:
        if isinstance(row, dict) and row.get("category") == "birthday" and row.get("todayName"):
            for item in birthdays:
                if isinstance(item, dict) and item.get("name") == row.get("todayName"):
                    return item
            break
    next_name = ((data.get("next_by_category") or {}).get("birthday") or {}).get("name")
    if next_name:
        for item in birthdays:
            if isinstance(item, dict) and item.get("name") == next_name:
                return item
    for item in birthdays:
        if isinstance(item, dict) and item.get("name"):
            return item
    return None


class HolidayDailyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(hours=1))
        self.entry = entry
        self._unsub_time = None
        self._last_notify_day: str | None = None
        self._last_ai_day: str | None = None
        self._notify_lock = asyncio.Lock()
        self.tap_date = dt_util.now().date()
        self.holiday_provider = HolidayProvider(
            fetch_enabled=bool(
                {**entry.data, **entry.options}.get(
                    CONF_HOLIDAY_AUTO, DEFAULT_HOLIDAY_AUTO
                )
            )
        )

    @property
    def options(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    def set_tap_date(self, value) -> None:
        self.tap_date = value

    async def async_setup(self) -> None:
        await self.holiday_provider.async_update(self.hass)
        await self.async_config_entry_first_refresh()
        self._unsub_time = async_track_time_change(
            self.hass, self._on_minute, second=0
        )

    async def async_shutdown(self) -> None:
        if self._unsub_time:
            self._unsub_time()
            self._unsub_time = None

    async def _async_update_data(self) -> dict[str, Any]:
        opts = self.options
        self.holiday_provider = HolidayProvider(
            fetch_enabled=bool(opts.get(CONF_HOLIDAY_AUTO, DEFAULT_HOLIDAY_AUTO))
        )
        await self.holiday_provider.async_update(self.hass)
        today = dt_util.now().date()
        tap = self.tap_date or today
        result = await self.hass.async_add_executor_job(
            lambda: compute(
                opts,
                today,
                holiday_provider=self.holiday_provider,
                tap_date=tap,
            )
        )
        result["ai_fortune"] = await self._maybe_fetch_ai(opts, result, today)
        pred = str((result.get("ai_fortune") or {}).get("prediction") or "").strip()
        if pred:
            ai_block = f"🔮AI运势\n{pred}"
            memorial = str(result.get("memorial_content") or "").rstrip()
            result["memorial_content"] = (
                f"{memorial}\n\n{ai_block}".strip() if memorial else ai_block
            )
            result["has_near_memorial"] = True
        language = str(opts.get(CONF_LANGUAGE) or DEFAULT_LANGUAGE)
        if language == "zh-Hant":
            result = convert_obj(result, language)
        return result

    async def _maybe_fetch_ai(
        self, opts: dict[str, Any], data: dict[str, Any], today
    ) -> dict[str, Any]:
        enabled = bool(opts.get(CONF_AI_ENABLED, DEFAULT_AI_ENABLED))
        day_key = today.isoformat()
        prev = (self.data or {}).get("ai_fortune") or {}
        model = opts.get(CONF_AI_MODEL, DEFAULT_AI_MODEL)
        if not enabled:
            return {
                "enabled": False,
                "prediction": "",
                "model": model,
                "person": "",
                "updated": "",
            }
        api_key = str(opts.get(CONF_AI_API_KEY) or "").strip()
        if not api_key:
            return {
                "enabled": True,
                "prediction": "",
                "model": model,
                "person": "",
                "updated": "",
            }
        if self._last_ai_day == day_key and prev.get("prediction"):
            return prev
        if self._last_ai_day == day_key:
            return prev or {
                "enabled": True,
                "prediction": "",
                "model": model,
                "person": "",
                "updated": "",
            }
        person = _next_birthday_item(opts, data)
        prediction = await fetch_ai_fortune(
            self.hass, opts, person, data.get("almanac") or {}
        )
        self._last_ai_day = day_key
        return {
            "enabled": True,
            "prediction": prediction,
            "model": model,
            "person": (person or {}).get("name") or "",
            "updated": day_key if prediction else "",
        }

    @callback
    def _on_minute(self, now: datetime) -> None:
        self.hass.async_create_task(self._async_tick(now))

    async def _async_tick(self, now: datetime) -> None:
        local = dt_util.as_local(now)
        if local.hour == 0 and local.minute == 5:
            await self.async_request_refresh()
        await self._maybe_notify(local)

    def _calendar_time(self, opts: dict[str, Any]) -> tuple[int, int]:
        return _parse_hm(
            opts.get(CONF_NOTIFY_CALENDAR_TIME), DEFAULT_NOTIFY_CALENDAR_TIME
        )

    def _festival_time(self, opts: dict[str, Any]) -> tuple[int, int]:
        return _parse_hm(
            opts.get(CONF_NOTIFY_FESTIVAL_TIME), DEFAULT_NOTIFY_FESTIVAL_TIME
        )

    def _license_time(self, opts: dict[str, Any]) -> tuple[int, int]:
        return _parse_hm(
            opts.get(CONF_NOTIFY_LICENSE_TIME), DEFAULT_NOTIFY_LICENSE_TIME
        )

    def _memorial_time(self, opts: dict[str, Any]) -> tuple[int, int]:
        raw = opts.get(CONF_NOTIFY_MEMORIAL_TIME)
        if raw in (None, ""):
            raw = opts.get("notify_birthday_time") or opts.get("notify_anniversary_time")
        return _parse_hm(raw, DEFAULT_NOTIFY_MEMORIAL_TIME)

    async def _maybe_notify(self, local: datetime) -> None:
        async with self._notify_lock:
            await self._maybe_notify_locked(local)

    def _memorial_on(self, opts: dict[str, Any]) -> bool:
        memorial_on = opts.get(CONF_NOTIFY_MEMORIAL)
        if memorial_on is None:
            memorial_on = opts.get("notify_birthday", DEFAULT_NOTIFY_MEMORIAL) or opts.get(
                "notify_anniversary", DEFAULT_NOTIFY_MEMORIAL
            )
        return bool(memorial_on)

    def _notify_slots(self, opts: dict[str, Any]) -> list[tuple[int, int]]:
        slots: list[tuple[int, int]] = []
        if bool(opts.get(CONF_NOTIFY_CALENDAR, DEFAULT_NOTIFY_CALENDAR)):
            slots.append(self._calendar_time(opts))
        if bool(opts.get(CONF_NOTIFY_FESTIVAL, DEFAULT_NOTIFY_FESTIVAL)):
            slots.append(self._festival_time(opts))
        if self._memorial_on(opts):
            slots.append(self._memorial_time(opts))
        if bool(opts.get(CONF_NOTIFY_LICENSE, DEFAULT_NOTIFY_LICENSE)):
            slots.append(self._license_time(opts))
        if bool(opts.get(CONF_NOTIFY_RULES_ENABLED, DEFAULT_NOTIFY_RULES_ENABLED)):
            slots.append(self._festival_time(opts))
        return slots

    async def _maybe_notify_locked(self, local: datetime) -> None:
        opts = self.options
        data = self.data or {}
        day_key = local.strftime("%Y-%m-%d")
        if self._last_notify_day == day_key:
            return
        slots = self._notify_slots(opts)
        if not slots:
            return
        hour, minute = min(slots)
        if local.hour != hour or local.minute != minute:
            return
        festival_on = bool(opts.get(CONF_NOTIFY_FESTIVAL, DEFAULT_NOTIFY_FESTIVAL))
        memorial_on = self._memorial_on(opts)
        license_on = bool(opts.get(CONF_NOTIFY_LICENSE, DEFAULT_NOTIFY_LICENSE))
        body = format_merged_notify(
            data,
            festival=festival_on,
            memorial=memorial_on,
            license_on=license_on,
        )
        if bool(opts.get(CONF_NOTIFY_RULES_ENABLED, DEFAULT_NOTIFY_RULES_ENABLED)):
            rules = opts.get(CONF_NOTIFY_RULES) or DEFAULT_NOTIFY_RULES
            if isinstance(rules, dict) and rules:
                matches = match_notify_rules(
                    rules, local.date(), opts, build_festival_lookup(data, local.date(), opts)
                )
                extra = _valid_message(format_notify_messages(matches))
                if extra:
                    body = f"{body}\n\n{extra}".strip() if body else extra
        if not _valid_message(body):
            return
        language = str(opts.get(CONF_LANGUAGE) or DEFAULT_LANGUAGE)
        if language == "zh-Hant":
            body = convert_text(body, language)
        title = "早上好🦔"
        self._last_notify_day = day_key
        await self._dispatch(opts, f"\n{body}", title)

    async def _dispatch(self, opts: dict[str, Any], body: str, title: str) -> bool:
        services = opts.get(CONF_NOTIFY) or []
        if isinstance(services, str):
            services = [services]
        sent = False
        seen: set[str] = set()
        message = str(body).replace("\\n", "\n")
        carousel_text = f"{title}\n{message}" if title else message
        stamp = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
        footer = f"本通知 By 狂欢马克思\n通知时间: {stamp}"
        language = str(opts.get(CONF_LANGUAGE) or DEFAULT_LANGUAGE)
        if language == "zh-Hant":
            footer = convert_text(footer, language)
        notify_message = f"{message.strip()}\n\n{footer}"
        for item in services:
            name = str(item).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            domain, _, service = name.partition(".")
            if domain != "notify" or not service or service == "send_message":
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    service,
                    {"title": title, "message": notify_message},
                    blocking=False,
                )
                sent = True
            except Exception:
                _LOGGER.exception("notify failed: %s", item)
        has_send = self.hass.services.has_service("ha_msg_notify", "send")
        has_carousel = self.hass.services.has_service("ha_msg_notify", "carousel")

        if sent:
            if has_carousel:
                try:
                    await self.hass.services.async_call(
                        "ha_msg_notify",
                        "carousel",
                        {"content": carousel_text, "source": title},
                        blocking=False,
                    )
                except Exception:
                    _LOGGER.exception("ha_msg_notify.carousel failed")
        elif has_send:
            try:
                await self.hass.services.async_call(
                    "ha_msg_notify",
                    "send",
                    {
                        "title": title,
                        "message": notify_message,
                        "content": carousel_text,
                        "source": title,
                        "carousel": True,
                    },
                    blocking=False,
                )
                sent = True
            except Exception:
                _LOGGER.exception("ha_msg_notify.send failed")
        elif has_carousel:
            try:
                await self.hass.services.async_call(
                    "ha_msg_notify",
                    "carousel",
                    {"content": carousel_text, "source": title},
                    blocking=False,
                )
                sent = True
            except Exception:
                _LOGGER.exception("ha_msg_notify.carousel failed")

        return sent
