from __future__ import annotations

from copy import deepcopy
from typing import Any

from .const import (
    CONF_ANNOUNCE_ENABLED,
    CONF_CUSTOM_URL,
    CONF_ENABLED,
    CONF_FEEDS,
    CONF_ITEMS,
    CONF_INTERVAL,
    CONF_LIMIT,
    CONF_NOTIFY_CHANGE_PCT,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_END,
    CONF_NOTIFY_LOW,
    CONF_NOTIFY_ON_CHANGE,
    CONF_NOTIFY_START,
    CONF_PROVIDER,
    CONF_SANJIN_BRACELET,
    CONF_SANJIN_NECKLACE,
    CONF_SANJIN_RING,
    CONF_SYMBOLS,
    CONF_TRACK_LOW,
    CONF_TRADING_ONLY,
    CONF_TYPES,
    CONF_PREDICT_ENABLED,
    DEFAULT_LOTTERY_INTERVAL,
    DEFAULT_LOTTERY_PREDICT,
    DEFAULT_MEDIA_INTERVAL,
    DEFAULT_METAL_INTERVAL,
    DEFAULT_NEWS_FEEDS,
    DEFAULT_NEWS_INTERVAL,
    DEFAULT_NEWS_LIMIT,
    DEFAULT_NOTIFY_END,
    DEFAULT_NOTIFY_START,
    DEFAULT_SANJIN_BRACELET,
    DEFAULT_SANJIN_NECKLACE,
    DEFAULT_SANJIN_RING,
    DEFAULT_STOCK_CHANGE_PCT,
    DEFAULT_STOCK_INTERVAL,
    LOTTERY_TYPES,
    MODULE_LOTTERY,
    MODULE_MEDIA,
    MODULE_METAL,
    MODULE_NEWS,
    MODULE_STOCK,
    PROVIDER_CWL,
    PROVIDER_DOUBAN,
    PROVIDER_HUANGJINJIAGE,
    PROVIDER_RSS,
    PROVIDER_SINA,
)


def _notify_block(enabled: bool = False) -> dict[str, Any]:
    return {
        CONF_NOTIFY_ENABLED: enabled,
        CONF_NOTIFY_START: DEFAULT_NOTIFY_START,
        CONF_NOTIFY_END: DEFAULT_NOTIFY_END,
        CONF_ANNOUNCE_ENABLED: False,
    }


def default_options() -> dict[str, Any]:
    return {
        MODULE_LOTTERY: {
            CONF_ENABLED: True,
            **_notify_block(False),
            CONF_PROVIDER: PROVIDER_CWL,
            CONF_TYPES: list(LOTTERY_TYPES),
            CONF_INTERVAL: DEFAULT_LOTTERY_INTERVAL,
            CONF_PREDICT_ENABLED: DEFAULT_LOTTERY_PREDICT,
        },
        MODULE_METAL: {
            CONF_ENABLED: True,
            **_notify_block(False),
            CONF_PROVIDER: PROVIDER_HUANGJINJIAGE,
            CONF_CUSTOM_URL: "",
            CONF_ITEMS: [],
            CONF_INTERVAL: DEFAULT_METAL_INTERVAL,
            CONF_TRACK_LOW: True,
            CONF_NOTIFY_LOW: True,
            CONF_NOTIFY_CHANGE_PCT: 0,
            CONF_SANJIN_NECKLACE: DEFAULT_SANJIN_NECKLACE,
            CONF_SANJIN_BRACELET: DEFAULT_SANJIN_BRACELET,
            CONF_SANJIN_RING: DEFAULT_SANJIN_RING,
        },
        MODULE_STOCK: {
            CONF_ENABLED: False,
            **_notify_block(False),
            CONF_PROVIDER: PROVIDER_SINA,
            CONF_SYMBOLS: [],
            CONF_INTERVAL: DEFAULT_STOCK_INTERVAL,
            CONF_TRADING_ONLY: True,
            CONF_NOTIFY_CHANGE_PCT: DEFAULT_STOCK_CHANGE_PCT,
        },
        MODULE_NEWS: {
            CONF_ENABLED: True,
            **_notify_block(False),
            CONF_PROVIDER: PROVIDER_RSS,
            CONF_FEEDS: list(DEFAULT_NEWS_FEEDS),
            CONF_CUSTOM_URL: "",
            CONF_LIMIT: DEFAULT_NEWS_LIMIT,
            CONF_INTERVAL: DEFAULT_NEWS_INTERVAL,
            CONF_NOTIFY_ON_CHANGE: True,
        },
        MODULE_MEDIA: {
            CONF_ENABLED: False,
            **_notify_block(False),
            CONF_PROVIDER: PROVIDER_DOUBAN,
            CONF_ITEMS: [],
            CONF_LIMIT: 10,
            CONF_INTERVAL: DEFAULT_MEDIA_INTERVAL,
            CONF_CUSTOM_URL: "",
            CONF_NOTIFY_ON_CHANGE: False,
        },
    }


def merge_options(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_options()
    if not raw:
        return base
    out = deepcopy(base)
    for key, val in raw.items():
        if key in out and isinstance(val, dict) and isinstance(out[key], dict):
            merged = deepcopy(out[key])
            merged.update(val)
            out[key] = merged
        else:
            out[key] = val
    return out
