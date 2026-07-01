"""OAuth loopback flow for the Google Smart Device Management API.

SDM authorization is two distinct steps. First, a one-time "partner
connections" URL (not the standard Google OAuth authorize endpoint) is where
the account owner picks which structures to share with our Device Access
project -- see nest/README.md for the full registration walkthrough. Second,
everything from there on (code exchange, refresh) is a normal OAuth2
authorization-code flow with a loopback redirect: we open a browser, catch
the redirect on a local port, and exchange the code for tokens.
"""

import json
import os
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

SCOPE = "https://www.googleapis.com/auth/sdm.service"
PARTNER_CONNECTIONS_BASE = "https://nestservices.google.com/partnerconnections"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CALLBACK_TIMEOUT = 300  # seconds to wait for the browser redirect


def _default_token_path() -> Path:
    env_path = os.environ.get("NEST_TOKEN_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "state" / "picklehome" / "nest-tokens.json"


DEFAULT_TOKEN_PATH = _default_token_path()


class NestAuthError(Exception):
    """Auth flow failed for a diagnosable reason."""


@dataclass
class NestConfig:
    project_id: str
    client_id: str
    client_secret: str
    redirect_uri: str


def load_config() -> NestConfig:
    values = {
        "NEST_PROJECT_ID": os.environ.get("NEST_PROJECT_ID", ""),
        "NEST_CLIENT_ID": os.environ.get("NEST_CLIENT_ID", ""),
        "NEST_CLIENT_SECRET": os.environ.get("NEST_CLIENT_SECRET", ""),
        "NEST_REDIRECT_URI": os.environ.get("NEST_REDIRECT_URI", ""),
    }
    missing = [name for name, val in values.items() if not val]
    if missing:
        raise NestAuthError(
            f"Missing {', '.join(missing)}. See nest/README.md for the 1Password "
            "items to create, then run 'just dotenv'."
        )
    return NestConfig(
        project_id=values["NEST_PROJECT_ID"],
        client_id=values["NEST_CLIENT_ID"],
        client_secret=values["NEST_CLIENT_SECRET"],
        redirect_uri=values["NEST_REDIRECT_URI"],
    )


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


def partner_connections_url(config: NestConfig) -> str:
    params = {
        "redirect_uri": config.redirect_uri,
        "access_type": "offline",
        "prompt": "consent",
        "client_id": config.client_id,
        "response_type": "code",
        "scope": SCOPE,
    }
    return f"{PARTNER_CONNECTIONS_BASE}/{config.project_id}/auth?{urlencode(params)}"


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches exactly one redirect: pulls ?code= (or ?error=) off the query string."""

    code: str | None = None
    error: str | None = None

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            _CallbackHandler.code = query["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorized. You can close this tab and return to the terminal.")
        else:
            _CallbackHandler.error = query.get("error", ["unknown error"])[0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Authorization failed: {_CallbackHandler.error}".encode())

    def log_message(self, format, *args):
        pass  # don't spam stderr with HTTP access logs for a one-shot local server


def _wait_for_code(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    _CallbackHandler.code = None
    _CallbackHandler.error = None
    server = HTTPServer((parsed.hostname, parsed.port), _CallbackHandler)
    try:
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        thread.join(timeout=CALLBACK_TIMEOUT)
    finally:
        server.server_close()

    if _CallbackHandler.error:
        raise NestAuthError(f"Google returned an error: {_CallbackHandler.error}")
    if not _CallbackHandler.code:
        raise NestAuthError(f"Timed out waiting for the OAuth redirect ({CALLBACK_TIMEOUT}s).")
    return _CallbackHandler.code


async def _post_token(data: dict) -> dict:
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.post(TOKEN_URL, data=data) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise NestAuthError(f"Token request failed: HTTP {resp.status}: {body}")
            return body


async def _exchange_code(config: NestConfig, code: str) -> dict:
    return await _post_token({
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": config.redirect_uri,
    })


async def _refresh(config: NestConfig, refresh_token: str) -> str:
    body = await _post_token({
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    return body["access_token"]


async def login(token_path: Path = DEFAULT_TOKEN_PATH) -> None:
    config = load_config()
    url = partner_connections_url(config)
    print("Opening browser to authorize device access...")
    print(f"If it doesn't open automatically, visit:\n  {url}\n")
    webbrowser.open(url)
    code = _wait_for_code(config.redirect_uri)
    tokens = await _exchange_code(config, code)
    if "refresh_token" not in tokens:
        raise NestAuthError(
            "Google didn't return a refresh token. Revoke prior access at "
            "https://myaccount.google.com/permissions and re-run 'just nest auth' "
            "(access_type=offline only issues one on the first consent)."
        )
    save_tokens(tokens["access_token"], tokens["refresh_token"], token_path)


async def get_access_token(token_path: Path = DEFAULT_TOKEN_PATH) -> str:
    """Access token for API calls, refreshed from the cached refresh token.

    Refreshes on every call rather than tracking expiry -- this CLI runs briefly
    and refresh is cheap, so there's no staleness window worth optimizing away.
    """
    config = load_config()
    tokens = load_tokens(token_path)
    if not tokens or not tokens.get("refresh_token"):
        raise NestAuthError("Nest tokens not found. Run 'just nest auth' to authorize.")
    access_token = await _refresh(config, tokens["refresh_token"])
    save_tokens(access_token, tokens["refresh_token"], token_path)
    return access_token
