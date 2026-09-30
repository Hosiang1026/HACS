from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ..apis.lottery_cwl import fetch_lottery, fetch_lottery_history
from ..const import (
    CONF_INTERVAL,
    CONF_PREDICT_ENABLED,
    CONF_PROVIDER,
    CONF_TYPES,
    DEFAULT_LOTTERY_HISTORY,
    DEFAULT_LOTTERY_INTERVAL,
    DEFAULT_LOTTERY_PREDICT,
    DOMAIN,
    LOTTERY_SSQ,
    LOTTERY_TYPES,
    PROVIDER_CWL,
)
from ..lottery_predict import predict_from_history
from ..lottery_schedule import calc_lottery_interval_minutes, waiting_for_results
from ..notify_util import async_send_notify, format_carousel, format_notify
from .update_stamp import mark_updated

_LOGGER = logging.getLogger(__name__)

_NAMES = {
    "ssq": "双色球",
    "3d": "福彩3D",
    "kl8": "快乐8",
    "qlc": "七乐彩",
}
_TITLES = {
    "ssq": "🎱双色球",
    "3d": "🎱福彩3D",
    "kl8": "🎱快乐8",
    "qlc": "🎱七乐彩",
}
_NOTIFY_ORDER = ("3d", "ssq", "kl8", "qlc")


