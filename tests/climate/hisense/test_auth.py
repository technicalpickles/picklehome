import pytest

from climate.hisense.auth import get_credentials


def test_get_credentials_from_env(monkeypatch):
    monkeypatch.setenv("CONNECTLIFE_USERNAME", "user@example.com")
    monkeypatch.setenv("CONNECTLIFE_PASSWORD", "s3cret")
    assert get_credentials() == ("user@example.com", "s3cret")


def test_get_credentials_missing_exits(monkeypatch):
    monkeypatch.delenv("CONNECTLIFE_USERNAME", raising=False)
    monkeypatch.delenv("CONNECTLIFE_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        get_credentials()
