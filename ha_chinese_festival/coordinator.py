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
from .festival_engine import compute
from .holiday_provider import HolidayProvider
from .text_util import convert_obj

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
        self._last_calendar_day: str | None = None
        self._last_festival_day: str | None = None
        self._last_license_day: str | None = None
        self._last_memorial_day: str | None = None
        self._last_rules_day: str | None = None
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

    async def _maybe_notify_locked(self, local: datetime) -> None:
        opts = self.options
        data = self.data or {}
        day_key = local.strftime("%Y-%m-%d")
        ch, cm = self._calendar_time(opts)
        fh, fm = self._festival_time(opts)
        lh, lm = self._license_time(opts)
        mh, mm = self._memorial_time(opts)

        if (
            bool(opts.get(CONF_NOTIFY_CALENDAR, DEFAULT_NOTIFY_CALENDAR))
            and local.hour == ch
            and local.minute == cm
            and self._last_calendar_day != day_key
        ):
            body = _valid_message(data.get("calendar_content"))
            if body and await self._dispatch(opts, body, "日历通知"):
                self._last_calendar_day = day_key

        if (
            bool(opts.get(CONF_NOTIFY_FESTIVAL, DEFAULT_NOTIFY_FESTIVAL))
            and local.hour == fh
            and local.minute == fm
            and self._last_festival_day != day_key
            and data.get("has_near_festival")
        ):
            body = _valid_message(data.get("festival_content"))
            if body and await self._dispatch(opts, body, "节日通知"):
                self._last_festival_day = day_key

        if (
            bool(opts.get(CONF_NOTIFY_LICENSE, DEFAULT_NOTIFY_LICENSE))
            and local.hour == lh
            and local.minute == lm
            and self._last_license_day != day_key
            and data.get("has_near_license")
        ):
            body = _valid_message(data.get("license_content"))
            if body and await self._dispatch(opts, body, "证件到期通知"):
                self._last_license_day = day_key

        memorial_on = opts.get(CONF_NOTIFY_MEMORIAL)
        if memorial_on is None:
            memorial_on = opts.get("notify_birthday", DEFAULT_NOTIFY_MEMORIAL) or opts.get(
                "notify_anniversary", DEFAULT_NOTIFY_MEMORIAL
            )
        if (
            bool(memorial_on)
            and local.hour == mh
            and local.minute == mm
            and self._last_memorial_day != day_key
            and data.get("has_near_memorial")
        ):
            body = _valid_message(data.get("memorial_content"))
            if body and await self._dispatch(opts, body, "生日/纪念日"):
                self._last_memorial_day = day_key

        if (
            bool(opts.get(CONF_NOTIFY_RULES_ENABLED, DEFAULT_NOTIFY_RULES_ENABLED))
            and local.hour == fh
            and local.minute == fm
            and self._last_rules_day != day_key
        ):
            rules = opts.get(CONF_NOTIFY_RULES) or DEFAULT_NOTIFY_RULES
            if isinstance(rules, dict) and rules:
                today = local.date()
                lookup = build_festival_lookup(data, today, opts)
                matches = match_notify_rules(rules, today, opts, lookup)
                body = _valid_message(format_notify_messages(matches))
                if body and await self._dispatch(opts, body, "高级通知"):
                    self._last_rules_day = day_key

    async def _dispatch(self, opts: dict[str, Any], body: str, title: str) -> bool:
        services = opts.get(CONF_NOTIFY) or []
        if isinstance(services, str):
            services = [services]
        sent = False
        seen: set[str] = set()
        for item in services:
            name = str(item)
            if name in seen:
                continue
            seen.add(name)
            domain, _, service = name.partition(".")
            if domain != "notify" or not service:
                continue
            try:
                await self.hass.services.async_call(
                    "notify",
                    service,
                    {"title": title, "message": body},
                    blocking=False,
                )
                sent = True
            except Exception:
                _LOGGER.exception("notify failed: %s", item)

        carousel_text = str(body).replace("\\n", "\n").strip()
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
                        "message": body,
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
