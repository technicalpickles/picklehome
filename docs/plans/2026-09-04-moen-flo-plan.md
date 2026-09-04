# Moen Flo Water Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `just water status` for the Moen Flo shutoff valve, plus a `scripts/secret-entry`
helper that lets credentials be typed in from a phone over the tailnet while 1Password is
unreachable.

**Architecture:** Two phases. Phase 0 is a stdlib-only one-shot HTTP form, fronted by
`tailscale serve --https=8443`, that upserts `KEY=value` into `.env`. Phase 1 is a read-only
`water/flo/` module on top of `aioflo`, laid out as `<domain>/<vendor>/` exactly like
`locks/yale/` and `lg/thinq/`. The raw API dump is built and run *before* the human-readable
`status` command, so both the output layout and the test fixture come from a real payload.

**Tech Stack:** Python 3.12+, uv, `aioflo`, `aiohttp`, `argparse`, `pytest` + `unittest.mock`,
`just`, `tailscale serve`.

**Spec:** `docs/plans/2026-09-04-moen-flo-design.md`

## Global Constraints

- **Read-only. No write path, ever, in this plan.** Do not call `device.open_valve`,
  `device.close_valve`, `device.run_health_test`, `location.set_mode_away`,
  `location.set_mode_home`, or `location.set_mode_sleep`. This valve is the house water supply.
- Dependency floor: `aioflo>=2026.9.3`.
- **Name our exceptions `MoenFloError` / `MoenFloAuthError` / `MoenFloConfigError`.** `aioflo`
  already exports a class called `FloError` (`aioflo/errors.py`); reusing that name shadows it.
- Every `aiohttp.ClientSession` is built with `trust_env=True`. The sandbox routes egress through
  `HTTP_PROXY`/`HTTPS_PROXY` and a default session ignores them.
- Data fetchers raise with diagnostic context. Never return `None` to signal failure (root
  `CLAUDE.md`, Coding Conventions).
- Tests are offline, mocked at the library boundary (patch the `aioflo` API object, not internal
  functions). No `conftest.py`; fixtures live in the file that uses them.
- `.env.template` entries for Flo stay **commented out** until the `Moen Flo` item exists in the
  `picklehome` 1Password vault. A live `op://` ref to a missing item breaks `just dotenv` repo-wide.
- Tailnet-only exposure. **Never `tailscale funnel`.**
- The Tailscale binary is not on `$PATH` on this Mac; fall back to
  `/Applications/Tailscale.app/Contents/MacOS/Tailscale`.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/secret_entry.py` | Phase 0. Env-file upsert + one-shot HTTP form + `tailscale serve` lifecycle |
| `tests/scripts/test_secret_entry.py` | Upsert logic tests (pure, no network) |
| `water/__init__.py` | Empty package marker |
| `water/flo/__init__.py` | Empty package marker |
| `water/flo/auth.py` | Env validation, `aioflo` API construction, auth-flow toggle |
| `water/flo/client.py` | Domain dataclasses, read-only fetches, error classification |
| `water/water_cli.py` | argparse + async dispatch + top-level error printing |
| `water/README.md` | Setup, commands, auth-flow finding, payload findings |
| `tests/water/flo/test_auth.py` | Env validation and toggle parsing |
| `tests/water/flo/test_client.py` | Payload → dataclass, error classification |
| `tests/water/test_water_cli.py` | Pure status formatting |
| `tests/fixtures/flo-device.json` | Captured real payload, drives client tests |

**Human-in-the-loop gate:** Task 2 ends with Josh entering real credentials from his phone. Task 4
cannot run until that happens.

---

## Task 1: Env-file upsert

**Files:**
- Create: `scripts/secret_entry.py`
- Create: `tests/scripts/__init__.py` (empty)
- Test: `tests/scripts/test_secret_entry.py`

**Interfaces:**
- Consumes: nothing
- Produces: `upsert_env_vars(path: pathlib.Path, values: dict[str, str]) -> None`

Why this is its own task: it is the only part of Phase 0 with meaningful edge cases (quoting,
in-place replacement, preserving unrelated lines), and it is fully testable without a socket.

- [ ] **Step 1: Write the failing tests**

Create `tests/scripts/__init__.py` as an empty file, then `tests/scripts/test_secret_entry.py`:

```python
import pytest

from scripts.secret_entry import upsert_env_vars


def test_creates_file_when_missing(tmp_path):
    env = tmp_path / ".env"
    upsert_env_vars(env, {"FLO_USERNAME": "a@b.com"})
    assert env.read_text() == 'FLO_USERNAME="a@b.com"\n'


