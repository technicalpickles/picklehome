import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from garage.aladdin.auth import (
    get_credentials,
    load_tokens,
    save_tokens,
    _compute_secret_hash,
    COGNITO_CLIENT_ID,
    COGNITO_CLIENT_SECRET,
)


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


# --- Cognito auth tests ---


def test_compute_secret_hash():
    # Verify HMAC-SHA256 computation matches expected format
    result = _compute_secret_hash("test@example.com")
    assert isinstance(result, str)
    # Should be valid base64
    decoded = base64.b64decode(result)
    # HMAC-SHA256 produces 32 bytes
    assert len(decoded) == 32


def test_login_saves_tokens(tmp_path):
    token_path = tmp_path / "tokens.json"

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "AuthenticationResult": {
            "AccessToken": "cognito_access",
            "RefreshToken": "cognito_refresh",
            "IdToken": "cognito_id",
        }
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
            assert result["AccessToken"] == "cognito_access"
            tokens = load_tokens(token_path)
            assert tokens["access_token"] == "cognito_access"
            assert tokens["refresh_token"] == "cognito_refresh"

    asyncio.run(_run())


def test_refresh_saves_tokens(tmp_path):
    token_path = tmp_path / "tokens.json"

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "AuthenticationResult": {
            "AccessToken": "refreshed_access",
            "IdToken": "refreshed_id",
        }
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    async def _run():
        with patch("garage.aladdin.auth.aiohttp.ClientSession", return_value=mock_session):
            from garage.aladdin.auth import refresh, load_tokens
            result = await refresh("original_refresh", "user@example.com", token_path)
            assert result["AccessToken"] == "refreshed_access"
            tokens = load_tokens(token_path)
            assert tokens["access_token"] == "refreshed_access"
            # Refresh token should be preserved (Cognito doesn't return a new one)
            assert tokens["refresh_token"] == "original_refresh"

    asyncio.run(_run())
