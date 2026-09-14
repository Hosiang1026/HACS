from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACW_TC,
    CONF_ADDRESSAPI_KEY,
    CONF_AMAP_KEY,
    CONF_AMAP_PARAMDATA,
    CONF_AMAP_SESSIONID,
    CONF_JSESSIONID,
    CONF_PRIVATE_KEY,
    CONF_URL,
    DOMAIN,
)
from .coordinator import CarStatsCoordinator

TO_REDACT = {
    CONF_ACCESS_TOKEN,
    CONF_JSESSIONID,
    CONF_ACW_TC,
    CONF_URL,
    CONF_AMAP_KEY,
    CONF_AMAP_SESSIONID,
    CONF_AMAP_PARAMDATA,
    CONF_ADDRESSAPI_KEY,
    CONF_PRIVATE_KEY,
    "jsessionid",
    "api_key",
    "private_key",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: CarStatsCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    data: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        }
    }
    if coordinator and coordinator.data:
        data["coordinator"] = {
            "session": (coordinator.data or {}).get("session"),
            "stats": (coordinator.data or {}).get("stats"),
            "vehicle_plate": ((coordinator.data or {}).get("vehicle") or {}).get("plate"),
            "violations_count": ((coordinator.data or {}).get("violations") or {}).get("count"),
        }
    amap = getattr(coordinator, "amap_coordinator", None) if coordinator else None
    if amap and amap.data:
        attrs = (amap.data.get("attrs") or {})
        data["amap"] = {
            "tid": getattr(amap, "tid", None),
            "status": amap.data.get("status"),
            "onlinestatus": attrs.get("onlinestatus"),
            "naviStatus": attrs.get("naviStatus"),
            "querytime": attrs.get("querytime"),
            "last_update_success": amap.last_update_success,
        }
    return data
