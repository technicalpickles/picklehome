import asyncio

import pytest
from thinqconnect import ThinQAPIException

from lg.thinq.auth import LGThinQConfigError, connect, describe_auth_error, get_credentials


def test_get_credentials_reads_env(monkeypatch):
    monkeypatch.setenv("LG_THINQ_PAT", "some-pat")
    monkeypatch.setenv("LG_THINQ_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("LG_THINQ_COUNTRY", "US")

    pat, client_id, country = get_credentials()

    assert pat == "some-pat"
    assert client_id == "some-client-id"
    assert country == "US"


def test_get_credentials_raises_when_missing(monkeypatch):
    monkeypatch.delenv("LG_THINQ_PAT", raising=False)
    monkeypatch.delenv("LG_THINQ_CLIENT_ID", raising=False)
    monkeypatch.delenv("LG_THINQ_COUNTRY", raising=False)

    with pytest.raises(LGThinQConfigError, match="LG_THINQ_PAT"):
        get_credentials()


def test_get_credentials_raises_when_blank(monkeypatch):
    monkeypatch.setenv("LG_THINQ_PAT", "  ")
    monkeypatch.setenv("LG_THINQ_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("LG_THINQ_COUNTRY", "US")

    with pytest.raises(LGThinQConfigError, match="LG_THINQ_PAT"):
        get_credentials()


def test_get_credentials_error_names_1password_item(monkeypatch):
    monkeypatch.delenv("LG_THINQ_PAT", raising=False)
    monkeypatch.setenv("LG_THINQ_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("LG_THINQ_COUNTRY", "US")

    with pytest.raises(LGThinQConfigError, match="LG ThinQ.*picklehome"):
        get_credentials()


def test_get_credentials_reports_all_missing_vars(monkeypatch):
    monkeypatch.delenv("LG_THINQ_PAT", raising=False)
    monkeypatch.delenv("LG_THINQ_CLIENT_ID", raising=False)
    monkeypatch.setenv("LG_THINQ_COUNTRY", "US")

    with pytest.raises(LGThinQConfigError) as exc_info:
        get_credentials()

    message = str(exc_info.value)
    assert "LG_THINQ_PAT" in message
    assert "LG_THINQ_CLIENT_ID" in message
    assert "LG_THINQ_COUNTRY" not in message


def test_connect_builds_session_with_trust_env(monkeypatch):
    monkeypatch.setenv("LG_THINQ_PAT", "some-pat")
    monkeypatch.setenv("LG_THINQ_CLIENT_ID", "some-client-id")
    monkeypatch.setenv("LG_THINQ_COUNTRY", "US")

    async def _run():
        api, session = await connect()
        try:
            assert session.trust_env is True
        finally:
            await session.close()

    asyncio.run(_run())


def test_connect_raises_config_error_without_credentials(monkeypatch):
    monkeypatch.delenv("LG_THINQ_PAT", raising=False)
    monkeypatch.delenv("LG_THINQ_CLIENT_ID", raising=False)
    monkeypatch.delenv("LG_THINQ_COUNTRY", raising=False)

    async def _run():
        with pytest.raises(LGThinQConfigError):
            await connect()

    asyncio.run(_run())


def test_describe_auth_error_for_invalid_token():
    exc = ThinQAPIException(code="1103", message="invalid token", headers={})
    message = describe_auth_error(exc)
    assert message is not None
    assert "1Password" in message
    assert "expired" in message or "revoked" in message


def test_describe_auth_error_for_invalid_token_again():
    exc = ThinQAPIException(code="1218", message="invalid token again", headers={})
    assert describe_auth_error(exc) is not None


def test_describe_auth_error_for_not_found_token():
    exc = ThinQAPIException(code="1302", message="token not found", headers={})
    assert describe_auth_error(exc) is not None


def test_describe_auth_error_returns_none_for_unrelated_error():
    exc = ThinQAPIException(code="2000", message="internal server error", headers={})
    assert describe_auth_error(exc) is None