def test_replaces_existing_key_in_place(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="1"\nFLO_USERNAME="old"\nB="2"\n')
    upsert_env_vars(env, {"FLO_USERNAME": "new"})
    assert env.read_text() == 'A="1"\nFLO_USERNAME="new"\nB="2"\n'


def test_appends_new_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="1"\n')
    upsert_env_vars(env, {"FLO_PASSWORD": "hunter2"})
    assert env.read_text() == 'A="1"\nFLO_PASSWORD="hunter2"\n'


def test_preserves_comments_and_blank_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# a comment\n\nA="1"\n')
    upsert_env_vars(env, {"B": "2"})
    assert env.read_text() == '# a comment\n\nA="1"\nB="2"\n'


def test_does_not_match_key_as_substring(tmp_path):
    env = tmp_path / ".env"
    env.write_text('MY_FLO_USERNAME="untouched"\n')
    upsert_env_vars(env, {"FLO_USERNAME": "new"})
    assert env.read_text() == 'MY_FLO_USERNAME="untouched"\nFLO_USERNAME="new"\n'


def test_quotes_and_escapes_special_characters(tmp_path):
    env = tmp_path / ".env"
    upsert_env_vars(env, {"P": 'a b"c\\d#e'})
    assert env.read_text() == 'P="a b\\"c\\\\d#e"\n'


def test_appends_trailing_newline_when_file_lacks_one(tmp_path):
    env = tmp_path / ".env"
    env.write_text('A="1"')
    upsert_env_vars(env, {"B": "2"})
    assert env.read_text() == 'A="1"\nB="2"\n'


def test_sets_owner_only_permissions(tmp_path):
    env = tmp_path / ".env"
    upsert_env_vars(env, {"A": "1"})
    assert env.stat().st_mode & 0o777 == 0o600


def test_rejects_invalid_key_name(tmp_path):
    with pytest.raises(ValueError, match="not a valid env var name"):
        upsert_env_vars(tmp_path / ".env", {"bad key": "1"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_secret_entry.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scripts.secret_entry'`

- [ ] **Step 3: Write the implementation**

Create `scripts/__init__.py` as an empty file if it does not already exist (check first:
`ls scripts/__init__.py`). Then create `scripts/secret_entry.py`:

```python
#!/usr/bin/env python3
"""scripts/secret_entry.py -- type secrets into .env from a phone, over the tailnet.

A temporary bridge for when `op` cannot reach the 1Password desktop app (a
phone-driven session, or the sandbox blocking the socket -- see root CLAUDE.md's
Sandbox section). The alternative is pasting a password into an agent transcript.

Values are never printed, logged, or echoed. See
docs/plans/2026-09-04-moen-flo-design.md, Phase 0.
"""

from __future__ import annotations

import re
from pathlib import Path

VALID_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote(value: str) -> str:
    """Double-quote a value, escaping backslashes and quotes.

    Always quoting (rather than only when the value contains a space) keeps
    passwords with `#`, spaces, or quotes parseable by python-dotenv, which is
    what loads .env for every module in this repo. Mirrors what
    scripts/quote-env-values does to op-injected values.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def upsert_env_vars(path: Path, values: dict[str, str]) -> None:
    """Write KEY=value pairs into an env file, replacing existing keys in place.

    Existing keys keep their original position so a hand-edited .env does not get
    reordered. Comments, blank lines, and unrelated variables are preserved
    verbatim. The file is left owner-readable only.

    Raises ValueError on a key that is not a legal shell/env identifier, rather
    than writing a line that python-dotenv would silently skip.
    """
    for key in values:
        if not VALID_KEY.match(key):
            raise ValueError(f"{key!r} is not a valid env var name")

    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={_quote(remaining.pop(key))}"

    for key, value in remaining.items():
        lines.append(f"{key}={_quote(value)}")

    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_secret_entry.py -v`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/secret_entry.py scripts/__init__.py tests/scripts/
git commit -m "feat(secret-entry): env-file upsert that preserves layout and quotes values"
```

---

## Task 2: One-shot form server and `just secret-entry`

**Files:**
- Modify: `scripts/secret_entry.py` (append to the file from Task 1)
- Modify: `Justfile` (add a recipe near the other `*ARGS` recipes, around line 441)

**Interfaces:**
- Consumes: `upsert_env_vars(path, values)` from Task 1
- Produces: `just secret-entry VAR [VAR...]`, a CLI that writes the named vars into `.env`

- [ ] **Step 1: Append the server implementation**

Add to `scripts/secret_entry.py`:

```python
import argparse
import html
import os
import secrets
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TAILSCALE_FALLBACK = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
SERVE_PORT = 8443  # not 443: the node's / route on 443 is already in use
IDLE_TIMEOUT_SECONDS = 15 * 60

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>secret entry</title>
<style>
 body{{font:16px/1.5 system-ui;margin:0;padding:2rem;max-width:30rem}}
 label{{display:block;margin:1.25rem 0 .25rem;font-weight:600}}
 input{{width:100%;padding:.75rem;font-size:1rem;box-sizing:border-box}}
 button{{margin-top:1.5rem;padding:.85rem 1.5rem;font-size:1rem;width:100%}}
</style></head>
<body><form method="post"><h1>Enter secrets</h1>{fields}
<button type="submit">Save to .env</button></form></body></html>
"""


def _tailscale_binary() -> str:
    """Locate the tailscale CLI, which the macOS GUI app does not put on PATH."""
    found = shutil.which("tailscale")
    if found:
        return found
    if os.path.exists(TAILSCALE_FALLBACK):
        return TAILSCALE_FALLBACK
    raise RuntimeError(
        f"tailscale not found on PATH or at {TAILSCALE_FALLBACK}. "
        "Is the Tailscale app installed?"
    )


def _make_handler(token: str, names: list[str], env_path: Path, done: threading.Event):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            """Silence the default access log; it would record the URL token."""

        def _authorized(self) -> bool:
            path = urlparse(self.path).path.strip("/")
            return secrets.compare_digest(path, token)

        def do_GET(self) -> None:
            if not self._authorized():
                self.send_error(404)
                return
            fields = "".join(
                f'<label for="{html.escape(n)}">{html.escape(n)}</label>'
                f'<input id="{html.escape(n)}" name="{html.escape(n)}" '
                f'type="password" autocomplete="off" autocapitalize="off" '
                f'autocorrect="off" spellcheck="false" required>'
                for n in names
            )
            self._respond(200, PAGE.format(fields=fields))

        def do_POST(self) -> None:
            if not self._authorized():
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            values = {n: form.get(n, [""])[0] for n in names}
            blank = [n for n, v in values.items() if not v]
            if blank:
                self._respond(400, f"<p>Blank: {html.escape(', '.join(blank))}. Go back.</p>")
                return
            upsert_env_vars(env_path, values)
            self._respond(200, "<h1>Saved.</h1><p>You can close this tab.</p>")
            done.set()

        def _respond(self, status: int, body: str) -> None:
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve a one-shot form over the tailnet to write secrets into .env"
    )
    parser.add_argument("names", nargs="+", metavar="VAR", help="Env var names to prompt for")
    parser.add_argument("--env-file", default=".env", type=Path, help="Target env file")
    parser.add_argument(
        "--timeout", type=int, default=IDLE_TIMEOUT_SECONDS, help="Give up after N seconds"
    )
    args = parser.parse_args()

    for name in args.names:
        if not VALID_KEY.match(name):
            sys.exit(f"error: {name!r} is not a valid env var name")

    tailscale = _tailscale_binary()
    hostname = subprocess.run(
        [tailscale, "status", "--json"], capture_output=True, text=True, check=True
    )
    import json as _json

    dns_name = _json.loads(hostname.stdout)["Self"]["DNSName"].rstrip(".")

    token = secrets.token_urlsafe(24)
    done = threading.Event()
    handler = _make_handler(token, args.names, args.env_file, done)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]

    subprocess.run(
        [tailscale, "serve", "--bg", f"--https={SERVE_PORT}", f"http://127.0.0.1:{port}"],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    print(f"Open on your phone:\n\n  https://{dns_name}:{SERVE_PORT}/{token}\n")
    print(f"Waiting up to {args.timeout}s for: {', '.join(args.names)}")

    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        if not done.wait(timeout=args.timeout):
            sys.exit("\nerror: timed out, nothing written")
    finally:
        server.shutdown()
        subprocess.run(
            [tailscale, "serve", f"--https={SERVE_PORT}", "off"],
            check=False,
            stdout=subprocess.DEVNULL,
        )

    for name in args.names:
        print(f"  {name} written ({len(os.environ.get(name, '')) or '?'} chars masked)")
    print(f"Wrote {len(args.names)} value(s) to {args.env_file}")


if __name__ == "__main__":
    main()
```

Note the masked confirmation deliberately does not read the value back; it only confirms the write
happened. Values must not reach stdout.

- [ ] **Step 2: Add the Justfile recipe**

Add after the `lg` recipe (around line 445 of `Justfile`):

```make
# Type secrets into .env from a phone over the tailnet: just secret-entry FLO_USERNAME FLO_PASSWORD
# Temporary bridge for when 1Password/op is unreachable. Tailnet-only, never funnel.
secret-entry *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    uv run python scripts/secret_entry.py "$@"
```

- [ ] **Step 3: Verify the recipe is registered**

Run: `just --list | grep secret-entry`
Expected: the `secret-entry` line appears. (Per `feedback-check-justfile-after-renames`, always
confirm `just --list` after touching the Justfile.)

- [ ] **Step 4: Smoke-test against a throwaway file, not `.env`**

Run with the sandbox disabled (the `tailscale` binary SIGTRAPs under it, exit 133):

```bash
uv run python scripts/secret_entry.py TEST_VALUE --env-file /tmp/secret-entry-smoke.env --timeout 300
```

Expected: prints an `https://<host>:8443/<token>` URL. Open it, submit a value, confirm the page
says "Saved.", the process exits 0, and:

```bash
cat /tmp/secret-entry-smoke.env   # TEST_VALUE="whatever you typed"
```

Then confirm teardown left the pre-existing 443 route alone:

```bash
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status
```

Expected: the `:8443` route is gone; the `/ proxy http://127.0.0.1:52131` route on 443 remains.
Clean up: `rm /tmp/secret-entry-smoke.env`

- [ ] **Step 5: Commit**

```bash
git add scripts/secret_entry.py Justfile
git commit -m "feat(secret-entry): one-shot tailnet form for entering secrets from a phone"
```

- [ ] **Step 6: GATE — Josh enters the real credentials**

```bash
just secret-entry FLO_USERNAME FLO_PASSWORD
```

Relay the printed URL. **Stop here until he confirms it saved.** Task 4 needs these.

---

## Task 3: `water/flo/auth.py`

**Files:**
- Create: `water/__init__.py`, `water/flo/__init__.py` (both empty)
- Create: `water/flo/auth.py`
- Create: `tests/water/__init__.py`, `tests/water/flo/__init__.py` (both empty)
- Test: `tests/water/flo/test_auth.py`
- Modify: `pyproject.toml` (dependencies list, and the `packages` list on line 6)
- Modify: `.env.template` (append, commented)
- Modify: `.claude/settings.json` (`allowedDomains`, lines 5-12)

**Interfaces:**
- Consumes: nothing
- Produces:
  - `MoenFloConfigError(RuntimeError)`
  - `ONEPASSWORD_ITEM: str`
  - `get_credentials() -> tuple[str, str]` returning `(username, password)`
  - `use_sso() -> bool`
  - `async connect() -> tuple[aioflo.api.API, aiohttp.ClientSession]`

- [ ] **Step 1: Write the failing tests**

Create the four empty `__init__.py` files, then `tests/water/flo/test_auth.py`:

```python
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
```

The default is SSO because that is the flow the current Moen Smartwater app uses, and this account
is new enough that it may never have had a legacy Flo login (see the spec's auth section). Task 4
records which one actually worked.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/water/flo/test_auth.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'water'`

- [ ] **Step 3: Add the dependency and register the package**

In `pyproject.toml`, add to the `packages` list on line 6 so it reads:

```toml
packages = ["picklehome", "climate", "network", "lighting", "garage", "locks", "nest", "sonos", "homelab", "lg", "water"]
```

and append to `dependencies`, after the `# lg` entry:

```toml
    # water
    "aioflo>=2026.9.3",
```

Then run: `uv sync`

- [ ] **Step 4: Write the implementation**

Create `water/flo/auth.py`:

```python
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

    Defaults to True: SSO is what the current Moen Smartwater app uses, and an
    account created recently may never have had a legacy Flo login at all. Set
    FLO_USE_SSO=0 to fall back to aioflo's legacy users/auth flow.
    """
    raw = os.environ.get("FLO_USE_SSO")
    if raw is None:
        return True
    return raw.strip().lower() in _TRUTHY


async def connect() -> tuple[API, aiohttp.ClientSession]:
    """Build an authenticated aioflo API client.

    Returns (api, session). The caller owns the session and must close it in a
    finally block -- aioflo only holds a reference.

    The session is built with trust_env=True so it honours HTTP_PROXY/HTTPS_PROXY.
    aioflo's own fallback session does not, which breaks under the Claude Code
    sandbox's proxy-based allowlisting (root CLAUDE.md, Sandbox). Same pattern as
    lg/thinq/auth.py and climate/hisense/auth.py.
    """
    username, password = get_credentials()
    session = aiohttp.ClientSession(trust_env=True)
    api = await async_get_api(username, password, session=session, use_sso=use_sso())
    return api, session
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/water/flo/test_auth.py -v`
Expected: PASS, 15 passed

- [ ] **Step 6: Add the sandbox domains**

In `.claude/settings.json`, extend `allowedDomains` (currently lines 5-12) to include all three
Moen hosts, keeping the list alphabetically sorted as it is now:

```json
      "allowedDomains": [
        "4j1gkf0vji.execute-api.us-east-2.amazonaws.com",
        "accounts.eu1.gigya.com",
        "api-aic.lgthinq.com",
        "api-eu.vicohome.io",
        "api-gw.meetflo.com",
        "api-us.vicohome.io",
        "api.meetflo.com",
        "clife-eu-gateway.hijuconn.com",
        "oauth.hijuconn.com"
      ]
```

`api-gw.meetflo.com` is the v2 API, `api.meetflo.com` is legacy auth, and the
`execute-api.us-east-2.amazonaws.com` host is the Moen SSO token endpoint. **These take effect
next session**, so Task 4's live run needs the sandbox disabled regardless.

- [ ] **Step 7: Add the commented `.env.template` entries**

Append to `.env.template`:

```bash
# Moen Flo smart shutoff valve, 1Password item: Moen Flo, picklehome vault.
#
# COMMENTED OUT ON PURPOSE. `op inject` fails hard on a reference to an item that does not exist,
# which would break `just dotenv` for the whole repo, not just for water. Un-comment these two
# lines once the "Moen Flo" item exists in the picklehome vault, then run `just dotenv`.
# Until then the values are written directly into .env by `just secret-entry`.
#
# FLO_USE_SSO selects the auth flow: 1 (default) uses Moen's SSO/Cognito flow, which is what the
# current Smartwater app uses; 0 falls back to aioflo's legacy users/auth endpoint.
# FLO_USERNAME={{ op://picklehome/Moen Flo/username }}
# FLO_PASSWORD={{ op://picklehome/Moen Flo/password }}
```

- [ ] **Step 8: Verify `just dotenv` is still not broken by the template change**

Run: `grep -c '^# FLO_' .env.template`
Expected: `2`. Both lines must be commented. Do **not** run `just dotenv` here; it would fail on
the `FLO_*` keys `secret-entry` wrote into `.env` (which is the intended guardrail, not a bug).

- [ ] **Step 9: Commit**

```bash
git add water/ tests/water/ pyproject.toml uv.lock .env.template .claude/settings.json
git commit -m "feat(water): Moen Flo auth module, deps, and sandbox domains"
```

---

## Task 4: `just water device --raw` and capturing the real payload

**Files:**
- Create: `water/flo/client.py`
- Create: `water/water_cli.py`
- Create: `tests/fixtures/flo-device.json` (captured in Step 5)
- Modify: `Justfile`

**Interfaces:**
- Consumes: `connect()`, `MoenFloConfigError`, `ONEPASSWORD_ITEM` from Task 3
- Produces:
  - `MoenFloError(RuntimeError)`, `MoenFloAuthError(MoenFloError)`
  - `async fetch_raw(api) -> dict` with keys `user`, `locations`, `devices`
  - `async with_api()` async context manager yielding an authenticated `API`

This task is where the unknowns get resolved: which auth flow works, and what the payload contains.
`status` is deliberately not built yet.

- [ ] **Step 1: Write the client**

Create `water/flo/client.py`:

```python
"""Read-only fetches against the Moen Flo API.

Read-only by design. aioflo also exposes open_valve/close_valve and the
home/away/sleep system-mode setters; none are called here and none should be
added without a deliberate decision. This valve is the house water supply.

aioflo collapses every failure into a single RequestError with no vendor error
code (unlike thinqconnect, which lg/thinq/client.py can classify on). The only
honest signal available is *when* the failure happened: during authentication,
or after it. connect() raising means the credentials or the auth flow are wrong;
anything later is an ordinary request failure.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from aioflo.api import API
from aioflo.errors import FloError as AioFloError

from water.flo.auth import ONEPASSWORD_ITEM, connect, use_sso


class MoenFloError(RuntimeError):
    """A Flo API call failed."""


class MoenFloAuthError(MoenFloError):
    """Flo rejected the credentials, or the wrong auth flow was used."""


@asynccontextmanager
async def with_api():
    """Yield an authenticated API, closing the session on the way out.

    Classifies an authentication-time failure as MoenFloAuthError, naming both
    plausible causes -- because with a single untyped RequestError there is no
    way to tell a bad password from the wrong auth flow, and the FLO_USE_SSO
    toggle is the first thing to try.
    """
    try:
        api, session = await connect()
    except AioFloError as err:
        flow = "SSO (Cognito)" if use_sso() else "legacy users/auth"
        other = "0" if use_sso() else "1"
        raise MoenFloAuthError(
            f"Flo rejected authentication via the {flow} flow. Either the password is "
            f"wrong, or this account needs the other flow -- try FLO_USE_SSO={other}. "
            f"Credentials come from {ONEPASSWORD_ITEM} (or 'just secret-entry')."
        ) from err

    try:
        yield api
    finally:
        await session.close()


async def fetch_raw(api: API) -> dict:
    """Return the unmassaged user, location, and device payloads.

    Three calls because each layer holds different things: the user record names
    the locations, the location record carries system mode (home/away/sleep) and
    the device ids, and only the per-device record has live telemetry.
    """
    try:
        user = await api.user.get_info(include_location_info=True)
        locations, devices = [], []
        for location_stub in user.get("locations", []):
            location = await api.location.get_info(
                location_stub["id"], include_device_info=True
            )
            locations.append(location)
            for device_stub in location.get("devices", []):
                devices.append(await api.device.get_info(device_stub["id"]))
    except AioFloError as err:
        raise MoenFloError(f"Flo API request failed: {err}") from err

    return {"user": user, "locations": locations, "devices": devices}
```

- [ ] **Step 2: Write the CLI with only the `device` command**

Create `water/water_cli.py`:

```python
#!/usr/bin/env python3
"""water_cli.py -- Moen Flo smart shutoff valve CLI. Read-only.

Usage:
    uv run python water/water_cli.py device --raw [--json]
"""

import argparse
import asyncio
import json
import sys

from water.flo.auth import MoenFloConfigError
from water.flo.client import MoenFloError, fetch_raw, with_api


async def cmd_device(raw: bool, json_output: bool) -> None:
    async with with_api() as api:
        payload = await fetch_raw(api)
    print(json.dumps(payload, indent=2, default=str))


async def run(args: argparse.Namespace) -> None:
    if args.command == "device":
        await cmd_device(args.raw, args.json)


def main() -> None:
    parser = argparse.ArgumentParser(description="Moen Flo shutoff valve CLI (read-only)")
    sub = parser.add_subparsers(dest="command", required=True)

    device_parser = sub.add_parser("device", help="Device detail, or the raw API dump")
    device_parser.add_argument("--raw", action="store_true", help="Print the unmassaged API JSON")
    device_parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (MoenFloConfigError, MoenFloError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add the Justfile recipe**

Add after the `lg` recipe:

```make
# Moen Flo water shutoff (read-only): just water status | device [--raw]
water *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    uv run python water/water_cli.py "$@"
```

Run: `just --list | grep water`
Expected: the `water` line appears.

- [ ] **Step 4: Run it live against the real account**

Run **with the sandbox disabled** (the domains added in Task 3 do not take effect until the next
session):

```bash
just water device --raw > /tmp/flo-raw.json && head -40 /tmp/flo-raw.json
```

If it fails with `MoenFloAuthError`, flip the flow and retry:

```bash
FLO_USE_SSO=0 just water device --raw > /tmp/flo-raw.json
```

**Record which one worked.** It goes in the README in Task 5 and decides the shipped default.

- [ ] **Step 5: Save the fixture, with secrets stripped**

Inspect `/tmp/flo-raw.json` for anything that should not be committed. Expect at minimum: the
account email, the device MAC address, the location's street address and coordinates, and
`serialNumber`. Per `feedback-hardware-id-sensitivity`, MACs and coordinates near the house are
geolocatable and must not land in a public repo.

```bash
mkdir -p tests/fixtures
uv run python - <<'PY'
import json, pathlib
from water.flo.scrub import scrub_payload
raw = json.loads(pathlib.Path("/tmp/flo-raw.json").read_text())
pathlib.Path("tests/fixtures/flo-device.json").write_text(
    json.dumps(scrub_payload(raw), indent=2) + "\n"
)
PY
grep -icE 'meetflo|@|[0-9a-f]{2}:[0-9a-f]{2}' tests/fixtures/flo-device.json
```

`water/flo/scrub.py` (added in the code-review fix wave, after this task originally shipped) is
now the single source of truth for what gets redacted -- see its docstring and
`tests/water/flo/test_scrub.py`. Read the scrubbed file yourself before committing regardless;
the redaction list is a starting point, not a guarantee, and Flo may nest identifiers under keys
not listed there.

- [ ] **Step 6: Commit**

```bash
rm -f /tmp/flo-raw.json
git add water/flo/client.py water/water_cli.py tests/fixtures/flo-device.json Justfile
git commit -m "feat(water): raw Flo API dump command and a scrubbed payload fixture"
```

---

## Task 5: `just water status`

**Files:**
- Modify: `water/flo/client.py` (add the dataclass and parser)
- Modify: `water/water_cli.py` (add the `status` command and formatter)
- Create: `water/README.md`
- Test: `tests/water/flo/test_client.py`, `tests/water/test_water_cli.py`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: `with_api()`, `fetch_raw()`, `MoenFloError`, `MoenFloAuthError` from Task 4
- Produces: `FloValve` dataclass, `parse_valve(device: dict, location: dict) -> FloValve`,
  `format_status(valve: FloValve) -> str`

**Field names below are provisional.** Before writing any code, open
`tests/fixtures/flo-device.json` from Task 4 and correct every key path in this task to match what
Flo actually returned. The names used here (`valve.lastKnownState`, `telemetry.current.gpm`,
`systemMode.lastKnownMode`, `connectivity.rssi`, `notifications.pending`) are the expected shape,
not verified fact. Adjust the tests and the parser together.

- [ ] **Step 1: Write the failing client tests**

Create `tests/water/flo/test_client.py`:

```python
import json
import pathlib

import pytest
from aioflo.errors import RequestError

from water.flo.client import MoenFloError, fetch_raw, parse_valve

FIXTURE = json.loads(
    (pathlib.Path(__file__).parents[2] / "fixtures" / "flo-device.json").read_text()
)


def _device_and_location():
    return FIXTURE["devices"][0], FIXTURE["locations"][0]


def test_parses_the_real_fixture_without_raising():
    device, location = _device_and_location()
    valve = parse_valve(device, location)
    assert valve.state in {"open", "closed", "unknown"}


def test_reports_unknown_rather_than_crashing_on_a_missing_valve_block():
    device, location = _device_and_location()
    stripped = {k: v for k, v in device.items() if k != "valve"}
    assert parse_valve(stripped, location).state == "unknown"


def test_missing_telemetry_yields_none_not_zero():
    device, location = _device_and_location()
    stripped = {k: v for k, v in device.items() if k != "telemetry"}
    valve = parse_valve(stripped, location)
    assert valve.gpm is None and valve.psi is None and valve.temp_f is None


@pytest.mark.asyncio
async def test_request_failure_after_auth_raises_moenfloerror():
    class Boom:
        class user:
            @staticmethod
            async def get_info(**kwargs):
                raise RequestError("network went away")

    with pytest.raises(MoenFloError, match="network went away"):
        await fetch_raw(Boom())
```

`pytest-asyncio` is not currently a dependency. Check first with
`grep -n 'asyncio\|pytest' pyproject.toml`. If it is absent, drop the `@pytest.mark.asyncio`
decorator and drive the coroutine with `asyncio.run(...)` inside a plain test function, which is
what `tests/garage/aladdin/test_auth.py` already does.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/water/flo/test_client.py -v`
Expected: FAIL, `ImportError: cannot import name 'parse_valve'`

- [ ] **Step 3: Add the dataclass and parser to `water/flo/client.py`**

Add these imports at the top (`from dataclasses import dataclass`), then append:

```python
@dataclass(frozen=True)
class FloValve:
    """One Flo shutoff valve, flattened from the device and location payloads.

    Every telemetry field is optional. The Flo reports telemetry only while it
    has a recent reading; absent is meaningfully different from zero, and 0.0 gpm
    ("no water moving") must not be confused with "no reading" (see root
    CLAUDE.md, Coding Conventions).
    """

    name: str
    state: str          # "open" | "closed" | "unknown"
    mode: str | None    # home | away | sleep
    gpm: float | None
    psi: float | None
    temp_f: float | None
    rssi: int | None
    connected: bool | None
    pending_alerts: int | None


def _dig(node: dict, *keys, default=None):
    """Walk nested dict keys, returning default the moment one is missing."""
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def parse_valve(device: dict, location: dict) -> FloValve:
    """Flatten a device payload (plus its location's system mode) into a FloValve."""
    pending = _dig(device, "notifications", "pending", default={})
    alert_count = None
    if isinstance(pending, dict):
        alert_count = sum(
            v for k, v in pending.items() if k.endswith("Count") and isinstance(v, int)
        )

    return FloValve(
        name=_dig(device, "nickname", default="Flo"),
        state=_dig(device, "valve", "lastKnownState", default="unknown"),
        mode=_dig(location, "systemMode", "lastKnownMode"),
        gpm=_dig(device, "telemetry", "current", "gpm"),
        psi=_dig(device, "telemetry", "current", "psi"),
        temp_f=_dig(device, "telemetry", "current", "tempF"),
        rssi=_dig(device, "connectivity", "rssi"),
        connected=_dig(device, "isConnected"),
        pending_alerts=alert_count,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/water/flo/test_client.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Write the failing formatter test**

Create `tests/water/test_water_cli.py`:

```python
from water.flo.client import FloValve
from water.water_cli import format_status


def _valve(**overrides):
    base = dict(name="Main Shutoff", state="open", mode="home", gpm=0.0, psi=62.0,
                temp_f=68.0, rssi=-54, connected=True, pending_alerts=0)
    base.update(overrides)
    return FloValve(**base)


def test_renders_every_field():
    out = format_status(_valve())
    assert "Main Shutoff" in out
    assert "open" in out
    assert "0.0 gpm" in out
    assert "62 psi" in out
    assert "68 °F" in out
    assert "home" in out
    assert "-54 dBm" in out
    assert "none" in out


def test_distinguishes_no_reading_from_zero():
    assert "0.0 gpm" in format_status(_valve(gpm=0.0))
    assert "no reading" in format_status(_valve(gpm=None))


def test_pluralizes_and_counts_alerts():
    assert "none" in format_status(_valve(pending_alerts=0))
    assert "1 pending" in format_status(_valve(pending_alerts=1))
    assert "3 pending" in format_status(_valve(pending_alerts=3))


def test_flags_a_closed_valve_and_a_disconnected_device():
    assert "closed" in format_status(_valve(state="closed"))
    assert "disconnected" in format_status(_valve(connected=False))
```

- [ ] **Step 6: Run to verify it fails**

Run: `uv run pytest tests/water/test_water_cli.py -v`
Expected: FAIL, `ImportError: cannot import name 'format_status'`

- [ ] **Step 7: Add `format_status` and the `status` command**

In `water/water_cli.py`, add `from dataclasses import asdict` and
`from water.flo.client import FloValve, parse_valve` to the imports, then add:

```python
def _num(value, suffix: str, fmt: str = "{:.0f}") -> str:
    """Render a telemetry value, keeping 'no reading' distinct from a real zero."""
    return "no reading" if value is None else f"{fmt.format(value)} {suffix}"


def format_status(valve: FloValve) -> str:
    if valve.pending_alerts is None:
        alerts = "unknown"
    elif valve.pending_alerts == 0:
        alerts = "none"
    else:
        alerts = f"{valve.pending_alerts} pending"

    if valve.connected is None:
        link = _num(valve.rssi, "dBm")
    else:
        link = f"{_num(valve.rssi, 'dBm')} ({'connected' if valve.connected else 'disconnected'})"

    lines = [
        f"Flo — {valve.name:<24} {valve.state}",
        f"  flow        {_num(valve.gpm, 'gpm', '{:.1f}')}",
        f"  pressure    {_num(valve.psi, 'psi')}",
        f"  temp        {_num(valve.temp_f, '°F')}",
        f"  mode        {valve.mode or 'unknown'}",
        f"  wifi        {link}",
        f"  alerts      {alerts}",
    ]
    return "\n".join(lines)


async def cmd_status(json_output: bool) -> None:
    async with with_api() as api:
        payload = await fetch_raw(api)

    location = payload["locations"][0] if payload["locations"] else {}
    valves = [parse_valve(device, location) for device in payload["devices"]]

    if json_output:
        print(json.dumps([asdict(v) for v in valves], indent=2))
        return

    print("\n\n".join(format_status(v) for v in valves))
```

Wire it into `run()` and `main()`:

```python
async def run(args: argparse.Namespace) -> None:
    if args.command == "status":
        await cmd_status(args.json)
    elif args.command == "device":
        await cmd_device(args.raw, args.json)
```

```python
    status_parser = sub.add_parser("status", help="Valve state, flow, pressure, alerts")
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")
```

- [ ] **Step 8: Run the whole suite**

Run: `uv run pytest tests/water/ tests/scripts/ -v`
Expected: PASS, all green.

Then run it for real (sandbox disabled if `allowedDomains` has not taken effect yet):

```bash
just water status
```

Expected: the status block, populated with real numbers.

- [ ] **Step 9: Write `water/README.md`**

Cover, using what Task 4 actually found rather than what this plan guessed:

- **Setup**: `just secret-entry FLO_USERNAME FLO_PASSWORD` now; the 1Password item and
  un-commenting `.env.template` later.
- **Commands**: `just water status`, `just water device --raw`, and why `--raw` is kept
  permanently (first thing to reach for when Moen changes a field).
- **Which auth flow this account uses**, recorded as a finding with the date, plus how to flip it
  with `FLO_USE_SSO`.
- **Payload findings**: any field that is present but always empty, any surprising units, anything
  that would otherwise get rediscovered from scratch. Follow `lg/README.md`'s "Filter fields in
  `--raw` output are unpopulated placeholders" section as the model.
- **Read-only by design**, and that `aioflo` exposes valve control which this module deliberately
  does not call.

- [ ] **Step 10: Update root `CLAUDE.md`**

Add to the Directories list, after the `lg/` entry:

```markdown
- `water/`: Moen Flo smart water shutoff (read-only); see `water/README.md`
```

Add to the Integrations table, after the LG ThinQ row:

```markdown
| Moen Flo | `water/` | Smart water shutoff valve | Cloud API (user/pass), read-only | `just water *` |
```

- [ ] **Step 11: Commit**

```bash
git add water/ tests/water/ CLAUDE.md
git commit -m "feat(water): just water status for the Moen Flo valve"
```

---

## Closing checklist

- [ ] `uv run pytest` passes across the whole repo, not just `tests/water/`
- [ ] `just --list` shows both `water` and `secret-entry`
- [ ] `tests/fixtures/flo-device.json` has been read by a human and contains no email, MAC,
      serial, street address, or coordinates
- [ ] File these as Taskwarrior items under `project:picklehome.water`:
  - Create the `Moen Flo` item in the `picklehome` 1Password vault, un-comment the two
    `.env.template` lines, run `just dotenv`, and confirm `just water status` still works
  - Delete the `FLO_USERNAME`/`FLO_PASSWORD` lines that `secret-entry` wrote into `.env` once
    they come from 1Password, so there is one source of truth
  - Consider usage history via `water.get_consumption_info` if trends become interesting
  - Revisit valve control and away-mode only if a concrete need appears
