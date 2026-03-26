import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from climate.ecobee.auth import (
    DEFAULT_TOKEN_PATH,
    get_api_key,
    load_tokens,
    save_tokens,
    make_ecobee,
)


def test_default_token_path():
    """Token file lives in ~/.local/state/picklehome/."""
    assert "picklehome" in str(DEFAULT_TOKEN_PATH)
    assert DEFAULT_TOKEN_PATH.name == "ecobee-tokens.json"


def test_get_api_key_from_env(monkeypatch):
    monkeypatch.setenv("ECOBEE_API_KEY", "test-key-123")
    assert get_api_key() == "test-key-123"


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("ECOBEE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        get_api_key()


def test_save_and_load_tokens(tmp_path):
    token_path = tmp_path / "tokens.json"
    save_tokens("access-abc", "refresh-xyz", token_path)

    tokens = load_tokens(token_path)
    assert tokens == {"access_token": "access-abc", "refresh_token": "refresh-xyz"}


def test_load_tokens_missing_file(tmp_path):
    token_path = tmp_path / "nonexistent.json"
    assert load_tokens(token_path) is None


def test_save_tokens_creates_parent_dir(tmp_path):
    token_path = tmp_path / "sub" / "dir" / "tokens.json"
    save_tokens("a", "r", token_path)
    assert token_path.exists()


def test_token_file_not_world_readable(tmp_path):
    token_path = tmp_path / "tokens.json"
    save_tokens("a", "r", token_path)
    mode = token_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_make_ecobee_with_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("ECOBEE_API_KEY", "test-key")
    token_path = tmp_path / "tokens.json"
    save_tokens("access-tok", "refresh-tok", token_path)

    ecobee = make_ecobee(token_path=token_path)
    assert ecobee.api_key == "test-key"
    assert ecobee.refresh_token == "refresh-tok"


def test_make_ecobee_no_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("ECOBEE_API_KEY", "test-key")
    token_path = tmp_path / "nonexistent.json"

    with pytest.raises(SystemExit):
        make_ecobee(token_path=token_path)
