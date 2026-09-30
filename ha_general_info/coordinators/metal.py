from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..apis.metal_hj import fetch_metal
from ..const import (
    CONF_CUSTOM_URL,
    CONF_INTERVAL,
    CONF_NOTIFY_LOW,
    CONF_PROVIDER,
    CONF_SANJIN_BRACELET,
    CONF_SANJIN_NECKLACE,
    CONF_SANJIN_RING,
    CONF_TRACK_LOW,
    DEFAULT_METAL_INTERVAL,
    DEFAULT_SANJIN_BRACELET,
    DEFAULT_SANJIN_NECKLACE,
    DEFAULT_SANJIN_RING,
    DOMAIN,
    PROVIDER_CUSTOM,
    PROVIDER_HUANGJINJIAGE,
    STORAGE_VERSION,
)
from ..notify_util import async_send_notify, format_carousel
from .update_stamp import mark_updated

_LOGGER = logging.getLogger(__name__)
_OZ_TO_G = 31.1035


def _num(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


class MetalCoordinator(DataUpdateCoordinator[dict[str, Any]]):
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
        self.device_id = f"{entry.entry_id}_metal"
        self.device_name = "金银价格"
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.metal")
        self._low: dict[str, Any] = {}
        self.last_update_at = None
        minutes = int(module_cfg.get(CONF_INTERVAL) or DEFAULT_METAL_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_metal",
            update_interval=timedelta(minutes=max(5, minutes)),
        )

    async def async_setup(self) -> None:
        self._low = await self._store.async_load() or {}
        await self.async_config_entry_first_refresh()

    async def clear_low(self) -> None:
        self._low = {}
        await self._store.async_save(self._low)
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        provider = self.module_cfg.get(CONF_PROVIDER) or PROVIDER_HUANGJINJIAGE
        session = async_get_clientsession(self.hass)
        url = None
        if provider == PROVIDER_CUSTOM:
            url = self.module_cfg.get(CONF_CUSTOM_URL) or None
        elif provider != PROVIDER_HUANGJINJIAGE:
            raise UpdateFailed(f"provider not implemented: {provider}")
        try:
            data = await fetch_metal(session, url)
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(str(err)) from err

        gold = data.get("gold")
        silver = data.get("silver")
        notified_low = False
        if self.module_cfg.get(CONF_TRACK_LOW, True):
            if isinstance(gold, (int, float)):
                changed, notified = await self._track_low(
                    "gold", gold, "黄金", data
                )
                notified_low = notified_low or notified
            if isinstance(silver, (int, float)):
                await self._track_low("silver", silver, "白银", data)
        data["gold_low"] = self._low.get("gold_low")
        data["gold_low_date"] = self._low.get("gold_low_date") or self._low.get("date")
        data["silver_low"] = self._low.get("silver_low")
        data["silver_low_date"] = self._low.get("silver_low_date")
        data["_notified_low"] = notified_low
        data.update(self._sanjin_cost(data))
        mark_updated(self)
        return data

    async def _track_low(
        self,
        kind: str,
        price: float,
        label: str,
        data: dict[str, Any],
    ) -> tuple[bool, bool]:
        key = f"{kind}_low"
        date_key = f"{kind}_low_date"
        prev = self._low.get(key)
        if prev is not None and price >= float(prev):
            return False, False
        self._low[key] = price
        self._low[date_key] = dt_util.now().date().isoformat()
        if kind == "gold":
            self._low["date"] = self._low[date_key]
        await self._store.async_save(self._low)
        notified = False
        if prev is not None and self.module_cfg.get(CONF_NOTIFY_LOW, True):
            notified = True
            await async_send_notify(
                self.hass,
                self.entry_opts,
                self.module_cfg,
                "👑今日金价",
                self._gold_notify_body(data, kind, price),
                carousel=format_carousel(
                    f"国内黄金：{_num(data.get('gold'))}元/克"
                    if data.get("gold") is not None
                    else "",
                    f"国内白银：{_num(data.get('silver'))}元/克"
                    if data.get("silver") is not None
                    else "",
                    f"最低{label}：{_num(price)}元/克",
                ),
            )
        return True, notified

    def _gold_notify_body(
        self, data: dict[str, Any], kind: str, price: float
    ) -> str:
        metal_lines = ["🏅金银价格"]
        if data.get("silver") is not None:
            metal_lines.append(f"· 国内白银：{_num(data.get('silver'))}元/克")
        if data.get("gold") is not None:
            metal_lines.append(f"· 国内黄金：{_num(data.get('gold'))}元/克")
        intl_silver = data.get("intl_silver_text") or data.get("intl_silver")
        intl_gold = data.get("intl_gold_text") or data.get("intl_gold")
        if intl_silver not in (None, ""):
            metal_lines.append(f"· 国际白银：{intl_silver}美元/盎司")
        if intl_gold not in (None, ""):
            metal_lines.append(f"· 国际黄金：{intl_gold}美元/盎司")

        store_lines: list[str] = []
        shops = data.get("shops") or {}
        if isinstance(shops, dict) and shops:
            store_lines = ["🏅金店价格"]
            for brand, p in list(shops.items())[:7]:
                store_lines.append(f"· {brand}：{_num(p)}元/克")

        low_lines = ["🎯最低价格"]
        gold_low = self._low.get("gold_low")
        if kind == "gold":
            gold_low = price
        if gold_low is not None:
            low_lines.append(f"· 国内黄金：{_num(gold_low)}元/克")
        silver_low = self._low.get("silver_low")
        if kind == "silver":
            silver_low = price
        if kind == "silver" and silver_low is not None:
            low_lines.append(f"· 国内白银：{_num(silver_low)}元/克")
        low_date = (
            self._low.get(f"{kind}_low_date")
            or self._low.get("date")
            or dt_util.now().date().isoformat()
        )
        if low_date:
            low_lines.append(f"· 更新时间: {low_date}")

        conv_lines: list[str] = []
        gold = data.get("gold")
        intl = data.get("intl_gold")
        rate = data.get("usd_cny")
        if not isinstance(rate, (int, float)):
            rate = 7.1329
        if isinstance(gold, (int, float)) and isinstance(intl, (int, float)):
            converted = round(float(intl) / _OZ_TO_G * float(rate), 2)
            diff = round(float(gold) - converted, 2)
            conv_lines = [
                "⚖金价换算",
                f"· 国际换算：{converted}元/克",
                f"· 50克价格：{round(float(gold) * 50, 2)}元|差价{round(diff * 50, 2)}元",
            ]
        sections = [
            "\n".join(metal_lines),
            "\n".join(store_lines),
            "\n".join(low_lines),
            "\n".join(conv_lines),
        ]
        return "\n\n".join(s for s in sections if s.strip())

    def _sanjin_cost(self, data: dict[str, Any]) -> dict[str, Any]:
        def _grams(key: str, default: float) -> float:
            try:
                return max(0.0, float(self.module_cfg.get(key, default) or 0))
            except (TypeError, ValueError):
                return default

        def _cost(unit: Any) -> float | None:
            if isinstance(unit, (int, float)) and total_g > 0:
                return round(float(unit) * total_g, 2)
            return None

        necklace = _grams(CONF_SANJIN_NECKLACE, DEFAULT_SANJIN_NECKLACE)
        bracelet = _grams(CONF_SANJIN_BRACELET, DEFAULT_SANJIN_BRACELET)
        ring = _grams(CONF_SANJIN_RING, DEFAULT_SANJIN_RING)
        total_g = round(necklace + bracelet + ring, 2)
        shop = data.get("shop")
        gold = data.get("gold")
        return {
            "sanjin_necklace": necklace,
            "sanjin_bracelet": bracelet,
            "sanjin_ring": ring,
            "sanjin_grams": total_g,
            "sanjin_shop_unit": shop,
            "sanjin_gold_unit": gold,
            "sanjin_shop_cost": _cost(shop),
            "sanjin_gold_cost": _cost(gold),
        }
