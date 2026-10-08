import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from load_module import load

backend_check = load("backend_check.py")


def test_verify_invalid_auth():
    status_resp = MagicMock()
    status_resp.status = 200
    auth_resp = MagicMock()
    auth_resp.status = 200
    auth_resp.json = AsyncMock(return_value={"code": 401, "reason": "INVALID_AUTH"})

    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(return_value=status_resp), __aexit__=AsyncMock())
    )
    mock_session.post = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(return_value=auth_resp), __aexit__=AsyncMock())
    )

    with patch.object(
        backend_check.aiohttp,
        "ClientSession",
        return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()),
    ):
        assert (
            asyncio.run(backend_check.verify_backend_credentials("http://x", "u", "p", "k"))
            == "invalid_auth"
        )


def test_verify_ok():
    status_resp = MagicMock()
    status_resp.status = 200
    auth_resp = MagicMock()
    auth_resp.status = 200
    auth_resp.json = AsyncMock(return_value={"code": 0})

    mock_session = MagicMock()
    mock_session.get = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(return_value=status_resp), __aexit__=AsyncMock())
    )
    mock_session.post = MagicMock(
        return_value=MagicMock(__aenter__=AsyncMock(return_value=auth_resp), __aexit__=AsyncMock())
    )

    with patch.object(
        backend_check.aiohttp,
        "ClientSession",
        return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_session), __aexit__=AsyncMock()),
    ):
        assert asyncio.run(backend_check.verify_backend_credentials("http://x", "u", "p", "k")) is None
