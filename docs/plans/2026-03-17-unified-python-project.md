# Unified Python Project (picklehome) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Merge climate and network into a single `picklehome` project with one lockfile, pinned deps, and shared utility code.

**Architecture:** Rename the project from `picklehome-climate` to `picklehome`, add `network` as an installable package alongside `climate`, add all network deps to `pyproject.toml`, extract duplicated UniFi auth code into `network/unifi.py`, and drop the ad-hoc `--with` flags from the Justfile.

**Tech Stack:** uv, hatchling, Python 3.12+, requests, python-dotenv, playwright, paramiko, dnspython

---

## Dependency map (for reference)

| Script | Third-party deps |
|--------|-----------------|
| `bgw.py` | `requests`, `playwright` |
| `usg.py` | `requests`, `python-dotenv`, `paramiko` (SSH/DNS subcommand only) |
| `resolve.py` | `dnspython` |
| `snapshot.py` | `requests`, `python-dotenv`, `paramiko`, `dnspython`, `playwright` |
| `isp_status.py` | `requests`, `python-dotenv` |
| `profile.py` | `playwright` |
| `wifi-diag.py` | `requests` |
| `unifi-wifi.py` | `requests`, `python-dotenv` |
| `unifi-api.py` | `requests`, `python-dotenv` |

All unique network deps: `requests`, `python-dotenv`, `playwright`, `paramiko`, `dnspython`

---

### Task 1: Update pyproject.toml

**Files:**
- Modify: `pyproject.toml`

**Step 1: Edit pyproject.toml**

Replace the entire file with:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["climate", "network"]

[project]
name = "picklehome"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # climate
    "python-ecobee-api==0.3.2",
    "keyring>=24",
    "pyyaml>=6",
    # network
    "requests>=2.32",
    "python-dotenv>=1.0",
    "playwright>=1.40",
    "paramiko>=3.0",
    "dnspython>=2.6",
]

[dependency-groups]
dev = [
    "pytest>=8",
]
```

**Step 2: Verify pyproject.toml is valid TOML**

```bash
python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))" && echo OK
```

Expected: `OK`

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: rename project to picklehome, add network deps"
```

---

### Task 2: Create network package

**Files:**
- Create: `network/__init__.py`

**Step 1: Create the package init**

Create `network/__init__.py` as an empty file (just the package marker):

```python
```

(Empty file; hatchling needs it to recognize `network/` as an installable package.)

**Step 2: Run uv sync to install updated deps and lock**

```bash
uv sync
```

Expected: uv resolves all deps, installs them into `.venv`, updates `uv.lock`. May take a minute for playwright's browser binaries to be noted (though they are fetched separately via `playwright install`).

**Step 3: Verify the network package is importable**

```bash
uv run python -c "import network; print('network package OK')"
```

Expected: `network package OK`

**Step 4: Commit**

```bash
git add network/__init__.py uv.lock
git commit -m "feat: add network as installable package, sync lockfile"
```

---

### Task 3: Extract shared UniFi auth into network/unifi.py

Three scripts (`unifi-api.py`, `unifi-wifi.py`, `usg.py`) contain byte-for-byte identical `session()` functions. Extract to a shared module.

**Files:**
- Create: `network/unifi.py`
- Modify: `network/unifi-api.py`
- Modify: `network/unifi-wifi.py`
- Modify: `network/usg.py`

**Step 1: Create network/unifi.py**

```python
"""Shared UniFi CloudKey authentication."""

import os
import sys
import warnings

import requests
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CLOUDKEY = "https://192.168.1.57"
LEGACY = f"{CLOUDKEY}/proxy/network/api/s/default"
BASE = f"{CLOUDKEY}/proxy/network/integration/v1"


def session() -> requests.Session:
    """Return an authenticated requests.Session for the UniFi CloudKey API."""
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        sys.exit("UNIFI_API_KEY not set: add it to .env")
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    return s
```

Note: `CLOUDKEY`, `LEGACY`, and `BASE` constants are also duplicated across scripts; centralizing them here avoids three separate definitions.

**Step 2: Update network/unifi-api.py**

Remove the local `session()` definition and the duplicate constants. Replace with an import from `network.unifi`:

At the top of the file, after the docstring, change:

```python
import argparse
import json
import os
import sys
import warnings

import requests
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CLOUDKEY = "https://192.168.1.57"
LEGACY = f"{CLOUDKEY}/proxy/network/api/s/default"


def session():
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        sys.exit("UNIFI_API_KEY not set: add it to .env")
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    return s
```

To:

```python
import argparse
import json
import sys

from network.unifi import LEGACY, session
```

