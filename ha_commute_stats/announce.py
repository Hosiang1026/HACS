from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)


def flat_speech(message: str) -> str:
    text = str(message or "").replace("\\n", "\n").replace("\r", "\n")
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    return "，".join(parts)


def speech_text(title: str, message: str) -> str:
    head = flat_speech(title).rstrip("。.")
    body = flat_speech(message)
    if head and body:
        return f"{head}。{body}"
    return head or body


def _ids(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw] if "." in raw else []
    return [item for item in raw if isinstance(item, str) and "." in item]


def _platform(hass: HomeAssistant, entity_id: str) -> str | None:
    ent = er.async_get(hass).async_get(entity_id)
    if ent is None:
        return None
    return ent.platform


def _miot_player(hass: HomeAssistant, entity_id: str) -> bool:
    if not hass.services.has_service("xiaomi_miot", "intelligent_speaker"):
        return False
    data = hass.data.get("xiaomi_miot")
    if not isinstance(data, dict):
        return False
    entities = data.get("entities")
    if not isinstance(entities, dict):
        return False
    ent = entities.get(entity_id)
    if ent is None:
        for item in entities.values():
            if getattr(item, "entity_id", None) == entity_id:
                ent = item
                break
    return ent is not None and hasattr(ent, "async_intelligent_speaker")


def _play_text_notify(hass: HomeAssistant, entity_id: str) -> str | None:
    reg = er.async_get(hass)
    ent = reg.async_get(entity_id)
    if ent is None or not ent.device_id:
        return None
    for other in er.async_entries_for_device(reg, ent.device_id):
        if other.domain != "notify" or other.disabled_by is not None:
            continue
        if "play_text" in other.entity_id:
            return other.entity_id
    return None


def _failed(result: Any) -> bool:
    return isinstance(result, dict) and (
        result.get("result") is False or bool(result.get("error"))
    )


async def _call(
    hass: HomeAssistant,
    domain: str,
    service: str,
    data: dict[str, Any],
    target: dict[str, Any] | None = None,
) -> Any:
    try:
        return await hass.services.async_call(
            domain,
            service,
            data,
            target=target,
            blocking=True,
            return_response=True,
        )
    except ServiceValidationError:
        await hass.services.async_call(
            domain, service, data, target=target, blocking=True
        )
        return None


async def _tts(hass: HomeAssistant, player: str, text: str) -> bool:
    if hass.services.has_service("tts", "speak"):
        for tts_id in hass.states.async_entity_ids("tts"):
            try:
                await _call(
                    hass,
                    "tts",
                    "speak",
                    {"media_player_entity_id": player, "message": text},
                    {"entity_id": tts_id},
                )
                return True
            except Exception:
                _LOGGER.exception("tts.speak failed: %s", tts_id)
    for name in hass.services.async_services().get("tts", {}):
        if not name.endswith("_say"):
            continue
        try:
            await _call(
                hass,
                "tts",
                name,
                {"entity_id": player, "message": text},
            )
            return True
        except Exception:
            _LOGGER.exception("tts %s failed", name)
    return False


async def _xiaomi_play(hass: HomeAssistant, notify_id: str, text: str) -> None:
    await _call(
        hass,
        "notify",
        "send_message",
        {
            "entity_id": notify_id,
            "message": json.dumps([text], ensure_ascii=False),
        },
    )


async def _try(label: str, action) -> bool:
    try:
        return await action()
    except Exception:
        _LOGGER.exception("播报失败: %s", label)
        return False


async def _announce_one(hass: HomeAssistant, entity_id: str, text: str) -> bool:
    domain = entity_id.split(".", 1)[0]
    platform = _platform(hass, entity_id)
    if domain == "media_player" and _miot_player(hass, entity_id):

        async def _miot() -> bool:
            result = await _call(
                hass,
                "xiaomi_miot",
                "intelligent_speaker",
                {
                    "entity_id": entity_id,
                    "text": text,
                    "execute": False,
                    "silent": False,
                },
            )
            return not _failed(result)

        if await _try(entity_id, _miot):
            return True
    notify_id = entity_id if domain == "notify" and "play_text" in entity_id else None
    if notify_id is None and domain in ("media_player", "text", "input_text"):
        notify_id = _play_text_notify(hass, entity_id)
    if notify_id:

        async def _play() -> bool:
            await _xiaomi_play(hass, notify_id, text)
            return True

        if await _try(notify_id, _play):
            return True
    if domain in ("text", "input_text"):

        async def _set_text() -> bool:
            value = (
                json.dumps([text], ensure_ascii=False)
                if platform == "xiaomi_home"
                else text
            )
            await _call(
                hass,
                domain,
                "set_value",
                {"entity_id": entity_id, "value": value},
            )
            return True

        if await _try(entity_id, _set_text):
            return True
    if domain == "notify":

        async def _notify() -> bool:
            await _call(
                hass,
                "notify",
                "send_message",
                {"entity_id": entity_id, "message": text},
            )
            return True

        if await _try(entity_id, _notify):
            return True
    if domain == "media_player":
        return await _tts(hass, entity_id, text)
    return False


async def async_announce(hass: HomeAssistant, targets: Any, message: str) -> str | None:
    text = flat_speech(message)
    ids = _ids(targets)
    if not ids or not text:
        return "announce_empty"
    ok = False
    for entity_id in ids:
        try:
            if await _announce_one(hass, entity_id, text):
                ok = True
        except Exception:
            _LOGGER.exception("播报失败: %s", entity_id)
    if not ok:
        _LOGGER.warning("播报失败: %s", ids)
        return "announce_failed"
    return None