def _has_val(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text not in ("_", "0")


def _predict_lines(predict: dict[str, Any] | None) -> list[str]:
    if not isinstance(predict, dict) or not predict.get("value"):
        return []
    lines = ["", "💹下期预测号码", ""]
    if predict.get("based_on"):
        lines.append(f"· 彩票期数: {predict.get('based_on')}")
    if predict.get("blue"):
        lines.append(f"· 蓝球号码: {predict.get('blue')}")
    if predict.get("red"):
        lines.append(f"· 红球号码: {predict.get('red')}")
    return lines


def _item_lines(t: str, item: dict[str, Any]) -> list[str]:
    code = str(item.get("code") or "")
    lines = [f"· 开奖期号: {code}"]
    if item.get("date"):
        lines.append(f"· 开奖日期: {item.get('date')}")
    if _has_val(item.get("sales")):
        lines.append(f"· 销售金额: {item.get('sales')}元")
    if _has_val(item.get("poolmoney")):
        lines.append(f"· 奖池金额: {item.get('poolmoney')}元")
    if t == "ssq":
        if item.get("blue"):
            lines.append(f"· 蓝球号码: {item.get('blue')}")
        if item.get("red"):
            lines.append(f"· 红球号码: {item.get('red')}")
    elif t == "qlc":
        if item.get("red"):
            lines.append(f"· 红球号码: {item.get('red')}")
        if item.get("blue"):
            lines.append(f"· 蓝球号码: {item.get('blue')}")
    elif item.get("red"):
        lines.append(f"· 中奖号码: {item.get('red')}")
    if _has_val(item.get("content")):
        lines.append(f"· 中奖情况: {item.get('content')}")
    return lines


def _notify_order(types: list[str], keys: set[str] | dict[str, Any]) -> list[str]:
    selected = [t for t in types if t in keys]
    rank = {name: idx for idx, name in enumerate(_NOTIFY_ORDER)}
    return sorted(selected, key=lambda t: rank.get(t, len(_NOTIFY_ORDER)))


def _compose_notify(
    order: list[str],
    data: dict[str, Any],
    pending: dict[str, dict[str, Any]],
    predict_on: bool,
) -> tuple[str, str]:
    predict = None
    if len(order) == 1:
        t = order[0]
        item = data.get(t) or pending[t]
        lines = _item_lines(t, item)
        if t == LOTTERY_SSQ and predict_on:
            raw = item.get("predict")
            lines.extend(_predict_lines(raw if isinstance(raw, dict) else None))
        return _TITLES.get(t, _NAMES.get(t, t)), format_notify(*lines)

    blocks: list[str] = []
    for t in order:
        item = data.get(t) or pending[t]
        head = _TITLES.get(t, _NAMES.get(t, t))
        blocks.append("\n".join([head, *_item_lines(t, item)]))
        if t == LOTTERY_SSQ and predict_on:
            raw = item.get("predict")
            if isinstance(raw, dict):
                predict = raw
    if predict:
        extra = _predict_lines(predict)
        while extra and extra[0] == "":
            extra = extra[1:]
        if extra:
            blocks.append("\n".join(extra))
    return "🎱福利彩票", "\n\n".join(blocks)


class LotteryCoordinator(DataUpdateCoordinator[dict[str, Any]]):
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
        self.device_id = f"{entry.entry_id}_lottery"
        self.device_name = "福利彩票"
        self._last_codes: dict[str, str] = {}
        self._pending_notify: dict[str, dict[str, Any]] = {}
        self.last_update_at = None
        minutes = calc_lottery_interval_minutes(
            types=module_cfg.get(CONF_TYPES) or list(LOTTERY_TYPES),
            data=None,
            draw_poll_minutes=int(
                module_cfg.get(CONF_INTERVAL) or DEFAULT_LOTTERY_INTERVAL
            ),
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_lottery",
            update_interval=timedelta(minutes=max(1, minutes)),
        )

    def _apply_interval(self, data: dict[str, Any] | None) -> None:
        minutes = calc_lottery_interval_minutes(
            types=self.module_cfg.get(CONF_TYPES) or list(LOTTERY_TYPES),
            data=data,
            draw_poll_minutes=int(
                self.module_cfg.get(CONF_INTERVAL) or DEFAULT_LOTTERY_INTERVAL
            ),
        )
        self.update_interval = timedelta(minutes=max(1, minutes))

    async def _async_update_data(self) -> dict[str, Any]:
        provider = self.module_cfg.get(CONF_PROVIDER) or PROVIDER_CWL
        if provider != PROVIDER_CWL:
            raise UpdateFailed(f"provider not implemented: {provider}")
        types = self.module_cfg.get(CONF_TYPES) or list(LOTTERY_TYPES)
        session = async_get_clientsession(self.hass)
        predict_on = self.module_cfg.get(CONF_PREDICT_ENABLED, DEFAULT_LOTTERY_PREDICT)
        result: dict[str, Any] = {}
        for t in types:
            try:
                if predict_on and t == LOTTERY_SSQ:
                    history = await fetch_lottery_history(
                        session, t, page_size=DEFAULT_LOTTERY_HISTORY
                    )
                    latest = history[0]
                    latest["predict"] = predict_from_history(t, history)
                    result[t] = latest
                else:
                    result[t] = await fetch_lottery(session, t)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("lottery %s failed: %s", t, err)
        if not result:
            raise UpdateFailed("lottery all failed")
        await self._maybe_notify(result)
        mark_updated(self)
        self._apply_interval(result)
        return result

    async def _maybe_notify(self, data: dict[str, Any]) -> None:
        predict_on = self.module_cfg.get(CONF_PREDICT_ENABLED, DEFAULT_LOTTERY_PREDICT)
        types = self.module_cfg.get(CONF_TYPES) or list(LOTTERY_TYPES)
        for t, item in data.items():
            code = str(item.get("code") or "")
            if not code:
                continue
            prev = self._last_codes.get(t)
            self._last_codes[t] = code
            if prev is None:
                continue
            if prev == code:
                if t in self._pending_notify:
                    self._pending_notify[t] = item
                continue
            self._pending_notify[t] = item
        if not self._pending_notify:
            return
        if waiting_for_results(
            dt_util.now(), types, {**self._pending_notify, **data}
        ):
            return
        order = _notify_order(list(types), self._pending_notify)
        if not order:
            return
        title, message = _compose_notify(
            order, data, self._pending_notify, predict_on
        )
        await async_send_notify(
            self.hass,
            self.entry_opts,
            self.module_cfg,
            title,
            message,
            carousel=format_carousel(*message.splitlines()),
            ignore_window=True,
        )
        self._pending_notify.clear()
