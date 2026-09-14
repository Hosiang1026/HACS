from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_AI_API_KEY,
    CONF_AI_API_URL,
    CONF_AI_MODEL,
    DEFAULT_AI_API_KEY,
    DEFAULT_AI_API_URL,
    DEFAULT_AI_MODEL,
)

_LOGGER = logging.getLogger(__name__)


async def fetch_ai_fortune(
    hass: HomeAssistant,
    opts: dict[str, Any],
    birthday_item: dict[str, Any] | None,
    today_almanac: dict[str, Any] | None,
) -> str:
    api_key = str(opts.get(CONF_AI_API_KEY) or DEFAULT_AI_API_KEY).strip()
    if not api_key:
        return ""
    api_url = str(opts.get(CONF_AI_API_URL) or DEFAULT_AI_API_URL).rstrip("/")
    model = str(opts.get(CONF_AI_MODEL) or DEFAULT_AI_MODEL)
    name = ""
    birthday = ""
    if birthday_item:
        name = str(birthday_item.get("name") or "")
        birthday = str(birthday_item.get("date") or "")
    almanac = today_almanac or {}
    yi = almanac.get("suit") or ""
    ji = almanac.get("avoid") or ""
    ba_zi = almanac.get("eight_char") or ""
    prompt = (
        f"请为{name or '某人'}进行今日运势预测。\n"
        f"姓名：{name or '未知'}\n"
        f"生日：{birthday or '未知'}\n"
        f"今日干支/八字相关：{ba_zi}\n"
        f"今日宜：{yi}\n"
        f"今日忌：{ji}\n"
        "请从运势、财运、感情、健康、工作等方面给出简洁预测，控制在240字以内，纯文本。"
    )
    try:
        from aiohttp import ClientTimeout
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(hass)
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with session.post(
            f"{api_url}/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=ClientTimeout(total=60),
        ) as resp:
            if resp.status >= 400:
                return ""
            data = await resp.json(content_type=None)
        choices = data.get("choices") or []
        if not choices:
            return ""
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        return str(content).strip() if content else ""
    except Exception:
        _LOGGER.warning("fetch_ai_fortune failed", exc_info=True)
        return ""
