import pytest

from climate.blueair.auth import get_credentials, store_credentials


def test_get_credentials_from_env(monkeypatch):
    monkeypatch.setenv("BLUEAIR_USERNAME", "user@example.com")
    monkeypatch.setenv("BLUEAIR_PASSWORD", "s3cret")
    monkeypatch.setenv("BLUEAIR_REGION", "eu")

    assert get_credentials() == ("user@example.com", "s3cret", "eu")


def test_get_credentials_default_region(monkeypatch):
    monkeypatch.setenv("BLUEAIR_USERNAME", "user@example.com")
    monkeypatch.setenv("BLUEAIR_PASSWORD", "s3cret")
    monkeypatch.delenv("BLUEAIR_REGION", raising=False)

    assert get_credentials() == ("user@example.com", "s3cret", "us")


def test_get_credentials_missing_username(monkeypatch):
    monkeypatch.delenv("BLUEAIR_USERNAME", raising=False)
    monkeypatch.delenv("BLUEAIR_PASSWORD", raising=False)

    with pytest.raises(SystemExit):
        get_credentials()


def test_get_credentials_missing_password(monkeypatch):
    monkeypatch.setenv("BLUEAIR_USERNAME", "user@example.com")
    monkeypatch.delenv("BLUEAIR_PASSWORD", raising=False)

    with pytest.raises(SystemExit):
        get_credentials()


def test_store_credentials_prints_guidance(capsys):
    store_credentials("user", "pass", "us")
    output = capsys.readouterr().out
    assert "1Password" in output