**Step 3: Update network/unifi-wifi.py**

Same pattern. Find and remove:

```python
import os
import warnings

import requests
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CLOUDKEY = "https://192.168.1.57"
LEGACY = f"{CLOUDKEY}/proxy/network/api/s/default"


def session():
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        sys.exit("UNIFI_API_KEY not set: add it to .env")
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    return s
```

Add to imports:

```python
from network.unifi import CLOUDKEY, LEGACY, session
```

Check `unifi-wifi.py` for any use of `BASE` (the integration/v1 URL); if present, also import `BASE` from `network.unifi`.

**Step 4: Update network/usg.py**

Same pattern. `usg.py` uses both `CLOUDKEY`, `BASE`, and `LEGACY`; check which are referenced after the session() block and import accordingly.

Find and remove the local `session()` + constants block, add:

```python
from network.unifi import BASE, CLOUDKEY, LEGACY, session
```

**Step 5: Verify scripts still work**

```bash
uv run python -c "from network.unifi import session; print('unifi module OK')"
uv run network/unifi-api.py get /stat/site
uv run network/unifi-wifi.py aps
uv run network/usg.py wan
```

Expected: no import errors; each script produces its normal output.

**Step 6: Commit**

```bash
git add network/unifi.py network/unifi-api.py network/unifi-wifi.py network/usg.py
git commit -m "refactor: extract shared UniFi auth into network/unifi.py"
```

---

### Task 4: Update Justfile: drop --with flags

Now that all deps are in the lockfile and installed by `uv sync`, the `--with` flags in the Justfile are redundant and should be removed. Scripts run as `uv run <script>` and get all deps from the venv.

**Files:**
- Modify: `Justfile`

**Step 1: Update each network recipe**

Change:

```just
network-status zip="":
    uv run --with requests --with python-dotenv --with playwright network/isp_status.py {{ if zip != "" { "--zip " + zip } else { "" } }}

wifi-diag *ARGS:
    uv run --with requests network/wifi-diag.py {{ARGS}}

unifi-wifi *ARGS:
    uv run --with requests --with python-dotenv network/unifi-wifi.py {{ARGS}}

unifi-api *ARGS:
    uv run --with requests --with python-dotenv network/unifi-api.py {{ARGS}}
```

To:

```just
network-status zip="":
    uv run network/isp_status.py {{ if zip != "" { "--zip " + zip } else { "" } }}

wifi-diag *ARGS:
    uv run network/wifi-diag.py {{ARGS}}

unifi-wifi *ARGS:
    uv run network/unifi-wifi.py {{ARGS}}

unifi-api *ARGS:
    uv run network/unifi-api.py {{ARGS}}
```

Also check for `bgw.py`, `profile.py`, `resolve.py`, `snapshot.py` recipes; add them if missing or update if present.

**Step 2: Verify just --list still shows all expected tasks**

```bash
just --list
```

Expected: all climate and network tasks present; no tasks silently dropped.

**Step 3: Smoke test a recipe**

```bash
just unifi-api get /stat/site
```

Expected: JSON output, no "module not found" errors.

**Step 4: Commit**

```bash
git add Justfile
git commit -m "chore: drop --with flags from network recipes now that deps are in lockfile"
```

---

### Task 5: Update network/CLAUDE.md usage examples

The `CLAUDE.md` in `network/` documents all the `uv run --with ...` incantations. Update them to reflect the new simpler form.

**Files:**
- Modify: `network/CLAUDE.md`

**Step 1: Replace all `uv run --with ...` examples**

Search for every `uv run --with` line and replace with the bare `uv run` equivalent. Example:

Before:
```
uv run --with requests --with python-dotenv network/unifi-wifi.py aps
```

After:
```
uv run network/unifi-wifi.py aps
# or: just unifi-wifi aps
```

Prefer showing `just` as the primary invocation since that's the standard workflow.

**Step 2: Commit**

```bash
git add network/CLAUDE.md
git commit -m "docs: update network/CLAUDE.md to reflect unified dep management"
```

---

## Verification checklist

After all tasks complete:

- [ ] `python3 -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"`: valid TOML
- [ ] `uv sync`: exits 0, lockfile updated
- [ ] `uv run python -c "import network; import climate"`: both packages importable
- [ ] `just --list`: all expected tasks present
- [ ] `just climate-status`: climate scripts still work
- [ ] `just unifi-api get /stat/site`: UniFi auth via shared module works
- [ ] `just unifi-wifi aps`: UniFi WiFi via shared module works
- [ ] `just network-status`: ISP status runs
- [ ] `just wifi-diag --no-trace --no-speed`: quick WiFi check runs
