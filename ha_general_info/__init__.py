from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ANNOUNCE,
    CONF_ENABLED,
    CONF_LIMIT,
    CONF_NOTIFY,
    CONF_NOTIFY_ENABLED,
    DEFAULT_NAME,
    DEFAULT_NEWS_LIMIT,
    DOMAIN,
    LOTTERY_TYPES,
    METAL_ITEMS,
    MODULE_LOTTERY,
    MODULE_MEDIA,
    MODULE_METAL,
    MODULE_NEWS,
    MODULE_STOCK,
    PLATFORMS,
)
from .coordinators.lottery import LotteryCoordinator
from .coordinators.media import MediaCoordinator
from .coordinators.metal import MetalCoordinator
from .coordinators.news import NewsCoordinator
from .coordinators.stock import StockCoordinator
from .defaults import merge_options

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _expected_unique_ids(entry: ConfigEntry, data: dict[str, Any]) -> set[str]:
    expected: set[str] = {f"{entry.entry_id}_created"}
    if data.get("lottery"):
        expected.add(f"{entry.entry_id}_refresh_lottery")
    if data.get("metal"):
        expected.add(f"{entry.entry_id}_refresh_metal")
    if data.get("news"):
        expected.add(f"{entry.entry_id}_refresh_news")
    if data.get("stock"):
        expected.add(f"{entry.entry_id}_refresh_stock")
    if data.get("media"):
        expected.add(f"{entry.entry_id}_refresh_media")
    if lottery := data.get("lottery"):
        expected.add(f"{lottery.device_id}_updated_at")
        types = lottery.module_cfg.get("types") or list(LOTTERY_TYPES)
        mapping = {"ssq": "ssq", "3d": "fc3d", "kl8": "kl8", "qlc": "qlc"}
        for t in types:
            expected.add(f"{lottery.device_id}_{mapping.get(t, t)}")
        if lottery.module_cfg.get("predict_enabled", True) and "ssq" in types:
            expected.add(f"{lottery.device_id}_ssq_predict")
    if metal := data.get("metal"):
        expected.add(f"{metal.device_id}_updated_at")
        raw = metal.module_cfg.get("items") or []
        if isinstance(raw, str):
            raw = [raw]
        items = [x for x in raw if x in METAL_ITEMS] or list(METAL_ITEMS)
        for key in items:
            expected.add(f"{metal.device_id}_{key}")
        expected.add(f"{metal.device_id}_intl_gold")
        expected.add(f"{metal.device_id}_intl_silver")
        expected.add(f"{metal.device_id}_sanjin_shop_cost")
        expected.add(f"{metal.device_id}_sanjin_gold_cost")
        if metal.module_cfg.get("track_low", True):
            expected.add(f"{metal.device_id}_gold_low")
            expected.add(f"{metal.device_id}_silver_low")
    if news := data.get("news"):
        expected.add(f"{news.device_id}_updated_at")
        limit = int(news.module_cfg.get(CONF_LIMIT) or DEFAULT_NEWS_LIMIT)
        for idx in range(max(1, limit)):
            expected.add(f"{news.device_id}_item_{idx + 1}")
    if stock := data.get("stock"):
        expected.add(f"{stock.device_id}_updated_at")
        for code in stock.module_cfg.get("symbols") or []:
            expected.add(f"{stock.device_id}_{str(code).lower()}")
    if media := data.get("media"):
        expected.add(f"{media.device_id}_updated_at")
        raw = media.module_cfg.get("items") or []
        if isinstance(raw, str):
            raw = [raw]
        items = [x for x in raw if x in ("movie", "tv", "music")] or [
            "movie",
            "tv",
            "music",
        ]
        limit = int(media.module_cfg.get(CONF_LIMIT) or 10)
        for key in items:
            for idx in range(max(1, limit)):
                expected.add(f"{media.device_id}_{key}_{idx + 1}")
    return expected


