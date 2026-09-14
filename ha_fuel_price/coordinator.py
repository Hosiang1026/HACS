from __future__ import annotations

from datetime import date, datetime, time
import logging
from typing import Any

from aiohttp import ClientTimeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    BASE_URL,
    CODE_TO_NAME,
    CONF_FILL_LITERS,
    CONF_NOTIFY,
    CONF_NOTIFY_DAILY,
    CONF_NOTIFY_ENABLE,
    CONF_NOTIFY_LOW,
    CONF_NOTIFY_WEEKEND,
    CONF_PROVINCE_CODE,
    CONF_PROVINCE_NAME,
    CONF_PROVINCES,
    DEFAULT_FILL_LITERS,
    DEFAULT_NOTIFY_DAILY,
    DEFAULT_NOTIFY_ENABLE,
    DEFAULT_NOTIFY_LOW,
    DEFAULT_NOTIFY_WEEKEND,
    DOMAIN,
    FETCH_HOUR,
    FETCH_MINUTE,
    FUEL_95,
    FUEL_TYPES,
    HTTP_HEADERS,
    NEAR_LOW_DELTA,
    PROVINCE_URL,
    STORAGE_KEY,
    STORAGE_VERSION,
    normalize_fill_liters,
)
from .localize import tr
from .scraper import parse_adjust_schedule, parse_province_prices, parse_update_text

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=40)


