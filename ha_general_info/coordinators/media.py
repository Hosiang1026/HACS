from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from ..apis.media_hot import fetch_movie_hot, fetch_music_hot, fetch_tv_hot
from ..const import (
    CONF_INTERVAL,
    CONF_ITEMS,
    CONF_LIMIT,
    CONF_NOTIFY_ON_CHANGE,
    DEFAULT_MEDIA_INTERVAL,
    DOMAIN,
)
from ..notify_util import async_send_notify, format_carousel, format_notify
from .update_stamp import mark_updated

_LOGGER = logging.getLogger(__name__)

_DEFAULT_ITEMS = ["movie", "tv", "music"]
_FETCHERS = {
    "movie": fetch_movie_hot,
    "tv": fetch_tv_hot,
    "music": fetch_music_hot,
}
_NOTIFY_TITLE = {
    "movie": "🎬电影热榜",
    "tv": "📺剧集热榜",
    "music": "🎵音乐热榜",
}


def _now_text() -> str:
    return dt_util.now().strftime("%Y-%m-%d %H:%M:%S")


def _media_items(module_cfg: dict[str, Any]) -> list[str]:
    raw = module_cfg.get(CONF_ITEMS) or []
    if isinstance(raw, str):
        raw = [raw]
    items = [x for x in raw if x in _FETCHERS]
    return items or list(_DEFAULT_ITEMS)


class MediaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
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
        self.device_id = f"{entry.entry_id}_media"
        self.device_name = "影视音乐"
        self._last: dict[str, str] = {}
        self.last_update_at = None
        minutes = int(module_cfg.get(CONF_INTERVAL) or DEFAULT_MEDIA_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_media",
            update_interval=timedelta(minutes=max(30, minutes)),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        items = _media_items(self.module_cfg)
        limit = int(self.module_cfg.get(CONF_LIMIT) or 10)
        session = async_get_clientsession(self.hass)
        result: dict[str, Any] = {}
        for key in items:
            fetcher = _FETCHERS.get(key)
            if not fetcher:
                continue
            try:
                result[key] = await fetcher(session, limit)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("%s hot failed: %s", key, err)
                result[key] = {"top": None, "items": []}
        await self._maybe_notify(result)
        mark_updated(self)
        return result

    async def _maybe_notify(self, data: dict[str, Any]) -> None:
        if not self.module_cfg.get(CONF_NOTIFY_ON_CHANGE, False):
            return
        for key, title in _NOTIFY_TITLE.items():
            item = data.get(key) or {}
            top = item.get("top")
            if not top:
                continue
            prev = self._last.get(key)
            self._last[key] = str(top)
            if prev is None or prev == top:
                continue
            lines: list[str] = []
            items = item.get("items") or []
            n = 0
            for row in items[:5]:
                if not isinstance(row, dict):
                    continue
                name = (row.get("title") or "").strip()
                if not name:
                    continue
                n += 1
                if row.get("artists"):
                    name = f"{name} - {row.get('artists')}"
                lines.append(f"· 第{n}名: {name}")
                if row.get("rating") is not None:
                    lines.append(f"· 评分: {row.get('rating')}")
                if row.get("album"):
                    lines.append(f"· 专辑: {row.get('album')}")
                if row.get("release_date"):
                    if key == "movie":
                        lines.append(f"· 上映: {row.get('release_date')}")
                    elif key == "tv":
                        lines.append(f"· 开播: {row.get('release_date')}")
                    else:
                        lines.append(f"· 发行: {row.get('release_date')}")
            if not lines:
                lines.append(f"· 榜首: {top}")
            rank2 = ""
            if len(items) > 1 and isinstance(items[1], dict):
                rank2 = (items[1].get("title") or "").strip()
                if items[1].get("artists"):
                    rank2 = f"{rank2} - {items[1].get('artists')}"
            await async_send_notify(
                self.hass,
                self.entry_opts,
                self.module_cfg,
                title,
                format_notify(*lines),
                carousel=format_carousel(
                    f"榜单: {title}",
                    f"榜首: {top}",
                    f"第2名: {rank2}" if rank2 else "",
                    f"当前时间: {_now_text()}",
                ),
            )