def _async_cleanup_orphans(hass: HomeAssistant, entry: ConfigEntry, data: dict[str, Any]) -> None:
    keep_devices = {entry.entry_id}
    for key in ("lottery", "metal", "news", "stock", "media"):
        if coord := data.get(key):
            keep_devices.add(coord.device_id)

    device_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        idents = {ident for domain, ident in device.identifiers if domain == DOMAIN}
        if idents and not idents.intersection(keep_devices):
            device_reg.async_remove_device(device.id)

    expected = _expected_unique_ids(entry, data)
    entity_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        if ent.unique_id not in expected:
            entity_reg.async_remove(ent.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    opts = merge_options(dict(entry.options))
    entry_opts = {
        CONF_NOTIFY: opts.get(CONF_NOTIFY) or entry.data.get(CONF_NOTIFY),
        CONF_ANNOUNCE: opts.get(CONF_ANNOUNCE) or entry.data.get(CONF_ANNOUNCE),
        CONF_NOTIFY_ENABLED: opts.get(
            CONF_NOTIFY_ENABLED, entry.data.get(CONF_NOTIFY_ENABLED, True)
        ),
        CONF_NAME: entry.data.get(CONF_NAME) or DEFAULT_NAME,
    }

    runtime: dict[str, Any] = {
        "lottery": None,
        "metal": None,
        "news": None,
        "stock": None,
        "media": None,
        "options": opts,
        "entry_opts": entry_opts,
    }

    if (opts.get(MODULE_LOTTERY) or {}).get(CONF_ENABLED, True):
        lottery = LotteryCoordinator(hass, entry, opts[MODULE_LOTTERY], entry_opts)
        try:
            await lottery.async_config_entry_first_refresh()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("lottery first refresh failed")
        runtime["lottery"] = lottery

    if (opts.get(MODULE_METAL) or {}).get(CONF_ENABLED, True):
        metal = MetalCoordinator(hass, entry, opts[MODULE_METAL], entry_opts)
        try:
            await metal.async_setup()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("metal first refresh failed")
        runtime["metal"] = metal

    if (opts.get(MODULE_NEWS) or {}).get(CONF_ENABLED, True):
        news = NewsCoordinator(hass, entry, opts[MODULE_NEWS], entry_opts)
        try:
            await news.async_config_entry_first_refresh()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("news first refresh failed")
        runtime["news"] = news

    if (opts.get(MODULE_STOCK) or {}).get(CONF_ENABLED, False):
        stock = StockCoordinator(hass, entry, opts[MODULE_STOCK], entry_opts)
        try:
            await stock.async_config_entry_first_refresh()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("stock first refresh failed")
        runtime["stock"] = stock

    if (opts.get(MODULE_MEDIA) or {}).get(CONF_ENABLED, False):
        media = MediaCoordinator(hass, entry, opts[MODULE_MEDIA], entry_opts)
        try:
            await media.async_config_entry_first_refresh()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("media first refresh failed")
        runtime["media"] = media

    hass.data[DOMAIN][entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_cleanup_orphans(hass, entry, runtime)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    if not hass.services.has_service(DOMAIN, "refresh"):
        async def _refresh_all(call: ServiceCall) -> None:
            target = call.data.get("module")
            for entry_id, runtime in list(hass.data.get(DOMAIN, {}).items()):
                if not isinstance(runtime, dict):
                    continue
                if target in (None, "lottery", "all") and runtime.get("lottery"):
                    await runtime["lottery"].async_request_refresh()
                if target in (None, "metal", "all") and runtime.get("metal"):
                    await runtime["metal"].async_request_refresh()
                if target in (None, "news", "all") and runtime.get("news"):
                    await runtime["news"].async_request_refresh()
                if target in (None, "stock", "all") and runtime.get("stock"):
                    await runtime["stock"].async_request_refresh()
                if target in (None, "media", "all") and runtime.get("media"):
                    await runtime["media"].async_request_refresh()

        async def _clear_low(_call: ServiceCall) -> None:
            for runtime in hass.data.get(DOMAIN, {}).values():
                if isinstance(runtime, dict) and runtime.get("metal"):
                    await runtime["metal"].clear_low()

        hass.services.async_register(
            DOMAIN,
            "refresh",
            _refresh_all,
            schema=vol.Schema({vol.Optional("module"): cv.string}),
        )
        hass.services.async_register(DOMAIN, "clear_gold_low", _clear_low)

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            if hass.services.has_service(DOMAIN, "refresh"):
                hass.services.async_remove(DOMAIN, "refresh")
            if hass.services.has_service(DOMAIN, "clear_gold_low"):
                hass.services.async_remove(DOMAIN, "clear_gold_low")
            hass.data.pop(DOMAIN, None)
    return unload_ok
