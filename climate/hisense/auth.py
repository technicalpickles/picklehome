"""Credential loading and a sandbox-safe ConnectLife API client.

Hisense ductless HVAC is reached through the ConnectLife cloud via the
``connectlife`` library. Credentials come from 1Password -> ``.env`` (the same
username/password style as BlueAir/Yale). The library holds its tokens in
memory only and re-authenticates per session, so there is nothing to persist;
each CLI invocation logs in fresh.
"""

import os
import sys

import aiohttp
from connectlife.api import ConnectLifeApi


class SandboxConnectLifeApi(ConnectLifeApi):
    """ConnectLifeApi that respects HTTP_PROXY/HTTPS_PROXY.

    The library builds its own aiohttp session and defaults to
    ``trust_env=False``, so it ignores the proxy env vars. The Claude Code
    sandbox routes traffic through a local proxy for domain allowlisting, so we
    override the one session factory the class exposes to opt in. This is the
    same subclass-and-override trick climate/ecobee uses for token persistence.
    """

    def _client_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(timeout=self.request_timeout, trust_env=True)


def get_credentials() -> tuple[str, str]:
    username = os.environ.get("CONNECTLIFE_USERNAME")
    password = os.environ.get("CONNECTLIFE_PASSWORD")
    missing = []
    if not username:
        missing.append("CONNECTLIFE_USERNAME")
    if not password:
        missing.append("CONNECTLIFE_PASSWORD")
    if missing:
        print(f"{', '.join(missing)} not set. Run 'just dotenv' to generate .env.")
        sys.exit(1)
    return username, password
