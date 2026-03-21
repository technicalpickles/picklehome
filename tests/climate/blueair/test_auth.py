from unittest.mock import call, patch

import pytest

from climate.blueair.auth import KEYCHAIN_SERVICE, get_credentials, store_credentials


def test_keychain_service_name():
    assert KEYCHAIN_SERVICE == "picklehome-blueair"


@patch("climate.blueair.auth.keyring")
def test_store_credentials(mock_keyring):
    store_credentials("user@example.com", "s3cret", "eu")

    assert mock_keyring.set_password.call_count == 3
    mock_keyring.set_password.assert_has_calls(
        [
            call(KEYCHAIN_SERVICE, "username", "user@example.com"),
            call(KEYCHAIN_SERVICE, "password", "s3cret"),
            call(KEYCHAIN_SERVICE, "region", "eu"),
        ]
    )


@patch("climate.blueair.auth.keyring")
def test_get_credentials_success(mock_keyring):
    mock_keyring.get_password.side_effect = lambda svc, key: {
        "username": "user@example.com",
        "password": "s3cret",
        "region": "eu",
    }[key]

    result = get_credentials()
    assert result == ("user@example.com", "s3cret", "eu")


@patch("climate.blueair.auth.keyring")
def test_get_credentials_default_region(mock_keyring):
    mock_keyring.get_password.side_effect = lambda svc, key: {
        "username": "user@example.com",
        "password": "s3cret",
        "region": None,
    }[key]

    result = get_credentials()
    assert result == ("user@example.com", "s3cret", "us")


@patch("climate.blueair.auth.keyring")
def test_get_credentials_missing_username(mock_keyring):
    mock_keyring.get_password.return_value = None

    with pytest.raises(SystemExit):
        get_credentials()


@patch("climate.blueair.auth.keyring")
def test_get_credentials_missing_password(mock_keyring):
    mock_keyring.get_password.side_effect = lambda svc, key: {
        "username": "user@example.com",
        "password": None,
        "region": "us",
    }[key]

    with pytest.raises(SystemExit):
        get_credentials()
