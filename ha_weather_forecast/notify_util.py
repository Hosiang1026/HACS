from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ANNOUNCE,
    CONF_ANNOUNCE_ENABLED,
    CONF_NOTIFY,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_END,
    CONF_NOTIFY_START,
)

_LOGGER = logging.getLogger(__name__)


def _parse_time(value: str | None, default: str) -> time:
    raw = value or default
    try:
        return time.fromisoformat(raw)
    except ValueError:
        return time.fromisoformat(default)


def in_notify_window(module_cfg: dict[str, Any], now: datetime | None = None) -> bool:
    now = now or dt_util.now()
    start = _parse_time(module_cfg.get(CONF_NOTIFY_START), "08:00:00")
    end = _parse_time(module_cfg.get(CONF_NOTIFY_END), "22:00:00")
    t = now.time().replace(tzinfo=None)
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def format_carousel(*lines: str) -> str:
    text = "\n".join(str(x) for x in lines if x is not None)
    return text.replace("\\n", "\n").strip()


async def async_send_notify(
    hass: HomeAssistant,
    entry_data: dict[str, Any],
    module_cfg: dict[str, Any],
    title: str,
    message: str,
    carousel: str | None = None,
) -> None:
    if not entry_data.get(CONF_NOTIFY_ENABLED, True):
        return
    if not module_cfg.get(CONF_NOTIFY_ENABLED, False):
        return
    if not in_notify_window(module_cfg):
        return

    message = str(message).replace("\\n", "\n").strip()
    carousel_text = format_carousel(carousel or message)
    sent = False
    for item in _as_list(entry_data.get(CONF_NOTIFY)):
        action = None
        data: dict[str, Any] = {}
        target = None
        if isinstance(item, str):
            action = item
        elif isinstance(item, dict):
            action = item.get("action") or item.get("service")
            data = dict(item.get("data") or {})
            target = item.get("target")
        if not action or "." not in action:
            continue
        data["title"] = title
        data["message"] = message
        domain, service = action.split(".", 1)
        try:
            if hass.services.has_service(domain, service):
                await hass.services.async_call(
                    domain, service, data, target=target, blocking=False
                )
                sent = True
            elif domain == "notify" and hass.states.get(action):
                await hass.services.async_call(
                    "notify",
                    "send_message",
                    {"entity_id": action, "title": title, "message": message},
                    blocking=False,
                )
                sent = True
        except Exception:  # noqa: BLE001
            _LOGGER.exception("notify failed: %s", action)

    if hass.services.has_service("ha_msg_notify", "carousel"):
        try:
            await hass.services.async_call(
                "ha_msg_notify",
                "carousel",
                {"content": carousel_text, "source": title},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("ha_msg_notify.carousel failed")
    elif not sent and hass.services.has_service("ha_msg_notify", "send"):
        try:
            await hass.services.async_call(
                "ha_msg_notify",
                "send",
                {
                    "title": title,
                    "message": message,
                    "content": carousel_text,
                    "source": title,
                    "carousel": True,
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("ha_msg_notify.send failed")

    if not module_cfg.get(CONF_ANNOUNCE_ENABLED):
        return
    text = f"{title}。{message}"
    for eid in _as_list(entry_data.get(CONF_ANNOUNCE)):
        if not isinstance(eid, str) or "." not in eid:
            continue
        domain = eid.split(".", 1)[0]
        try:
            if domain in ("text", "input_text"):
                await hass.services.async_call(
                    domain, "set_value", {"entity_id": eid, "value": text}, blocking=False
                )
            elif domain == "media_player":
                if hass.services.has_service("tts", "speak"):
                    tts_ids = hass.states.async_entity_ids("tts")
                    if not tts_ids:
                        continue
                    await hass.services.async_call(
                        "tts",
                        "speak",
                        {"media_player_entity_id": eid, "message": text},
                        target={"entity_id": tts_ids[0]},
                        blocking=False,
                    )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("announce failed: %s", eid)
