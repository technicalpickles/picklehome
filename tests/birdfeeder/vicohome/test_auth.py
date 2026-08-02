import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from birdfeeder.vicohome.auth import get_credentials, login


def test_get_credentials_reads_env(monkeypatch):
    monkeypatch.setenv("VICOHOME_EMAIL", "someone@example.com")
    monkeypatch.setenv("VICOHOME_PASSWORD", "hunter2")
    monkeypatch.setenv("VICOHOME_REGION", "eu")

    email, password, region = get_credentials()

    assert email == "someone@example.com"
    assert password == "hunter2"
    assert region == "eu"


def test_get_credentials_defaults_region_to_us(monkeypatch):
    monkeypatch.setenv("VICOHOME_EMAIL", "someone@example.com")
    monkeypatch.setenv("VICOHOME_PASSWORD", "hunter2")
    monkeypatch.delenv("VICOHOME_REGION", raising=False)

    _email, _password, region = get_credentials()

    assert region == "us"


def test_get_credentials_exits_when_missing(monkeypatch):
    monkeypatch.delenv("VICOHOME_EMAIL", raising=False)
    monkeypatch.delenv("VICOHOME_PASSWORD", raising=False)

    with pytest.raises(SystemExit):
        get_credentials()


def _mock_session(response_body: dict):
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = AsyncMock(return_value=response_body)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    return mock_session


def test_login_returns_token_on_success():
    session = _mock_session({
        "result": 0,
        "msg": "Success",
        "data": {"token": {"token": "abc123"}},
    })

    async def _run():
        token = await login(session, "someone@example.com", "hunter2")
        assert token == "abc123"
        session.post.assert_called_once_with(
            "/account/login",
            json={"email": "someone@example.com", "password": "hunter2", "loginType": 0},
        )

    asyncio.run(_run())


def test_login_raises_on_failure():
    session = _mock_session({"result": -1, "msg": "invalid password", "data": None})

    async def _run():
        with pytest.raises(RuntimeError, match="invalid password"):
            await login(session, "someone@example.com", "wrong")

    asyncio.run(_run())
