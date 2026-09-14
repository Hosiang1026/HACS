from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import (
    DOMAIN,
    STATE_HOLIDAY,
    STATE_REPAIR,
    STATE_REST,
    STATE_WEEKEND,
    STATE_WORKDAY,
)
from .coordinator import HolidayDailyCoordinator

_LOGGER = logging.getLogger(__name__)

_DAY_TYPE_CN = {
    STATE_WORKDAY: "工作日",
    STATE_HOLIDAY: "节假日",
    STATE_WEEKEND: "周末",
    STATE_REST: "休息日",
    STATE_REPAIR: "补班",
}
_SENTENCE_LANGS = ("zh-cn",)
_INTENTS_SRC = Path(__file__).parent / "intents.yaml"


def _coordinator(hass: HomeAssistant) -> HolidayDailyCoordinator | None:
    domain_data = hass.data.get(DOMAIN) or {}
    for key, value in domain_data.items():
        if key == "lovelace_registered" or key.startswith("_"):
            continue
        if isinstance(value, HolidayDailyCoordinator):
            return value
    return None


def _install_sentences(hass: HomeAssistant) -> None:
    if not _INTENTS_SRC.is_file():
        return
    raw = _INTENTS_SRC.read_text(encoding="utf-8")
    for lang in _SENTENCE_LANGS:
        dest_dir = Path(hass.config.path("custom_sentences", lang))
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{DOMAIN}.yaml"
        body = raw
        if body.startswith('language:'):
            lines = body.splitlines()
            lines[0] = f'language: "{lang}"'
            body = "\n".join(lines) + ("\n" if raw.endswith("\n") else "")
        try:
            dest.write_text(body, encoding="utf-8")
        except OSError:
            _LOGGER.warning("install sentences failed: %s", dest)


async def async_setup_intents(hass: HomeAssistant) -> None:
    if hass.data.get(DOMAIN, {}).get("_intents_registered"):
        return
    await hass.async_add_executor_job(_install_sentences, hass)
    intent.async_register(hass, QueryHolidayIntent())
    intent.async_register(hass, QueryAlmanacIntent())
    intent.async_register(hass, QueryEventIntent())
    hass.data.setdefault(DOMAIN, {})["_intents_registered"] = True


class QueryHolidayIntent(intent.IntentHandler):
    intent_type = "查询节假日"
    description = "查询节假日信息，包括春节、元旦、清明、端午、中秋、国庆、劳动节、过年、放假、调休等"
    slot_schema = {
        vol.Optional("keyword", description="节日关键词如春节、过年、放假"): str
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        keyword = slots.get("keyword", {}).get("value", "") or ""
        synonyms = {
            "过年": "春节",
            "新年": "春节",
            "五一": "劳动节",
            "十一": "国庆",
            "鬼节": "中元",
            "月饼节": "中秋",
            "粽子节": "端午",
        }
        search = [keyword]
        if keyword in synonyms:
            search.append(synonyms[keyword])
        coordinator = _coordinator(hass)
        data = (coordinator.data if coordinator else None) or {}
        parts: list[str] = []
        solar = data.get("solar_date") or ""
        lunar = data.get("lunar_date") or ""
        parts.append(f"今天是{solar}，农历{lunar}。")
        day_name = data.get("day_name") or ""
        day_type = data.get("day_type") or ""
        if day_name:
            parts.append(f"今日{day_name}。")
        elif day_type:
            parts.append(f"今日{_DAY_TYPE_CN.get(day_type, day_type)}。")
        plan = data.get("holiday_plan") or {}
        if plan.get("name"):
            parts.append(
                f"最近假期{plan.get('name')}，还有{plan.get('days', '')}天。"
            )
        next_name = data.get("next_name")
        next_days = data.get("next_days")
        if next_name is not None and next_days is not None:
            parts.append(f"距离{next_name}还有{next_days}天。")
        if keyword:
            matched = False
            for item in data.get("next") or []:
                name = str(item.get("name") or "")
                if any(kw and kw in name for kw in search):
                    parts.append(f"{name}还有{item.get('days')}天。")
                    matched = True
            for item in data.get("today") or []:
                name = str(item.get("todayName") or "")
                if any(kw and kw in name for kw in search):
                    parts.append(f"今天是{name}。")
                    matched = True
            if not matched:
                parts.append(f"未找到与{keyword}相关的节日。")
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech("".join(parts))
        return response


class QueryAlmanacIntent(intent.IntentHandler):
    intent_type = "查询黄历"
    description = "查询传统历法信息，包括农历、八字、节气、宜忌、黄历等"
    slot_schema = {
        vol.Optional("date", description="查询日期YYYY-MM-DD格式"): str
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        date_str = slots.get("date", {}).get("value")
        coordinator = _coordinator(hass)
        restored = False
        if date_str and coordinator:
            try:
                from datetime import datetime

                query_date = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
                old = coordinator.tap_date
                coordinator.set_tap_date(query_date)
                await coordinator.async_request_refresh()
                restored = True
            except ValueError:
                query_date = None
        else:
            query_date = None
        data = (coordinator.data if coordinator else None) or {}
        almanac = data.get("almanac") or {}
        solar = data.get("solar_date") or ""
        lunar = data.get("lunar_date") or ""
        weekday = data.get("weekday") or ""
        if query_date:
            result = f"{query_date.year}年{query_date.month}月{query_date.day}日"
            tap_lunar = ((data.get("month_grid") or {}).get("tap_lunar") or {}).get(
                "full"
            ) or lunar
            result += f"是农历{tap_lunar}，{weekday}。"
        else:
            result = f"今天是{solar}，农历{lunar}，{weekday}。"
        term = data.get("term") or almanac.get("solar_term")
        if term:
            result += f"节气是{term}。"
        yi = almanac.get("suit")
        ji = almanac.get("avoid")
        if yi:
            result += f"宜{yi}。"
        if ji:
            result += f"忌{ji}。"
        if restored and coordinator:
            from homeassistant.util import dt as dt_util

            coordinator.set_tap_date(old if old else dt_util.now().date())
            await coordinator.async_request_refresh()
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(result)
        return response


class QueryEventIntent(intent.IntentHandler):
    intent_type = "查询事项"
    description = "查询生日提醒和纪念日提醒"
    slot_schema: dict[str, Any] = {}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        hass = intent_obj.hass
        coordinator = _coordinator(hass)
        data = (coordinator.data if coordinator else None) or {}
        opts = coordinator.options if coordinator else {}
        parts: list[str] = []
        for item in opts.get("birthdays") or []:
            if isinstance(item, dict) and item.get("name"):
                parts.append(f"{item.get('name')}生日是{item.get('date')}")
        for item in opts.get("anniversaries") or []:
            if isinstance(item, dict) and item.get("name"):
                parts.append(f"{item.get('name')}纪念日是{item.get('date')}")
        bday = (data.get("next_by_category") or {}).get("birthday") or {}
        if bday.get("name") is not None and bday.get("days") is not None:
            parts.append(f"下一生日是{bday['name']}，还有{bday['days']}天")
        anni = (data.get("next_by_category") or {}).get("anniversary") or {}
        if anni.get("name") is not None and anni.get("days") is not None:
            parts.append(f"下一纪念日是{anni['name']}，还有{anni['days']}天")
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech("，".join(parts) if parts else "暂无配置生日或纪念日")
        return response
