"""Credentials and client factory for the Moen Flo shutoff valve.

Username/password to a session token, matching the "Username/password to session
token" row of the auth table in root CLAUDE.md -- except that aioflo holds the
token in memory for the life of the process rather than caching it to disk, so
there is no ~/.local/state/picklehome/ token file here. A CLI invocation
authenticates once and exits.

See docs/plans/2026-09-04-moen-flo-design.md for the full design.
"""

from __future__ import annotations

import os

import aiohttp
from aioflo import async_get_api
from aioflo.api import API

ONEPASSWORD_ITEM = "the 'Moen Flo' item in the picklehome 1Password vault"

_REQUIRED_ENV_VARS = ("FLO_USERNAME", "FLO_PASSWORD")
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class MoenFloConfigError(RuntimeError):
    """Raised when Flo credentials are missing or blank.

    Named MoenFlo* rather than Flo* because aioflo already exports its own
    FloError base class (aioflo/errors.py); sharing the prefix invites an
    import collision that reads as a subtle bug.
    """


def get_credentials() -> tuple[str, str]:
    """Read (username, password) from the environment.

    Raises MoenFloConfigError naming every missing or blank variable, and
    pointing at both credential paths: `just secret-entry` for right now, and
    the 1Password item once it exists.
    """
    values = {name: os.environ.get(name) for name in _REQUIRED_ENV_VARS}
    missing = [name for name, value in values.items() if not value or not value.strip()]
    if missing:
        raise MoenFloConfigError(
            f"{', '.join(missing)} not set (or blank). Run "
            f"'just secret-entry {' '.join(missing)}' to enter them now, or create "
            f"{ONEPASSWORD_ITEM}, un-comment the FLO_* lines in .env.template, and "
            "run 'just dotenv'."
        )
    return values["FLO_USERNAME"], values["FLO_PASSWORD"]


def use_sso() -> bool:
    """Whether to authenticate via Moen SSO (Cognito) instead of the legacy flow.

    Defaults to False. Determined empirically against the live account on
    2026-09-04: SSO (Cognito) authentication fails, while aioflo's legacy
    users/auth flow works. Set FLO_USE_SSO=1 to opt back into SSO, in case a
    different (e.g. newer) account needs it.
    """
    raw = os.environ.get("FLO_USE_SSO")
    if raw is None:
        return False
    return raw.strip().lower() in _TRUTHY


async def connect() -> tuple[API, aiohttp.ClientSession]:
    """Build an authenticated aioflo API client.

    Returns (api, session). The caller owns the session on success and must
    close it in a finally block -- aioflo only holds a reference.

    The session is built with trust_env=True so it honours HTTP_PROXY/HTTPS_PROXY.
    aioflo's own fallback session does not, which breaks under the Claude Code
    sandbox's proxy-based allowlisting (root CLAUDE.md, Sandbox). Same pattern as
    lg/thinq/auth.py and climate/hisense/auth.py.

    Unlike ThinQApi's constructor (lg/thinq/auth.py), async_get_api is not a
    plain constructor -- it awaits api.async_authenticate() internally, a real
    network call that can fail (bad password, wrong auth flow, Moen down). If
    it raises, this closes the session before re-raising the exception
    unchanged, so a failed connect() never leaks a session with nobody holding
    a handle to close it. Without this, the caller's "I own the session" only
    holds on the success path.
    """
    username, password = get_credentials()
    session = aiohttp.ClientSession(trust_env=True)
    try:
        api = await async_get_api(username, password, session=session, use_sso=use_sso())
    except BaseException:
        await session.close()
        raise
    return api, session
