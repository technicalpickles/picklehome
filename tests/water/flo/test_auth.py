import pytest

from water.flo.auth import MoenFloConfigError, get_credentials, use_sso


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


def test_use_sso_defaults_to_true_when_unset(monkeypatch):
    monkeypatch.delenv("FLO_USE_SSO", raising=False)
    assert use_sso() is True
