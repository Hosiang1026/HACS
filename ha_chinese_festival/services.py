from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HolidayDailyCoordinator

SERVICE_GET_OVERVIEW = "get_overview"
SERVICE_DATE_CONTROL = "date_control"

ATTR_ACTION = "action"
ATTR_DATE = "date"
ACTIONS = ["today", "previous_day", "next_day", "select_date"]

DATE_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ACTION): vol.In(ACTIONS),
        vol.Optional(ATTR_DATE): vol.Any(cv.date, None),
    }
)


def _coordinator(hass: HomeAssistant) -> HolidayDailyCoordinator | None:
    domain_data = hass.data.get(DOMAIN) or {}
    for key, value in domain_data.items():
        if key == "lovelace_registered" or key.startswith("_"):
            continue
        if isinstance(value, HolidayDailyCoordinator):
            return value
    return None


async def async_setup_services(hass: HomeAssistant) -> None:
    if hass.data.get(DOMAIN, {}).get("_services_registered"):
        return

    async def handle_get_overview(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinator(hass)
        if not coordinator or not coordinator.data:
            return {}
        data = coordinator.data
        return {
            "solar_date": data.get("solar_date"),
            "lunar_date": data.get("lunar_date"),
            "weekday": data.get("weekday"),
            "day_type": data.get("day_type"),
            "day_name": data.get("day_name"),
            "next_name": data.get("next_name"),
            "next_days": data.get("next_days"),
            "festival_content": data.get("festival_content"),
            "almanac": data.get("almanac") or {},
            "today": data.get("today") or [],
            "next": data.get("next") or [],
            "holiday_plan": data.get("holiday_plan") or {},
            "ai_fortune": data.get("ai_fortune") or {},
        }

    async def handle_date_control(call: ServiceCall) -> dict[str, Any]:
        coordinator = _coordinator(hass)
        if not coordinator:
            return {"ok": False}
        action = call.data[ATTR_ACTION]
        selected = call.data.get(ATTR_DATE)
        current = coordinator.tap_date or dt_util.now().date()
        if action == "today":
            new_date = dt_util.now().date()
        elif action == "previous_day":
            new_date = current - timedelta(days=1)
        elif action == "next_day":
            new_date = current + timedelta(days=1)
        elif action == "select_date" and selected:
            if isinstance(selected, datetime):
                new_date = selected.date()
            else:
                new_date = selected
        else:
            return {"ok": False, "date": current.isoformat()}
        coordinator.set_tap_date(new_date)
        await coordinator.async_request_refresh()
        return {"ok": True, "date": new_date.isoformat()}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_OVERVIEW,
        handle_get_overview,
        schema=vol.Schema({}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DATE_CONTROL,
        handle_date_control,
        schema=DATE_CONTROL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.data.setdefault(DOMAIN, {})["_services_registered"] = True


async def async_unload_services(hass: HomeAssistant) -> None:
    if not hass.data.get(DOMAIN, {}).get("_services_registered"):
        return
    hass.services.async_remove(DOMAIN, SERVICE_GET_OVERVIEW)
    hass.services.async_remove(DOMAIN, SERVICE_DATE_CONTROL)
    hass.data[DOMAIN].pop("_services_registered", None)
