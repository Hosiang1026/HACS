from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.notify.const import ATTR_MESSAGE, ATTR_TITLE
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import MsgNotifyCoordinator

ACTION_SEND = "send"

ACTION_TYPES = {ACTION_SEND}

ACTION_SCHEMA = cv.DEVICE_ACTION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(ACTION_TYPES),
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Required(ATTR_MESSAGE): cv.string,
    }
)


def _resolve_channel(
    hass: HomeAssistant, device_id: str
) -> tuple[MsgNotifyCoordinator, str] | None:
    device = dr.async_get(hass).async_get(device_id)
    if not device:
        return None
    domain_data = hass.data.get(DOMAIN) or {}
    for ident_domain, ident in device.identifiers:
        if ident_domain != DOMAIN:
            continue
        for entry_id, data in domain_data.items():
            coordinator: MsgNotifyCoordinator | None = data.get("coordinator")
            if not coordinator:
                continue
            prefix = f"{entry_id}_"
            if not ident.startswith(prefix):
                continue
            channel_id = ident[len(prefix) :]
            if coordinator.channel_by_id(channel_id):
                return coordinator, channel_id
    return None


async def async_get_actions(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    if not _resolve_channel(hass, device_id):
        return []
    return [
        {
            CONF_DEVICE_ID: device_id,
            CONF_DOMAIN: DOMAIN,
            CONF_TYPE: ACTION_SEND,
        }
    ]


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: dict[str, Any],
    variables: dict[str, Any],
    context: Context | None,
) -> None:
    resolved = _resolve_channel(hass, config[CONF_DEVICE_ID])
    if not resolved:
        return
    coordinator, channel_id = resolved
    await coordinator.async_send(
        title=config.get(ATTR_TITLE),
        message=config.get(ATTR_MESSAGE, ""),
        channels=[channel_id],
    )


async def async_get_action_capabilities(
    hass: HomeAssistant, config: dict[str, Any]
) -> dict[str, vol.Schema]:
    return {
        "extra_fields": vol.Schema(
            {
                vol.Optional(ATTR_TITLE): cv.string,
                vol.Required(ATTR_MESSAGE): cv.string,
            }
        )
    }
