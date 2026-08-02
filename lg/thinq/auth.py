"""Credentials and session/client factory for LG ThinQ Connect.

Auth is a static Personal Access Token (PAT) plus a self-assigned client id and a
country code -- no refresh flow, matching the "API key (static)" row of the auth
table in root CLAUDE.md (alongside UniFi and Cloudflare Radar). See
docs/plans/2026-08-02-lg-thinq-design.md for the full design.
"""

from __future__ import annotations

import os

import aiohttp
from thinqconnect import ThinQApi, ThinQAPIErrorCodes, ThinQAPIException

ONEPASSWORD_ITEM = "the 'LG ThinQ' item in the picklehome 1Password vault"

_REQUIRED_ENV_VARS = ("LG_THINQ_PAT", "LG_THINQ_CLIENT_ID", "LG_THINQ_COUNTRY")

# LG ThinQ error codes (thinqconnect.ThinQAPIErrorCodes) that mean the PAT
# itself was rejected, as opposed to a one-off request problem. thinqconnect's
# ThinQAPIException doesn't preserve the raw HTTP status (401/403) -- only
# LG's own JSON error code -- so that code is the best signal available for
# telling "your token is bad" apart from "this one request failed".
AUTH_ERROR_CODES = frozenset(
    {
        ThinQAPIErrorCodes.INVALID_TOKEN,
        ThinQAPIErrorCodes.INVALID_TOKEN_AGAIN,
        ThinQAPIErrorCodes.NOT_FOUND_TOKEN,
    }
)


class LGThinQConfigError(RuntimeError):
    """Raised when required LG ThinQ credentials are missing or blank.

    The client id in particular is self-assigned (LG never issues or validates
    it -- see the design doc's "The client id is self-assigned" section), so an
    empty value would silently reach LG as a blank x-client-id header rather
    than failing loudly. Validate here instead.
    """


def get_credentials() -> tuple[str, str, str]:
    """Read (pat, client_id, country) from the environment.

    Raises LGThinQConfigError naming the missing/blank variable(s) and pointing
    at the 1Password item, rather than letting an empty header reach LG.
    """
    values = {name: os.environ.get(name) for name in _REQUIRED_ENV_VARS}
    missing = [name for name, value in values.items() if not value or not value.strip()]
    if missing:
        raise LGThinQConfigError(
            f"{', '.join(missing)} not set (or blank). Check {ONEPASSWORD_ITEM}, "
            "then run 'just dotenv' to regenerate .env."
        )
    return values["LG_THINQ_PAT"], values["LG_THINQ_CLIENT_ID"], values["LG_THINQ_COUNTRY"]


async def connect() -> tuple[ThinQApi, aiohttp.ClientSession]:
    """Build an authenticated ThinQApi client.

    Returns (api, session). The caller owns the session's lifecycle and must
    close it (e.g. in a finally block) -- ThinQApi only holds a reference, it
    has no close() of its own.

    thinqconnect builds its own aiohttp session internally when one isn't
    supplied, and that default session ignores HTTP_PROXY/HTTPS_PROXY
    (trust_env=False), which breaks under the Claude Code sandbox's
    proxy-based network allowlisting (see root CLAUDE.md's Sandbox section).
    Passing a pre-built trust_env=True session here is the fix -- the same
    pattern birdfeeder/vicohome and climate/hisense use.
    """
    pat, client_id, country = get_credentials()
    session = aiohttp.ClientSession(trust_env=True)
    api = ThinQApi(session=session, access_token=pat, country_code=country, client_id=client_id)
    return api, session


def describe_auth_error(exc: ThinQAPIException) -> str | None:
    """If `exc` indicates the PAT was rejected, return a diagnostic message; else None.

    Distinguishes an authentication rejection (LG's equivalent of 401/403)
    from other API failures, naming the likely cause (expiry/revocation) and
    pointing at the 1Password item, so a bad token doesn't read as a generic
    error someone ends up re-discovering from scratch. client.py -- the only
    module that actually calls the SDK and can catch ThinQAPIException -- uses
    this to decide whether to raise LGThinQAuthError or a plain LGThinQError.
    """
    if exc.code not in AUTH_ERROR_CODES:
        return None
    return (
        f"LG rejected the request ({exc.error_name}). It may have expired or been revoked -- "
        f"check {ONEPASSWORD_ITEM}."
    )
