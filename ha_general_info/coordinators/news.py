from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ..apis.news_rss import fetch_rss
from ..const import (
    CONF_FEEDS,
    CONF_INTERVAL,
    CONF_LIMIT,
    CONF_NOTIFY_ON_CHANGE,
    CONF_PROVIDER,
    DEFAULT_NEWS_FEEDS,
    DEFAULT_NEWS_INTERVAL,
    DEFAULT_NEWS_LIMIT,
    DOMAIN,
    PROVIDER_RSS,
)
from ..news_schedule import calc_news_interval_minutes
from ..notify_util import async_send_notify, format_carousel, format_notify
from .update_stamp import mark_updated

_LOGGER = logging.getLogger(__name__)


class NewsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        module_cfg: dict[str, Any],
        entry_opts: dict[str, Any],
    ) -> None:
        self.entry = entry
        self.module_cfg = module_cfg
        self.entry_opts = entry_opts
        self.device_id = f"{entry.entry_id}_news"
        self.device_name = "新闻资讯"
        self._last_headline: str | None = None
        self.last_update_at = None
        minutes = calc_news_interval_minutes(
            fixed_minutes=int(module_cfg.get(CONF_INTERVAL) or DEFAULT_NEWS_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_news",
            update_interval=timedelta(minutes=max(5, minutes)),
        )

    def _apply_interval(self) -> None:
        minutes = calc_news_interval_minutes(
            fixed_minutes=int(
                self.module_cfg.get(CONF_INTERVAL) or DEFAULT_NEWS_INTERVAL
            )
        )
        self.update_interval = timedelta(minutes=max(5, minutes))

    async def _async_update_data(self) -> dict[str, Any]:
        provider = self.module_cfg.get(CONF_PROVIDER) or PROVIDER_RSS
        if provider != PROVIDER_RSS:
            raise UpdateFailed(f"provider not implemented: {provider}")
        feeds = self.module_cfg.get(CONF_FEEDS) or list(DEFAULT_NEWS_FEEDS)
        limit = int(self.module_cfg.get(CONF_LIMIT) or DEFAULT_NEWS_LIMIT)
        session = async_get_clientsession(self.hass)
        try:
            data = await fetch_rss(session, list(feeds), limit)
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
        await self._maybe_notify(data)
        mark_updated(self)
        self._apply_interval()
        return data

    async def _maybe_notify(self, data: dict[str, Any]) -> None:
        if not self.module_cfg.get(CONF_NOTIFY_ON_CHANGE, True):
            return
        headline = data.get("headline")
        if not headline:
            return
        prev = self._last_headline
        self._last_headline = headline
        if prev is None or prev == headline:
            return
        lines: list[str] = []
        items = data.get("items") or []
        n = 0
        for row in items:
            if not isinstance(row, dict):
                continue
            title = (row.get("title") or "").strip()
            if not title:
                continue
            n += 1
            lines.append(f"· 新闻{n}: {title}")
        if not lines:
            lines.append(f"· 头条: {headline}")
        await async_send_notify(
            self.hass,
            self.entry_opts,
            self.module_cfg,
            "📰新闻资讯",
            format_notify(*lines),
            carousel=format_carousel(*lines),
        )
