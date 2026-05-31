# Garage Door (Aladdin Connect) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add garage door status and control via Aladdin Connect by Genie, following existing repo patterns.

**Architecture:** New `garage/` top-level module with `garage/aladdin/` vendor submodule. OAuth2 auth via `genie-partner-sdk`, token persistence to JSON file, async CLI with argparse subcommands. Mirrors the `climate/ecobee/` auth pattern and `lighting/hue_cli.py` CLI pattern.

**Tech Stack:** `genie-partner-sdk>=1.0.11`, `aiohttp`, Python 3.12+

---

### Task 1: Project scaffolding

Add the `garage` package to `pyproject.toml` and create empty module files.

**Files:**
- Modify: `pyproject.toml`
- Create: `garage/__init__.py`
- Create: `garage/aladdin/__init__.py`

**Step 1: Add garage to pyproject.toml**

In `pyproject.toml`, add `"garage"` to the wheel packages list:

```python
packages = ["climate", "network", "lighting", "garage"]
```

And add the dependency:

```python
    # garage
    "genie-partner-sdk>=1.0.11",
```

**Step 2: Create empty module files**

```bash
mkdir -p garage/aladdin
touch garage/__init__.py
touch garage/aladdin/__init__.py
```

**Step 3: Install deps**

```bash
uv sync
```

Verify `genie-partner-sdk` is importable:

```bash
uv run python -c "from genie_partner_sdk.client import AladdinConnectClient; print('ok')"
```

**Step 4: Commit**

```
feat(garage): add garage module scaffolding and genie-partner-sdk dep
```

---

### Task 2: Auth - token storage

Implement token load/save functions following the Ecobee pattern (`climate/ecobee/auth.py`). Token file at `~/.local/state/picklehome/aladdin-tokens.json`, permissions 0o600.

**Files:**
- Create: `garage/aladdin/auth.py`
- Create: `tests/garage/__init__.py`
- Create: `tests/garage/aladdin/__init__.py`
- Create: `tests/garage/aladdin/test_auth.py`

**Step 1: Write failing tests for token storage**

```python
# tests/garage/aladdin/test_auth.py
import json

from garage.aladdin.auth import load_tokens, save_tokens


def test_save_and_load_tokens(tmp_path):
    token_path = tmp_path / "tokens.json"
    save_tokens("access123", "refresh456", token_path)

    tokens = load_tokens(token_path)
    assert tokens == {"access_token": "access123", "refresh_token": "refresh456"}


def test_load_tokens_missing_file(tmp_path):
    token_path = tmp_path / "nonexistent.json"
    assert load_tokens(token_path) is None


def test_token_file_permissions(tmp_path):
    token_path = tmp_path / "tokens.json"
    save_tokens("a", "b", token_path)
    assert token_path.stat().st_mode & 0o777 == 0o600


def test_save_tokens_creates_parent_dirs(tmp_path):
    token_path = tmp_path / "deep" / "nested" / "tokens.json"
    save_tokens("a", "b", token_path)
    assert token_path.exists()
```

**Step 2: Run tests, verify they fail**

```bash
uv run pytest tests/garage/aladdin/test_auth.py -v
```

