from __future__ import annotations

from typing import Any

import aiohttp

async def verify_backend_credentials(
    base_url: str,
    username: str,
    password: str,
    session_key: str,
) -> str | None:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{base_url}/status", timeout=timeout) as resp:
                if resp.status >= 500:
                    return "cannot_connect"
        except (aiohttp.ClientError, TimeoutError, OSError):
            return "cannot_connect"

        try:
            async with session.post(
                f"{base_url}/auth/ensure",
                json={
                    "session_key": session_key,
                    "username": username,
                    "password": password,
                },
                timeout=timeout,
            ) as resp:
                if resp.status >= 500:
                    return "cannot_connect"
                data: dict[str, Any] = await resp.json()
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError):
            return "cannot_connect"

        reason = str(data.get("reason") or "")
        if reason in ("INVALID_AUTH", "INVALID_CREDENTIALS"):
            return "invalid_auth"
        code = data.get("code", 0)
        if code in (401, 403):
            return "invalid_auth"
        return None
