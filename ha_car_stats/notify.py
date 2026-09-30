from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .helpers import cfg_announce, cfg_notify_actions

_LOGGER = logging.getLogger(__name__)


def _append_notify_footer(message: str) -> str:
    stamp = dt_util.now().strftime("%Y-%m-%d %H:%M:%S")
    base = str(message).replace("\\n", "\n").strip()
    return f"{base}\n\n本通知 By 狂欢马克思\n通知时间: {stamp}"


async def send_announce(hass: HomeAssistant, entry: ConfigEntry, text: str, kind: str) -> None:
    players = cfg_announce(entry, kind)
    if not players or not text:
        return
    for eid in players:
        if not isinstance(eid, str) or "." not in eid:
            continue
        domain = eid.split(".", 1)[0]
        try:
            if domain in ("text", "input_text"):
                await hass.services.async_call(
                    domain, "set_value", {"entity_id": eid, "value": text}, blocking=True
                )
            elif domain == "media_player":
                if hass.services.has_service("xiaomi_miot", "intelligent_speaker"):
                    await hass.services.async_call(
                        "xiaomi_miot",
                        "intelligent_speaker",
                        {"entity_id": eid, "text": text, "execute": False, "silent": False},
                        blocking=True,
                    )
                elif hass.services.has_service("tts", "speak"):
                    tts_ids = hass.states.async_entity_ids("tts")
                    if not tts_ids:
                        continue
                    await hass.services.async_call(
                        "tts",
                        "speak",
                        {"media_player_entity_id": eid, "message": text},
                        target={"entity_id": tts_ids[0]},
                        blocking=True,
                    )
        except Exception:
            _LOGGER.exception("announce failed: %s", eid)


async def send_notify(hass: HomeAssistant, entry: ConfigEntry, title: str, message: str, kind: str) -> bool:
    raw = cfg_notify_actions(entry, kind)
    notify_message = _append_notify_footer(message)
    if not raw:
        sent = True
    elif isinstance(raw, (str, dict)):
        items = [raw]
        sent = False
    else:
        items = list(raw)
        sent = False
    any_target = False
    if raw:
        for item in items:
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
            any_target = True
            data["title"] = title
            data["message"] = notify_message
            domain, service = action.split(".", 1)
            try:
                if hass.services.has_service(domain, service):
                    await hass.services.async_call(
                        domain, service, data, target=target, blocking=True
                    )
                    sent = True
                elif domain == "notify" and hass.states.get(action):
                    await hass.services.async_call(
                        "notify",
                        "send_message",
                        {"entity_id": action, "title": title, "message": notify_message},
                        blocking=True,
                    )
                    sent = True
                else:
                    _LOGGER.warning("notify service missing: %s", action)
            except Exception:
                _LOGGER.exception("notify failed: %s", action)
    text = f"{title}，{message.replace(chr(10), '，')}"
    await send_announce(hass, entry, text, kind)
    return sent if any_target else True