def _notify_values(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        action = raw.get("action") or raw.get("service")
        return [action] if action else []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item:
            out.append(item)
        elif isinstance(item, dict):
            action = item.get("action") or item.get("service")
            if action:
                out.append(action)
    return out


class FuelPriceCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.entry = entry
        self.session = async_get_clientsession(hass)
        self._store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
        self._low_prices: dict[str, dict[str, Any]] = {}
        self._last_notify_date: str | None = None
        self._last_near_low_notify: dict[str, str] = {}
        self._unsub_schedule: CALLBACK_TYPE | None = None
        entry.async_on_unload(self._async_cancel_schedule)
        self._async_schedule_daily()

    def _async_cancel_schedule(self) -> None:
        if self._unsub_schedule:
            self._unsub_schedule()
            self._unsub_schedule = None

    def _fetch_at(self, day: date) -> datetime:
        local = dt_util.now().tzinfo
        return datetime.combine(day, time(FETCH_HOUR, FETCH_MINUTE), tzinfo=local)

    def _async_schedule_daily(self) -> None:
        self._async_cancel_schedule()
        self._unsub_schedule = async_track_time_change(
            self.hass,
            self._async_scheduled_refresh,
            hour=FETCH_HOUR,
            minute=FETCH_MINUTE,
            second=0,
        )

    def _async_schedule_from_trend(self, trend: str) -> None:
        today = dt_util.now().date()
        plan = parse_adjust_schedule(trend, today=today)
        if plan is True:
            self._async_schedule_daily()
            return
        if plan is False:
            self._async_cancel_schedule()
            return
        when = self._fetch_at(plan)
        if when <= dt_util.now():
            self._async_cancel_schedule()
            return
        self._async_cancel_schedule()
        self._unsub_schedule = async_track_point_in_time(
            self.hass,
            self._async_scheduled_refresh,
            when,
        )
        _LOGGER.debug("下次油价抓取: %s", when.isoformat())

    async def _async_scheduled_refresh(self, _now: datetime) -> None:
        await self.async_request_refresh()

    @property
    def provinces(self) -> list[dict[str, Any]]:
        return list(self.entry.options.get(CONF_PROVINCES) or [])

    @property
    def integration_name(self) -> str:
        return self.entry.data.get("name") or self.entry.title

    def low_price(self, code: str, fuel: str) -> float | None:
        item = self._normalize_low_item(self._low_prices.get(code) or {})
        value = item.get(fuel)
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None

    def low_95(self, code: str) -> float | None:
        return self.low_price(code, FUEL_95)

    def low_date(self, code: str) -> str | None:
        item = self._normalize_low_item(self._low_prices.get(code) or {})
        date = item.get("date")
        return str(date) if date else None

    def low_95_date(self, code: str) -> str | None:
        return self.low_date(code)

    @staticmethod
    def _normalize_low_item(raw: dict[str, Any]) -> dict[str, Any]:
        if any(k in raw for k in FUEL_TYPES):
            return dict(raw)
        price = raw.get("price")
        out: dict[str, Any] = {}
        if price is not None:
            out[FUEL_95] = price
        if raw.get("date"):
            out["date"] = raw["date"]
        return out

    async def async_initialize(self) -> None:
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        if isinstance(stored.get("provinces"), dict):
            self._low_prices = {
                str(k): self._normalize_low_item(dict(v))
                for k, v in stored["provinces"].items()
                if isinstance(v, dict)
            }
            self._last_notify_date = stored.get("last_notify_date") or None
            near = stored.get("last_near_low_notify") or {}
            if isinstance(near, dict):
                self._last_near_low_notify = {
                    str(k): str(v) for k, v in near.items() if v
                }
            return
        self._low_prices = {
            str(k): self._normalize_low_item(dict(v))
            for k, v in stored.items()
            if isinstance(v, dict)
        }

    async def _async_persist(self) -> None:
        await self._store.async_save(
            {
                "provinces": self._low_prices,
                "last_notify_date": self._last_notify_date,
                "last_near_low_notify": self._last_near_low_notify,
            }
        )

    def _should_notify_today(self) -> bool:
        daily = bool(
            self.entry.options.get(CONF_NOTIFY_DAILY, DEFAULT_NOTIFY_DAILY)
        )
        weekend = bool(
            self.entry.options.get(CONF_NOTIFY_WEEKEND, DEFAULT_NOTIFY_WEEKEND)
        )
        is_weekend = dt_util.now().weekday() >= 5
        if daily:
            return True
        if weekend and is_weekend:
            return True
        return False

    async def _async_maybe_notify(self, data: dict[str, Any]) -> None:
        if not self.entry.options.get(CONF_NOTIFY_ENABLE, DEFAULT_NOTIFY_ENABLE):
            return
        if not _notify_values(self.entry.options.get(CONF_NOTIFY)):
            return
        today = dt_util.now().date().isoformat()
        if self._last_notify_date == today:
            return
        if not self._should_notify_today():
            return
        text = self._build_notify_text(data)
        if not text:
            return
        await self._async_send_notify(tr(self.hass, "notify_daily_title"), text)
        self._last_notify_date = today
        await self._async_persist()

    def _fuel_label(self, fuel: str) -> str:
        return tr(self.hass, f"fuel_{fuel}")

    def _build_notify_text(self, data: dict[str, Any]) -> str:
        provinces = data.get("provinces") or {}
        lines: list[str] = []
        fill_liters = normalize_fill_liters(
            self.entry.options.get(CONF_FILL_LITERS, DEFAULT_FILL_LITERS)
        )
        low_items: list[tuple[str, float]] = []
        convert_items: list[tuple[str, float, float]] = []
        max_low_date = ""
        for item in self.provinces:
            code = item.get(CONF_PROVINCE_CODE)
            if not code or code not in provinces:
                continue
            name = item.get(CONF_PROVINCE_NAME) or CODE_TO_NAME.get(code, code)
            prices = provinces[code]
            lines.append(tr(self.hass, "notify_province", name=name))
            for fuel in FUEL_TYPES:
                value = prices.get(fuel)
                if value is None:
                    continue
                lines.append(
                    tr(
                        self.hass,
                        "notify_price_line",
                        fuel=self._fuel_label(fuel),
                        value=value,
                    )
                )
            low = self.low_95(code)
            if low is not None:
                low_items.append((name, low))
            current = prices.get(FUEL_95)
            if current is not None and low is not None:
                try:
                    convert_items.append((name, float(current), float(low)))
                except (TypeError, ValueError):
                    pass
            low_date = self.low_date(code) or ""
            if low_date and (not max_low_date or low_date > max_low_date):
                max_low_date = low_date
        if low_items:
            lines.append(tr(self.hass, "notify_low_header"))
            lines.append("")
            for name, low in low_items:
                lines.append(tr(self.hass, "notify_low_95", name=name, value=low))
            if max_low_date:
                lines.append(tr(self.hass, "notify_update_time", date=max_low_date))
        for name, current, low in convert_items:
            lines.append(tr(self.hass, "notify_convert_header", name=name))
            if fill_liters > 0:
                liters = (
                    int(fill_liters) if fill_liters == int(fill_liters) else fill_liters
                )
                lines.append(tr(self.hass, "notify_tank", liters=liters))
            for amount in (30, 50):
                curr_cost = current * amount
                lines.append(
                    tr(
                        self.hass,
                        "notify_cost_line",
                        liters=amount,
                        cost=curr_cost,
                        diff=curr_cost - low * amount,
                    )
                )
        trend = str(data.get("trend") or "").strip()
        if trend:
            lines.append(f"\n{trend}")
        return "\n".join(lines).strip()

    async def _async_send_notify(
        self, title: str, message: str, actions: Any = None
    ) -> None:
        notify_list = (
            _notify_values(actions)
            if actions is not None
            else _notify_values(self.entry.options.get(CONF_NOTIFY))
        )
        for action in notify_list:
            if "." not in action:
                continue
            domain, service = action.split(".", 1)
            try:
                if self.hass.services.has_service(domain, service):
                    await self.hass.services.async_call(
                        domain,
                        service,
                        {"title": title, "message": message},
                        blocking=False,
                    )
                elif domain == "notify" and self.hass.states.get(action):
                    await self.hass.services.async_call(
                        "notify",
                        "send_message",
                        {
                            "entity_id": action,
                            "title": title,
                            "message": message,
                        },
                        blocking=False,
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("notify failed: %s", action)

        if self.hass.services.has_service("ha_msg_notify", "carousel"):
            try:
                await self.hass.services.async_call(
                    "ha_msg_notify",
                    "carousel",
                    {"content": message, "source": title},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("ha_msg_notify.carousel failed")
        elif self.hass.services.has_service("ha_msg_notify", "send"):
            try:
                await self.hass.services.async_call(
                    "ha_msg_notify",
                    "send",
                    {
                        "title": title,
                        "message": message,
                        "content": message,
                        "source": title,
                        "carousel": True,
                    },
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("ha_msg_notify.send failed")

    async def _async_update_low_prices(
        self, provinces_data: dict[str, dict[str, Any]]
    ) -> set[str]:
        """Update lows; return province codes whose 95 low newly initialized."""
        today = dt_util.now().date().isoformat()
        changed = False
        initialized_95: set[str] = set()
        for code, prices in provinces_data.items():
            old = self._normalize_low_item(self._low_prices.get(code) or {})
            had_95 = self.low_price(code, FUEL_95) is not None
            updated = dict(old)
            hit = False
            for fuel in FUEL_TYPES:
                current = prices.get(fuel)
                if current is None:
                    continue
                try:
                    current_f = float(current)
                except (TypeError, ValueError):
                    continue
                if current_f <= 0:
                    continue
                old_price = updated.get(fuel)
                try:
                    old_f = float(old_price) if old_price is not None else None
                except (TypeError, ValueError):
                    old_f = None
                if old_f is None or current_f < old_f:
                    updated[fuel] = current_f
                    hit = True
            if hit:
                updated["date"] = today
                self._low_prices[code] = updated
                changed = True
                if not had_95 and self.low_price(code, FUEL_95) is not None:
                    initialized_95.add(code)
        if changed:
            await self._async_persist()
        return initialized_95

    async def _async_update_data(self) -> dict[str, Any]:
        provinces_data: dict[str, dict[str, Any]] = {}
        for item in self.provinces:
            code = item.get(CONF_PROVINCE_CODE)
            name = item.get(CONF_PROVINCE_NAME) or CODE_TO_NAME.get(code, code)
            if not code:
                continue
            url = PROVINCE_URL.format(code=code)
            try:
                async with self.session.get(
                    url, headers=HTTP_HEADERS, timeout=_TIMEOUT
                ) as resp:
                    resp.raise_for_status()
                    html = await resp.text()
                prices = parse_province_prices(html)
                provinces_data[code] = {"name": name, **prices}
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("抓取 %s 油价失败: %s", name, err)

        trend = ""
        try:
            async with self.session.get(
                BASE_URL, headers=HTTP_HEADERS, timeout=_TIMEOUT
            ) as resp:
                resp.raise_for_status()
                html = await resp.text()
            trend = parse_update_text(html)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("抓取油价趋势失败: %s", err)

        if not provinces_data and self.provinces:
            raise UpdateFailed(tr(self.hass, "update_failed"))

        initialized_95 = await self._async_update_low_prices(provinces_data)
        result = {
            "update_time": dt_util.utcnow(),
            "trend": trend,
            "provinces": provinces_data,
            "low_prices": dict(self._low_prices),
        }
        self._async_schedule_from_trend(trend)
        await self._async_maybe_notify(result)
        await self._async_maybe_notify_near_low(result, initialized_95)
        return result

    async def _async_maybe_notify_near_low(
        self, data: dict[str, Any], initialized_95: set[str]
    ) -> None:
        today = dt_util.now().date().isoformat()
        provinces = data.get("provinces") or {}
        changed = False
        for item in self.provinces:
            if not bool(item.get(CONF_NOTIFY_LOW, DEFAULT_NOTIFY_LOW)):
                continue
            actions = _notify_values(item.get(CONF_NOTIFY))
            if not actions:
                continue
            code = item.get(CONF_PROVINCE_CODE)
            if not code or code not in provinces:
                continue
            if code in initialized_95:
                continue
            if self._last_near_low_notify.get(code) == today:
                continue
            current = provinces[code].get(FUEL_95)
            low = self.low_95(code)
            if current is None or low is None:
                continue
            try:
                current_f = float(current)
            except (TypeError, ValueError):
                continue
            if current_f <= 0:
                continue
            if current_f - low > NEAR_LOW_DELTA:
                continue
            name = item.get(CONF_PROVINCE_NAME) or CODE_TO_NAME.get(code, code)
            low_date = self.low_date(code) or ""
            diff = current_f - low
            msg = tr(
                self.hass,
                "notify_near_low_message",
                name=name,
                current=current_f,
                low=low,
                diff=diff,
            )
            if low_date:
                msg = f"{msg}\n{tr(self.hass, 'notify_low_date', date=low_date)}"
            await self._async_send_notify(
                tr(self.hass, "notify_near_low_title"), msg, actions
            )
            self._last_near_low_notify[code] = today
            changed = True
        if changed:
            await self._async_persist()