Expected: ImportError (module doesn't exist yet)

**Step 3: Implement token storage**

```python
# garage/aladdin/auth.py
import json
import os
from pathlib import Path


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
```

**Step 4: Run tests, verify they pass**

```bash
uv run pytest tests/garage/aladdin/test_auth.py -v
```

**Step 5: Commit**

```
feat(garage): add aladdin token load/save with file permissions
```

---

### Task 3: Auth - credential loading

Load Aladdin email/password from env vars, with clear error messages if missing.

**Files:**
- Modify: `garage/aladdin/auth.py`
- Modify: `tests/garage/aladdin/test_auth.py`

**Step 1: Write failing tests for credential loading**

```python
# append to tests/garage/aladdin/test_auth.py
import pytest

from garage.aladdin.auth import get_credentials


def test_get_credentials_from_env(monkeypatch):
    monkeypatch.setenv("ALADDIN_EMAIL", "user@example.com")
    monkeypatch.setenv("ALADDIN_PASSWORD", "secret")
    email, password = get_credentials()
    assert email == "user@example.com"
    assert password == "secret"


def test_get_credentials_missing_email(monkeypatch):
    monkeypatch.delenv("ALADDIN_EMAIL", raising=False)
    monkeypatch.setenv("ALADDIN_PASSWORD", "secret")
    with pytest.raises(SystemExit):
        get_credentials()


def test_get_credentials_missing_password(monkeypatch):
    monkeypatch.setenv("ALADDIN_EMAIL", "user@example.com")
    monkeypatch.delenv("ALADDIN_PASSWORD", raising=False)
    with pytest.raises(SystemExit):
        get_credentials()
```

**Step 2: Run tests, verify new tests fail**

```bash
uv run pytest tests/garage/aladdin/test_auth.py -v
```

**Step 3: Implement credential loading**

Add to `garage/aladdin/auth.py`:

```python
import sys

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
```

**Step 4: Run tests, verify they pass**

```bash
uv run pytest tests/garage/aladdin/test_auth.py -v
```

**Step 5: Commit**

```
feat(garage): add aladdin credential loading from env vars
```

---

### Task 4: Auth - OAuth flow and SDK Auth subclass

Implement the OAuth2 login flow and the `genie-partner-sdk` Auth subclass. The flow:
1. POST email/password to the Genie OAuth token endpoint
2. Receive access + refresh tokens
3. Persist tokens to disk
4. Auth subclass returns cached token, refreshing when expired

Reference: the HA integration at `erikreedstrom/aladdin_connect` (api.py, const.py).

**Files:**
- Modify: `garage/aladdin/auth.py`
- Modify: `tests/garage/aladdin/test_auth.py`

**Step 1: Add constants**

Add to `garage/aladdin/auth.py`:

```python
# OAuth/API constants (from erikreedstrom/aladdin_connect HA integration)
API_URL = "https://twdvzuefzh.execute-api.us-east-2.amazonaws.com/v1"
API_KEY = "k6QaiQmcTm2zfaNns5L1Z8duBtJmhDOW8JawlCC3"
OAUTH2_TOKEN_URL = "https://twdvzuefzh.execute-api.us-east-2.amazonaws.com/v1/oauth2/token"
OAUTH2_AUTHORIZE_URL = "https://app.aladdinconnect.net/login.html"
```

**Step 2: Write failing test for Auth subclass**

```python
# append to tests/garage/aladdin/test_auth.py
from unittest.mock import AsyncMock, MagicMock

from garage.aladdin.auth import AladdinAuth, API_URL, API_KEY


def test_aladdin_auth_returns_cached_token():
    session = MagicMock()
    auth = AladdinAuth(session, "valid_access_token", "refresh_token", tmp_path / "t.json")

    async def _run():
        token = await auth.async_get_access_token()
        assert token == "valid_access_token"

    import asyncio
    asyncio.run(_run())
```

**Step 3: Implement Auth subclass**

The `AladdinAuth` subclass of `genie_partner_sdk.Auth`:
- Takes a websession, initial access token, refresh token, and token path
- `async_get_access_token()` returns the current access token
- Token refresh via the OAuth2 token endpoint (using refresh_token grant)
- Saves refreshed tokens to disk

```python
import aiohttp
from genie_partner_sdk.auth import Auth


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
        async with self._websession.post(
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
```

**Step 4: Implement the login flow function**

```python
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
```

**Note:** The exact OAuth grant type and payload may need adjustment based on what the Genie API actually accepts. The HA integration uses an authorization code flow (browser redirect), but for CLI use we'll try password grant first. If that doesn't work, we'll fall back to opening a browser with a local callback server. This task may require some experimentation against the live API.

**Step 5: Run tests, verify they pass**

```bash
uv run pytest tests/garage/aladdin/test_auth.py -v
```

**Step 6: Commit**

```
feat(garage): add OAuth Auth subclass and login flow
```

---

### Task 5: Client wrapper

Thin wrapper around `AladdinConnectClient` that creates the session and auth, exposes status/open/close.

**Files:**
- Create: `garage/aladdin/client.py`
- Create: `tests/garage/aladdin/test_client.py`

**Step 1: Write failing tests**

```python
# tests/garage/aladdin/test_client.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from garage.aladdin.client import get_doors, open_door, close_door


def test_get_doors_returns_door_list():
    fake_door = MagicMock()
    fake_door.name = "Garage Door"
    fake_door.status = "closed"
    fake_door.battery_level = 95
    fake_door.link_status = "connected"
    fake_door.device_id = "dev1"
    fake_door.door_number = 1

    async def _run():
        with patch("garage.aladdin.client.AladdinConnectClient") as MockClient:
            instance = MockClient.return_value
            instance.get_doors = AsyncMock(return_value=[fake_door])
            doors = await get_doors(instance)
            assert len(doors) == 1
            assert doors[0].name == "Garage Door"

    asyncio.run(_run())
```

**Step 2: Run tests, verify they fail**

```bash
uv run pytest tests/garage/aladdin/test_client.py -v
```

**Step 3: Implement client wrapper**

```python
# garage/aladdin/client.py
import aiohttp
from genie_partner_sdk.client import AladdinConnectClient
from genie_partner_sdk.model import GarageDoor

from garage.aladdin.auth import AladdinAuth, load_tokens, get_credentials, login, DEFAULT_TOKEN_PATH


async def connect() -> tuple[aiohttp.ClientSession, AladdinConnectClient]:
    """Create an authenticated Aladdin Connect client.

    Returns the session (caller must close) and the client.
    """
    tokens = load_tokens()
    if not tokens or not tokens.get("access_token"):
        print("Aladdin tokens not found. Run 'just garage auth' to authenticate.")
        import sys
        sys.exit(1)

    session = aiohttp.ClientSession(trust_env=True)
    auth = AladdinAuth(
        session,
        tokens["access_token"],
        tokens["refresh_token"],
        DEFAULT_TOKEN_PATH,
    )
    client = AladdinConnectClient(auth)
    return session, client


async def get_doors(client: AladdinConnectClient) -> list[GarageDoor]:
    """Fetch all garage doors."""
    return await client.get_doors()


async def open_door(client: AladdinConnectClient, device_id: str, door_number: int) -> bool:
    """Open a door. Returns True on success."""
    return await client.open_door(device_id, door_number)


async def close_door(client: AladdinConnectClient, device_id: str, door_number: int) -> bool:
    """Close a door. Returns True on success."""
    return await client.close_door(device_id, door_number)
```

**Step 4: Run tests, verify they pass**

```bash
uv run pytest tests/garage/aladdin/test_client.py -v
```

**Step 5: Commit**

```
feat(garage): add aladdin client wrapper for status and control
```

---

### Task 6: CLI

Argparse-based CLI following the `lighting/hue_cli.py` pattern: subcommands for auth, status, open, close.

**Files:**
- Create: `garage/garage_cli.py`

**Step 1: Implement CLI**

```python
#!/usr/bin/env python3
"""
garage_cli.py: Aladdin Connect garage door CLI

Usage:
    uv run python garage/garage_cli.py auth      # login and save tokens
    uv run python garage/garage_cli.py status     # door state, battery, signal
    uv run python garage/garage_cli.py open       # open the door
    uv run python garage/garage_cli.py close      # close the door
"""

import argparse
import asyncio

from garage.aladdin.auth import get_credentials, login
from garage.aladdin.client import connect, get_doors, open_door, close_door


async def cmd_auth():
    email, password = get_credentials()
    print(f"Logging in as {email}...")
    await login(email, password)
    print("Authentication successful! Tokens saved.")

    # Show discovered doors
    session, client = await connect()
    try:
        doors = await get_doors(client)
        if doors:
            print(f"\nFound {len(doors)} door(s):")
            for door in doors:
                print(f"  {door.name}: {door.status} (battery: {door.battery_level}%)")
        else:
            print("\nNo doors found on this account.")
    finally:
        await session.close()


async def cmd_status():
    session, client = await connect()
    try:
        doors = await get_doors(client)
        if not doors:
            print("No doors found.")
            return
        for door in doors:
            print(f"{door.name}")
            print(f"  State:   {door.status}")
            print(f"  Battery: {door.battery_level}%")
            print(f"  Link:    {door.link_status}")
    finally:
        await session.close()


async def cmd_open():
    session, client = await connect()
    try:
        doors = await get_doors(client)
        if not doors:
            print("No doors found.")
            return
        door = doors[0]
        print(f"Opening {door.name}...")
        success = await open_door(client, door.device_id, door.door_number)
        print("Sent." if success else "Failed to send open command.")
    finally:
        await session.close()


async def cmd_close():
    session, client = await connect()
    try:
        doors = await get_doors(client)
        if not doors:
            print("No doors found.")
            return
        door = doors[0]
        print(f"Closing {door.name}...")
        success = await close_door(client, door.device_id, door.door_number)
        print("Sent." if success else "Failed to send close command.")
    finally:
        await session.close()


async def run(args):
    if args.command == "auth":
        await cmd_auth()
    elif args.command == "status":
        await cmd_status()
    elif args.command == "open":
        await cmd_open()
    elif args.command == "close":
        await cmd_close()


def main():
    parser = argparse.ArgumentParser(description="Aladdin Connect garage door CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Login and save OAuth tokens")
    sub.add_parser("status", help="Show door state, battery, signal")
    sub.add_parser("open", help="Open the garage door")
    sub.add_parser("close", help="Close the garage door")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
```

**Step 2: Verify CLI loads without errors**

```bash
uv run python garage/garage_cli.py --help
```

**Step 3: Commit**

```
feat(garage): add garage door CLI with auth, status, open, close
```

---

### Task 7: Justfile and .env.template

Wire up `just garage` and add Aladdin credentials to the env template.

**Files:**
- Modify: `Justfile`
- Modify: `.env.template`

**Step 1: Add Justfile task**

Append to `Justfile`:

```just
# Aladdin garage door: just garage auth | status | open | close
garage *ARGS:
    uv run python garage/garage_cli.py {{ARGS}}
```

**Step 2: Add env vars to .env.template**

Append to `.env.template`:

```bash
# Aladdin Connect garage door (1Password item: Aladdin Connect)
ALADDIN_EMAIL={{ op://picklehome/Aladdin Connect/email }}
ALADDIN_PASSWORD={{ op://picklehome/Aladdin Connect/password }}
```

**Step 3: Verify**

```bash
just garage --help
```

**Step 4: Commit**

```
feat(garage): add just garage task and env template for aladdin creds
```

---

### Task 8: 1Password setup and live test

Store Aladdin Connect credentials in 1Password, regenerate `.env`, and test the full flow.

**Step 1: Create 1Password item**

The user needs to create an "Aladdin Connect" item in the picklehome vault with `email` and `password` fields matching their Genie app credentials.

**Step 2: Regenerate .env**

```bash
just dotenv
```

**Step 3: Test auth flow**

```bash
just garage auth
```

This will attempt the OAuth login. If the password grant type doesn't work, we'll need to adjust the auth flow (potentially to authorization code with a browser).

**Step 4: Test status**

```bash
just garage status
```

**Step 5: Commit any adjustments**

If the OAuth flow needed tweaks during live testing, commit the fixes.

---

### Task 9: README

Write `garage/README.md` following the `climate/README.md` pattern: setup, commands, architecture, module structure.

**Files:**
- Create: `garage/README.md`

**Step 1: Write README**

Cover:
- Setup steps (1Password, dotenv, auth)
- Command reference (just garage auth/status/open/close)
- Architecture notes (genie-partner-sdk, OAuth2, token storage)
- Module structure

**Step 2: Commit**

```
docs(garage): add README with setup, commands, and architecture
```
