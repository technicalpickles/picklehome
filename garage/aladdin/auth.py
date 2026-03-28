import json
import os
import sys
from pathlib import Path

import aiohttp
from genie_partner_sdk.auth import Auth

# OAuth/API constants (from erikreedstrom/aladdin_connect HA integration)
API_URL = "https://twdvzuefzh.execute-api.us-east-2.amazonaws.com/v1"
API_KEY = "k6QaiQmcTm2zfaNns5L1Z8duBtJmhDOW8JawlCC3"
OAUTH2_TOKEN_URL = "https://twdvzuefzh.execute-api.us-east-2.amazonaws.com/v1/oauth2/token"


def _default_token_path() -> Path:
    env_path = os.environ.get("ALADDIN_TOKEN_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "state" / "picklehome" / "aladdin-tokens.json"


DEFAULT_TOKEN_PATH = _default_token_path()


def load_tokens(token_path: Path = DEFAULT_TOKEN_PATH) -> dict | None:
    if not token_path.exists():
        return None
    with open(token_path) as f:
        return json.load(f)


def save_tokens(access_token: str, refresh_token: str, token_path: Path = DEFAULT_TOKEN_PATH) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"access_token": access_token, "refresh_token": refresh_token}
    with open(token_path, "w") as f:
        json.dump(data, f, indent=2)
    token_path.chmod(0o600)


def get_credentials() -> tuple[str, str]:
    email = os.environ.get("ALADDIN_EMAIL")
    password = os.environ.get("ALADDIN_PASSWORD")
    missing = []
    if not email:
        missing.append("ALADDIN_EMAIL")
    if not password:
        missing.append("ALADDIN_PASSWORD")
    if missing:
        print(f"{', '.join(missing)} not set. Run 'just dotenv' to generate .env.")
        sys.exit(1)
    return email, password


class AladdinAuth(Auth):
    """Auth subclass that persists tokens to a local JSON file."""

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        access_token: str,
        refresh_token: str,
        token_path: Path = DEFAULT_TOKEN_PATH,
    ):
        super().__init__(websession, API_URL, access_token, API_KEY)
        self._refresh_token = refresh_token
        self._token_path = token_path

    async def async_get_access_token(self) -> str:
        return self.access_token

    async def refresh_access_token(self) -> str:
        """Exchange refresh token for new access token."""
        async with self.websession.post(
            OAUTH2_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            headers={"x-api-key": API_KEY},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        self.access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        save_tokens(self.access_token, self._refresh_token, self._token_path)
        return self.access_token


async def login(email: str, password: str, token_path: Path = DEFAULT_TOKEN_PATH) -> dict:
    """Authenticate with Genie OAuth and save tokens."""
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.post(
            OAUTH2_TOKEN_URL,
            json={
                "grant_type": "password",
                "email": email,
                "password": password,
            },
            headers={"x-api-key": API_KEY},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Aladdin login failed (HTTP {resp.status}): {body}")
            data = await resp.json()
    access_token = data["access_token"]
    refresh_token = data["refresh_token"]
    save_tokens(access_token, refresh_token, token_path)
    return data
