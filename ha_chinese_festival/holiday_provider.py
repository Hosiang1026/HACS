from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import calendar_cn as cal

_LOGGER = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent / "data" / "holiday_cache.json"
_BITEFU_API = "http://tool.bitefu.net/jiari/"
_REQUEST_TIMEOUT = 10
_CACHE_TTL_DAYS = 15
_FETCH_MONTHS = 6

_HOLIDAY_NAMES: dict[str, str] = {
    "0101": "元旦",
    "0501": "劳动节",
    "1001": "国庆节",
    "1002": "国庆节",
    "1003": "国庆节",
    "1004": "国庆节",
    "1005": "国庆节",
    "1006": "国庆节",
    "1007": "国庆节",
}

_LUNAR_HOLIDAY_NAMES: dict[str, str] = {
    "0101": "春节",
    "0505": "端午节",
    "0815": "中秋节",
}


class HolidayProvider:
    def __init__(
        self,
        *,
        fetch_enabled: bool = True,
        cache_path: Path | None = None,
        cache_ttl_days: int = _CACHE_TTL_DAYS,
    ) -> None:
        self._fetch_enabled = fetch_enabled
        self._cache_path = cache_path or _CACHE_PATH
        self._cache_ttl_days = cache_ttl_days
        self._holiday_json: dict[str, Any] = {}
        self._loaded = False

    def get_day_type(self, d: date) -> int:
        self._ensure_loaded()
        y_str = str(d.year)
        h_dict = self._holiday_json.get(y_str, {})
        key = f"{d.month:02d}{d.day:02d}"
        if key in h_dict:
            return int(h_dict[key])
        return 1 if d.weekday() >= 5 else 0

    def nearest_holiday_plan(
        self,
        today: date,
        *,
        min_days: int = 30,
        max_days: int = 45,
    ) -> dict[str, Any]:
        self._ensure_loaded()
        today_dt = datetime(today.year, today.month, today.day)
        seen: set[tuple[str, str]] = set()
        candidates: list[tuple[int, datetime, datetime, str, str]] = []

        for y in self._holiday_json:
            if y == "update_time":
                continue
            dates = self._holiday_json[y]
            if not isinstance(dates, dict):
                continue
            for m, t in dates.items():
                if int(t) != 2:
                    continue
                try:
                    d = datetime.strptime(f"{y}-{m[0:2]}-{m[2:]}", "%Y-%m-%d")
                except ValueError:
                    continue
                diff = (d.date() - today).days
                if diff > max_days:
                    continue

                start = d
                end = d
                while self.get_day_type(start.date()) != 0:
                    start -= timedelta(days=1)
                while self.get_day_type(end.date()) != 0:
                    end += timedelta(days=1)
                start += timedelta(days=1)
                end -= timedelta(days=1)

                period_key = (
                    start.strftime("%Y-%m-%d"),
                    end.strftime("%Y-%m-%d"),
                )
                if period_key in seen:
                    continue
                seen.add(period_key)

                if diff < min_days and not self._is_in_bridge_window(
                    start, end, today_dt
                ):
                    continue

                candidates.append((diff, start, end, y, m))

        if not candidates:
            return {}

        candidates.sort(key=lambda x: (x[0], x[1]))
        _, start, end, y, m = candidates[0]
        name = self._resolve_holiday_period_name(y, start, end, m)
        holiday_days = (end - start).days + 1
        detail: list[dict[str, Any]] = []
        before = self._build_bridge_plan(start, end, "before", today_dt)
        after = self._build_bridge_plan(start, end, "after", today_dt)
        if before:
            detail.append(
                {
                    "label": "向前拼",
                    "range": before["leave_range"],
                    "start": before["leave_start"],
                    "end": before["leave_end"],
                    "days": before["leave_days"],
                    "total_days": before["total_days"],
                    "calendar_days": before["calendar_days"],
                }
            )
        if after:
            detail.append(
                {
                    "label": "向后拼",
                    "range": after["leave_range"],
                    "start": after["leave_start"],
                    "end": after["leave_end"],
                    "days": after["leave_days"],
                    "total_days": after["total_days"],
                    "calendar_days": after["calendar_days"],
                }
            )
        return {
            "name": name,
            "days": holiday_days,
            "range_text": f"{start.month}/{start.day} - {end.month}/{end.day}",
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "detail": detail,
        }
    def update(self, *, force: bool = False) -> None:
        self._load_cache()
        if not self._fetch_enabled and not force:
            return
        if not force and not self._cache_expired():
            return
        self._fetch_from_server()

    async def async_update(self, hass: Any, *, force: bool = False) -> None:
        await hass.async_add_executor_job(
            lambda: self.update(force=force)
        )

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load_cache()
        if self._fetch_enabled and self._cache_expired():
            try:
                self._fetch_from_server()
            except Exception as err:
                _LOGGER.warning("holiday update failed: %s", err)
        self._loaded = True
    def _cache_expired(self) -> bool:
        update_date = self._holiday_json.get("update_time", "2000-01-01")
        try:
            last = datetime.strptime(str(update_date), "%Y-%m-%d").date()
        except ValueError:
            return True
        return (date.today() - last).days > self._cache_ttl_days

    def _load_cache(self) -> None:
        try:
            if self._cache_path.is_file():
                self._holiday_json = json.loads(
                    self._cache_path.read_text(encoding="utf-8")
                )
            else:
                self._holiday_json = {}
        except Exception as err:
            _LOGGER.debug("load holiday cache failed: %s", err)
            self._holiday_json = {}

    def _write_cache(self, data: dict[str, Any]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as err:
            _LOGGER.error("write holiday cache failed: %s", err)

    def _fetch_from_server(self) -> None:
        today = date.today()
        data: dict[str, Any] = {"update_time": today.strftime("%Y-%m-%d")}
        for i in range(_FETCH_MONTHS):
            month = today.month + i
            year = today.year
            if month > 12:
                year += 1
                month -= 12
            year_key = str(year)
            data.setdefault(year_key, {})
            try:
                self._fetch_one_month(year, month, data[year_key])
                time.sleep(0.5)
            except Exception as err:
                _LOGGER.warning(
                    "fetch holiday %d-%02d failed: %s", year, month, err
                )
        self._write_cache(data)
        self._holiday_json = data
        self._loaded = True

    def _fetch_one_month(
        self, year: int, month: int, year_dict: dict[str, Any]
    ) -> None:
        d = f"{year}{month:02d}"
        params = urllib.parse.urlencode({"d": d, "info": 1})
        url = f"{_BITEFU_API}?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "HomeAssistant"})
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
            _LOGGER.warning("fetch month %s failed: %s", d, err)
            return

        if d not in result:
            _LOGGER.warning("fetch month %s: empty response", d)
            return

        for key, info in result[d].items():
            t = int(info.get("type", 0))
            w = int(info.get("week2", 0))
            if t in (1, 2) or (w in (6, 7) and t == 0):
                year_dict[key] = str(t)

    def _is_in_bridge_window(
        self,
        holiday_start: datetime,
        holiday_end: datetime,
        today: datetime,
    ) -> bool:
        before_start = self._bridge_edge_date(holiday_start, "before")
        after_end = self._bridge_edge_date(holiday_end, "after")
        if before_start and before_start <= today <= holiday_end:
            return True
        if after_end and holiday_start <= today <= after_end:
            return True
        return False

    def _bridge_edge_date(
        self, anchor: datetime, direction: str
    ) -> datetime | None:
        step = -1 if direction == "before" else 1
        cursor = (
            anchor - timedelta(days=1)
            if direction == "before"
            else anchor + timedelta(days=1)
        )
        saw_workday = False
        while self.get_day_type(cursor.date()) == 0:
            saw_workday = True
            cursor += timedelta(days=step)
        if not saw_workday:
            return None
        edge = cursor - timedelta(days=step)
        while self.get_day_type(cursor.date()) != 0:
            edge = cursor
            cursor += timedelta(days=step)
        return edge

    def _build_bridge_plan(
        self,
        holiday_start: datetime,
        holiday_end: datetime,
        direction: str,
        today: datetime,
    ) -> dict[str, Any]:
        step = -1 if direction == "before" else 1
        cursor = (
            holiday_start - timedelta(days=1)
            if direction == "before"
            else holiday_end + timedelta(days=1)
        )

        leave_dates: list[datetime] = []
        while self.get_day_type(cursor.date()) == 0:
            leave_dates.append(cursor)
            cursor += timedelta(days=step)

        if not leave_dates:
            return {}

        extra_rest_dates: list[datetime] = []
        while self.get_day_type(cursor.date()) != 0:
            extra_rest_dates.append(cursor)
            cursor += timedelta(days=step)

        if direction == "before":
            leave_dates.reverse()
            extra_rest_dates.reverse()
            calendar_dates = extra_rest_dates + leave_dates
        else:
            calendar_dates = leave_dates + extra_rest_dates

        clip = today.replace(hour=0, minute=0, second=0, microsecond=0)
        if (
            direction == "before"
            and calendar_dates
            and holiday_start <= clip <= holiday_end
        ):
            calendar_dates = []
            leave_dates = []
            extra_rest_dates = []
        elif (
            direction == "before"
            and calendar_dates
            and calendar_dates[0] <= clip <= holiday_end
        ):
            calendar_dates = [d for d in calendar_dates if d >= clip]
            leave_dates = [d for d in leave_dates if d >= clip]
            extra_rest_dates = [d for d in extra_rest_dates if d >= clip]
        elif (
            direction == "after"
            and calendar_dates
            and holiday_start <= clip <= calendar_dates[-1]
        ):
            calendar_dates = [d for d in calendar_dates if d >= clip]
            leave_dates = [d for d in leave_dates if d >= clip]
            extra_rest_dates = [d for d in extra_rest_dates if d >= clip]

        if not calendar_dates:
            return {}

        leave_set = {d.strftime("%Y-%m-%d") for d in leave_dates}
        rest_set = {d.strftime("%Y-%m-%d") for d in extra_rest_dates}
        calendar_days: list[dict[str, Any]] = []
        for dt in calendar_dates:
            key = dt.strftime("%Y-%m-%d")
            if key in leave_set:
                tag, day_type = "请假", "leave"
            elif key in rest_set:
                tag, day_type = "休息", "rest"
            else:
                tag, day_type = "上班", "work"
            calendar_days.append(
                {
                    "key": key,
                    "label": f"{dt.month}/{dt.day}",
                    "tag": tag,
                    "type": day_type,
                }
            )

        return {
            "leave_range": self._format_date_range(leave_dates),
            "leave_start": leave_dates[0].strftime("%Y-%m-%d") if leave_dates else "",
            "leave_end": leave_dates[-1].strftime("%Y-%m-%d") if leave_dates else "",
            "leave_days": len(leave_dates),
            "total_days": len(calendar_days) + (holiday_end - holiday_start).days + 1,
            "calendar_days": calendar_days,
        }

    @staticmethod
    def _format_date_range(dates: list[datetime]) -> str:
        if not dates:
            return ""
        start, end = dates[0], dates[-1]
        return f"{start.month}/{start.day} - {end.month}/{end.day}"

    def _resolve_holiday_period_name(
        self,
        year: str,
        holiday_start: datetime,
        holiday_end: datetime,
        fallback_mmdd: str,
    ) -> str:
        current = holiday_start
        while current <= holiday_end:
            mmdd = current.strftime("%m%d")
            name = self._resolve_holiday_name(year, mmdd)
            if not re.fullmatch(r"\d+月\d+日", name):
                return name
            current += timedelta(days=1)
        return self._resolve_holiday_name(year, fallback_mmdd)

    def _resolve_holiday_name(self, year: str, mmdd: str) -> str:
        if mmdd in _HOLIDAY_NAMES:
            return _HOLIDAY_NAMES[mmdd]

        month = int(mmdd[:2])
        day = int(mmdd[2:])
        year_int = int(year)

        try:
            qingming_day = cal.get_term(year_int, 6)
            if month == 4 and day == qingming_day:
                return "清明节"
        except Exception:
            pass

        try:
            lunar = cal.solar2lunar(year_int, month, day)
            if isinstance(lunar, dict):
                l_m = int(lunar.get("lMonth", 0))
                l_d = int(lunar.get("lDay", 0))
                key = f"{l_m:02d}{l_d:02d}"
                if key in _LUNAR_HOLIDAY_NAMES:
                    return _LUNAR_HOLIDAY_NAMES[key]
        except Exception:
            pass

        return f"{month}月{day}日"
