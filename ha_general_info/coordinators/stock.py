from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..apis.stock import fetch_stock_sina, fetch_stock_tencent
from ..const import (
    CONF_INTERVAL,
    CONF_NOTIFY_CHANGE_PCT,
    CONF_PROVIDER,
    CONF_SYMBOLS,
    CONF_TRADING_ONLY,
    DEFAULT_STOCK_ACTIVE_INTERVAL,
    DEFAULT_STOCK_CHANGE_PCT,
    DEFAULT_STOCK_INTERVAL,
    DEFAULT_STOCK_PEAK_INTERVAL,
    DOMAIN,
    PROVIDER_SINA,
    PROVIDER_TENCENT,
)
from ..notify_util import async_send_notify, format_carousel, format_notify
from ..stock_schedule import calc_stock_interval_minutes, in_watch_session
from .update_stamp import mark_updated

_LOGGER = logging.getLogger(__name__)


def _now_text() -> str:
    return dt_util.now().strftime("%Y-%m-%d %H:%M:%S")


class StockCoordinator(DataUpdateCoordinator[dict[str, Any]]):
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
        self.device_id = f"{entry.entry_id}_stock"
        self.device_name = "股票交易"
        self._last_pct: dict[str, float] = {}
        self.last_update_at = None
        minutes = self._calc_interval()
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_stock",
            update_interval=timedelta(minutes=max(1, minutes)),
        )

    def _calc_interval(self) -> int:
        active = int(
            self.module_cfg.get(CONF_INTERVAL)
            or DEFAULT_STOCK_INTERVAL
            or DEFAULT_STOCK_ACTIVE_INTERVAL
        )
        return calc_stock_interval_minutes(
            peak_minutes=DEFAULT_STOCK_PEAK_INTERVAL,
            active_minutes=active,
            trading_only=bool(self.module_cfg.get(CONF_TRADING_ONLY, True)),
        )

    def _apply_interval(self) -> None:
        self.update_interval = timedelta(minutes=max(1, self._calc_interval()))

    async def _async_update_data(self) -> dict[str, Any]:
        trading_only = bool(self.module_cfg.get(CONF_TRADING_ONLY, True))
        if trading_only and not in_watch_session() and self.data is not None:
            self._apply_interval()
            return self.data

        symbols = self.module_cfg.get(CONF_SYMBOLS) or []
        if not symbols:
            mark_updated(self)
            self._apply_interval()
            return {}
        provider = self.module_cfg.get(CONF_PROVIDER) or PROVIDER_SINA
        session = async_get_clientsession(self.hass)
        try:
            if provider == PROVIDER_TENCENT:
                data = await fetch_stock_tencent(session, list(symbols))
            else:
                data = await fetch_stock_sina(session, list(symbols))
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err
        if not data:
            raise UpdateFailed("stock empty")
        await self._maybe_notify(data)
        mark_updated(self)
        self._apply_interval()
        return data

    async def _maybe_notify(self, data: dict[str, Any]) -> None:
        threshold = float(
            self.module_cfg.get(CONF_NOTIFY_CHANGE_PCT) or DEFAULT_STOCK_CHANGE_PCT
        )
        if threshold <= 0:
            return
        for code, item in data.items():
            pct = item.get("change_pct")
            if pct is None:
                continue
            prev = self._last_pct.get(code)
            self._last_pct[code] = float(pct)
            if abs(float(pct)) < threshold:
                continue
            if prev is not None and abs(float(pct) - prev) < 0.01:
                continue
            name = item.get("name") or code
            pct_f = float(pct)
            change = item.get("change")
            chg_s = f"{change:+g}" if isinstance(change, (int, float)) else str(change or "")
            lines = [
                f"· 股票名称: {name}",
                f"· 股票代码: {code}",
            ]
            if item.get("price") is not None:
                lines.append(f"· 现价: {item.get('price')}")
            if chg_s:
                lines.append(f"· 涨跌额: {chg_s}")
            lines.append(f"· 涨跌幅: {pct_f:+g}%")
            if item.get("prev_close") is not None:
                lines.append(f"· 昨收: {item.get('prev_close')}")
            if item.get("open") is not None:
                lines.append(f"· 今开: {item.get('open')}")
            if item.get("high") is not None:
                lines.append(f"· 最高: {item.get('high')}")
            if item.get("low") is not None:
                lines.append(f"· 最低: {item.get('low')}")
            if item.get("volume") is not None:
                lines.append(f"· 成交量: {item.get('volume')}")
            if item.get("amount") is not None:
                lines.append(f"· 成交额: {item.get('amount')}")
            dt = " ".join(
                str(x) for x in (item.get("date"), item.get("time")) if x
            ).strip()
            if dt:
                lines.append(f"· 更新时间: {dt}")
            await async_send_notify(
                self.hass,
                self.entry_opts,
                self.module_cfg,
                f"📈{name}",
                format_notify(*lines),
                carousel=format_carousel(
                    f"股票名称: {name}",
                    f"现价: {item.get('price')}" if item.get("price") is not None else "",
                    f"涨跌幅: {pct_f:+g}%",
                    f"当前时间: {dt or _now_text()}",
                ),
            )
