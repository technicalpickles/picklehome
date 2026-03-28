import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from garage.aladdin.auth import get_credentials, load_tokens, save_tokens


def test_save_and_load_tokens(tmp_path):
    token_path = tmp_path / "tokens.json"
    save_tokens("access123", "refresh456", token_path)
    tokens = load_tokens(token_path)
    assert tokens == {"access_token": "access123", "refresh_token": "refresh456"}


def test_load_tokens_missing_file(tmp_path):
    token_path = tmp_path / "nonexistent.json"
    assert load_tokens(token_path) is None


def test_token_file_permissions(tmp_path):
    token_path = tmp_path / "tokens.json"
    save_tokens("a", "b", token_path)
    assert token_path.stat().st_mode & 0o777 == 0o600


def test_save_tokens_creates_parent_dirs(tmp_path):
    token_path = tmp_path / "deep" / "nested" / "tokens.json"
    save_tokens("a", "b", token_path)
    assert token_path.exists()


def test_get_credentials_from_env(monkeypatch):
    monkeypatch.setenv("ALADDIN_EMAIL", "user@example.com")
    monkeypatch.setenv("ALADDIN_PASSWORD", "secret")
    email, password = get_credentials()
    assert email == "user@example.com"
    assert password == "secret"


def test_get_credentials_missing_email(monkeypatch):
    monkeypatch.delenv("ALADDIN_EMAIL", raising=False)
    monkeypatch.setenv("ALADDIN_PASSWORD", "secret")
    with pytest.raises(SystemExit):
        get_credentials()


def test_get_credentials_missing_password(monkeypatch):
    monkeypatch.setenv("ALADDIN_EMAIL", "user@example.com")
    monkeypatch.delenv("ALADDIN_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        get_credentials()


# --- AladdinAuth and login tests ---

from garage.aladdin.auth import AladdinAuth, API_URL, API_KEY


def test_aladdin_auth_returns_cached_token(tmp_path):
    session = MagicMock()
    auth = AladdinAuth(session, "valid_access_token", "refresh_token", tmp_path / "t.json")

    async def _run():
        token = await auth.async_get_access_token()
        assert token == "valid_access_token"

    asyncio.run(_run())


def test_aladdin_auth_init_sets_api_constants():
    session = MagicMock()
    auth = AladdinAuth(session, "tok", "ref")
    assert auth.host == API_URL
    assert auth.api_key == API_KEY


def test_login_saves_tokens(tmp_path):
    token_path = tmp_path / "tokens.json"

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "access_token": "new_access",
        "refresh_token": "new_refresh",
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _run():
        with patch("garage.aladdin.auth.aiohttp.ClientSession", return_value=mock_session):
            from garage.aladdin.auth import login, load_tokens
            result = await login("user@example.com", "pass", token_path)
            assert result["access_token"] == "new_access"
            tokens = load_tokens(token_path)
            assert tokens["access_token"] == "new_access"
            assert tokens["refresh_token"] == "new_refresh"

    asyncio.run(_run())
