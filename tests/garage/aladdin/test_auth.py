import json

import pytest

from garage.aladdin.auth import load_tokens, save_tokens


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
