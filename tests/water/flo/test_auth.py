import asyncio

import aiohttp
import pytest

import water.flo.auth as auth
from water.flo.auth import MoenFloConfigError, connect, get_credentials, use_sso


def _set_credentials(monkeypatch):
    monkeypatch.setenv("FLO_USERNAME", "a@b.com")
    monkeypatch.setenv("FLO_PASSWORD", "hunter2")


def test_returns_credentials_when_both_set(monkeypatch):
    monkeypatch.setenv("FLO_USERNAME", "a@b.com")
    monkeypatch.setenv("FLO_PASSWORD", "hunter2")
    assert get_credentials() == ("a@b.com", "hunter2")


def test_raises_naming_the_missing_variable(monkeypatch):
    monkeypatch.setenv("FLO_USERNAME", "a@b.com")
    monkeypatch.delenv("FLO_PASSWORD", raising=False)
    with pytest.raises(MoenFloConfigError, match="FLO_PASSWORD"):
        get_credentials()


def test_raises_naming_both_when_neither_is_set(monkeypatch):
    monkeypatch.delenv("FLO_USERNAME", raising=False)
    monkeypatch.delenv("FLO_PASSWORD", raising=False)
    with pytest.raises(MoenFloConfigError) as excinfo:
        get_credentials()
    assert "FLO_USERNAME" in str(excinfo.value)
    assert "FLO_PASSWORD" in str(excinfo.value)


def test_treats_blank_as_missing(monkeypatch):
    monkeypatch.setenv("FLO_USERNAME", "a@b.com")
    monkeypatch.setenv("FLO_PASSWORD", "   ")
    with pytest.raises(MoenFloConfigError, match="FLO_PASSWORD"):
        get_credentials()


def test_error_points_at_secret_entry_and_the_vault_item(monkeypatch):
    monkeypatch.delenv("FLO_USERNAME", raising=False)
    monkeypatch.delenv("FLO_PASSWORD", raising=False)
    with pytest.raises(MoenFloConfigError) as excinfo:
        get_credentials()
    assert "just secret-entry" in str(excinfo.value)
    assert "Moen Flo" in str(excinfo.value)


@pytest.mark.parametrize("raw,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("no", False), ("", False),
])
def test_use_sso_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("FLO_USE_SSO", raw)
    assert use_sso() is expected


def test_use_sso_defaults_to_false_when_unset(monkeypatch):
    monkeypatch.delenv("FLO_USE_SSO", raising=False)
    assert use_sso() is False


def test_connect_builds_session_with_trust_env(monkeypatch):
    _set_credentials(monkeypatch)

    async def fake_async_get_api(username, password, *, session, use_sso):
        return "fake-api"

    monkeypatch.setattr(auth, "async_get_api", fake_async_get_api)

    async def _run():
        api, session = await connect()
        try:
            assert session.trust_env is True
        finally:
            await session.close()

    asyncio.run(_run())


def test_connect_passes_use_sso_through(monkeypatch):
    _set_credentials(monkeypatch)
    monkeypatch.setenv("FLO_USE_SSO", "0")

    captured = {}

    async def fake_async_get_api(username, password, *, session, use_sso):
        captured["use_sso"] = use_sso
        return "fake-api"

    monkeypatch.setattr(auth, "async_get_api", fake_async_get_api)

    async def _run():
        _, session = await connect()
        await session.close()

    asyncio.run(_run())
    assert captured["use_sso"] is False


def test_connect_returns_api_and_the_session_it_built(monkeypatch):
    _set_credentials(monkeypatch)

    sentinel_api = object()
    seen = {}

    async def fake_async_get_api(username, password, *, session, use_sso):
        seen["session"] = session
        return sentinel_api

    monkeypatch.setattr(auth, "async_get_api", fake_async_get_api)

    async def _run():
        api, session = await connect()
        try:
            assert api is sentinel_api
            assert session is seen["session"]
            assert isinstance(session, aiohttp.ClientSession)
        finally:
            await session.close()

    asyncio.run(_run())


def test_connect_closes_session_and_reraises_unchanged_on_auth_failure(monkeypatch):
    _set_credentials(monkeypatch)

    class BoomError(RuntimeError):
        """Stand-in for an aioflo authentication failure (bad password, SSO down, etc.)."""

    seen = {}

    async def fake_async_get_api(username, password, *, session, use_sso):
        seen["session"] = session
        raise BoomError("bad password")

    monkeypatch.setattr(auth, "async_get_api", fake_async_get_api)

    async def _run():
        with pytest.raises(BoomError, match="bad password"):
            await connect()

    asyncio.run(_run())
    assert seen["session"].closed is True
