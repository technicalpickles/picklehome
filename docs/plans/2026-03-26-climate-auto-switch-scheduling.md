# Climate Auto-Switch Scheduling on Picklelab

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run `climate comfort-switch auto` on a regular interval on the homelab (picklelab), replacing macOS Keychain-based auth with a cross-platform approach.

**Architecture:** Move the Ecobee API key into `.env` via 1Password (like all other secrets). Store OAuth tokens (access + refresh) in a local JSON file that the code reads/writes at runtime, since tokens rotate on every API call. Deploy as a systemd timer on picklelab.

**Tech Stack:** Python, systemd (timer + service), 1Password CLI (`op`), `uv`

---

## Part 1: Ecobee Auth Migration (Keychain to env + file)

### Task 1: Add Ecobee API key to .env.template

The API key is static and belongs with all the other 1Password-managed secrets.

**Files:**
- Modify: `.env.template`

**Step 1: Add the Ecobee API key reference**

Add after the Ambient Weather section in `.env.template`:

```
# Ecobee thermostat API (1Password item: Ecobee)
ECOBEE_API_KEY={{ op://picklehome/Ecobee/api_key }}
```

**Prerequisite:** The API key must already exist in 1Password under `picklehome/Ecobee/api_key`. If it doesn't, store it first:
```bash
# Find the current key:
keyring get picklehome-ecobee api_key

# Store it in 1Password:
op item create --category=login --vault=picklehome --title="Ecobee" api_key=<the-key>
# OR if item exists:
op item edit Ecobee --vault=picklehome api_key=<the-key>
```

**Step 2: Regenerate .env**

Run: `just dotenv`

**Step 3: Commit**

```
feat(climate): add Ecobee API key to .env.template
```

---

### Task 2: Replace Keychain token storage with local JSON file

The core auth change. Ecobee access/refresh tokens need read AND write, so they live in a local file rather than 1Password.

**Files:**
- Modify: `climate/ecobee/auth.py`
- Create: `tests/climate/ecobee/test_auth.py`

**Step 1: Write failing tests for the new token storage**

Test file: `tests/climate/ecobee/test_auth.py`

```python
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from climate.ecobee.auth import (
    DEFAULT_TOKEN_PATH,
    get_api_key,
    load_tokens,
    save_tokens,
    make_ecobee,
)


def test_default_token_path():
    """Token file lives in ~/.local/state/picklehome/."""
    assert "picklehome" in str(DEFAULT_TOKEN_PATH)
    assert DEFAULT_TOKEN_PATH.name == "ecobee-tokens.json"


def test_get_api_key_from_env(monkeypatch):
    monkeypatch.setenv("ECOBEE_API_KEY", "test-key-123")
    assert get_api_key() == "test-key-123"


def test_get_api_key_missing(monkeypatch):
    monkeypatch.delenv("ECOBEE_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        get_api_key()


def test_save_and_load_tokens(tmp_path):
    token_path = tmp_path / "tokens.json"
    save_tokens("access-abc", "refresh-xyz", token_path)

    tokens = load_tokens(token_path)
    assert tokens == {"access_token": "access-abc", "refresh_token": "refresh-xyz"}


def test_load_tokens_missing_file(tmp_path):
    token_path = tmp_path / "nonexistent.json"
    assert load_tokens(token_path) is None


def test_save_tokens_creates_parent_dir(tmp_path):
    token_path = tmp_path / "sub" / "dir" / "tokens.json"
    save_tokens("a", "r", token_path)
    assert token_path.exists()


def test_token_file_not_world_readable(tmp_path):
    token_path = tmp_path / "tokens.json"
    save_tokens("a", "r", token_path)
    mode = token_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_make_ecobee_with_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("ECOBEE_API_KEY", "test-key")
    token_path = tmp_path / "tokens.json"
    save_tokens("access-tok", "refresh-tok", token_path)

    ecobee = make_ecobee(token_path=token_path)
    assert ecobee.api_key == "test-key"
    assert ecobee.refresh_token == "refresh-tok"


def test_make_ecobee_no_tokens(monkeypatch, tmp_path):
    monkeypatch.setenv("ECOBEE_API_KEY", "test-key")
    token_path = tmp_path / "nonexistent.json"

    with pytest.raises(SystemExit):
        make_ecobee(token_path=token_path)
```

**Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/climate/ecobee/test_auth.py -v`
Expected: ImportError / failures (new functions don't exist yet)

**Step 3: Rewrite `climate/ecobee/auth.py`**

Replace the keyring-based implementation:

```python
import json
import os
import sys
import time
from pathlib import Path

from pyecobee import Ecobee

DEFAULT_TOKEN_PATH = Path.home() / ".local" / "state" / "picklehome" / "ecobee-tokens.json"

# Standard Ecobee PIN auth values (not exposed by library after request_pin())
PIN_EXPIRY_SECONDS = 9 * 60   # 9 minutes
PIN_POLL_INTERVAL = 30        # seconds between request_tokens() calls


def get_api_key() -> str:
    api_key = os.environ.get("ECOBEE_API_KEY")
    if not api_key:
        print("ECOBEE_API_KEY not set. Run 'just dotenv' to generate .env.")
        sys.exit(1)
    return api_key


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


class FileTokenEcobee(Ecobee):
    """Ecobee subclass that persists refreshed tokens to a local JSON file.

    The parent class calls _write_config() after every token refresh.
    """

    def __init__(self, config: dict, token_path: Path = DEFAULT_TOKEN_PATH):
        super().__init__(config=config)
        self._token_path = token_path

    def _write_config(self) -> None:
        if self.access_token and self.refresh_token:
            save_tokens(self.access_token, self.refresh_token, self._token_path)


def make_ecobee(token_path: Path = DEFAULT_TOKEN_PATH) -> FileTokenEcobee:
    api_key = get_api_key()
    tokens = load_tokens(token_path)
    if not tokens or not tokens.get("refresh_token"):
        print("Ecobee tokens not found. Run 'just climate-auth' to authorize.")
        sys.exit(1)
    return FileTokenEcobee(
        config={
            "API_KEY": api_key,
            "ACCESS_TOKEN": tokens.get("access_token", ""),
            "REFRESH_TOKEN": tokens["refresh_token"],
        },
        token_path=token_path,
    )


def _print_thermostat_info(ecobee: FileTokenEcobee) -> None:
    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        print("Failed to fetch thermostat list from Ecobee.")
        sys.exit(2)

    print("\nThermostats on this account (add these to schedule.yaml):")
    for thermostat in ecobee.thermostats:
        identifier = thermostat["identifier"]
        name = thermostat["name"]
        climates = thermostat.get("program", {}).get("climates", [])
        print(f"\n  {name}")
        print(f"    thermostat_id: \"{identifier}\"")
        print(f"    Available climates: {', '.join(c['climateRef'] for c in climates)}")


def list_thermostats() -> None:
    ecobee = make_ecobee()
    _print_thermostat_info(ecobee)


def pin_auth_flow(api_key: str, token_path: Path = DEFAULT_TOKEN_PATH) -> None:
    ecobee = FileTokenEcobee(config={"API_KEY": api_key}, token_path=token_path)
    result = ecobee.request_pin()
    if result is False:
        print("Failed to get PIN from Ecobee. Check your API key and network connection.")
        sys.exit(1)

    print(f"""Authorization required!
  PIN: {ecobee.pin}
  1. Go to https://www.ecobee.com → My Apps → Add Application
  2. Enter PIN above. You have approximately 9 minutes.

Waiting for authorization (Ctrl-C to cancel)...""")

    deadline = time.time() + PIN_EXPIRY_SECONDS
    try:
        while True:
            time.sleep(PIN_POLL_INTERVAL)
            result = ecobee.request_tokens()
            if result is True:
                break
            print(".", end="", flush=True)
            if time.time() >= deadline:
                print("\nTimed out waiting for authorization. Re-run 'just climate-auth'.")
                sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled. Re-run 'just climate-auth'.")
        sys.exit(0)

    _print_thermostat_info(ecobee)
    print(f"\nSetup complete! Tokens saved to {token_path}")
```

**Step 4: Run tests, confirm they pass**

Run: `uv run pytest tests/climate/ecobee/test_auth.py -v`
Expected: all pass

**Step 5: Commit**

```
feat(climate): replace Keychain auth with env var + file-based tokens

Ecobee API key now comes from ECOBEE_API_KEY env var (via .env/1Password).
OAuth tokens are stored in ~/.local/state/picklehome/ecobee-tokens.json
and auto-refreshed on every API call. This makes the climate module
portable to Linux (picklelab) where macOS Keychain isn't available.
```

---

### Task 3: Migrate existing Keychain tokens to the new file

One-time migration on the Mac where tokens currently live.

**Step 1: Read current tokens from Keychain and write to file**

```bash
# Read existing tokens
keyring get picklehome-ecobee api_key
keyring get picklehome-ecobee access_token
keyring get picklehome-ecobee refresh_token

# Write to new location
mkdir -p ~/.local/state/picklehome
cat > ~/.local/state/picklehome/ecobee-tokens.json << 'EOF'
{
  "access_token": "<paste access_token>",
  "refresh_token": "<paste refresh_token>"
}
EOF
chmod 600 ~/.local/state/picklehome/ecobee-tokens.json
```

**Step 2: Verify the new auth works**

Run: `just climate-status`
Expected: thermostat status prints normally

**Step 3: Store API key in 1Password if not already there**

```bash
op item create --category=login --vault=picklehome --title="Ecobee" "api_key=<the-key>"
```

Then regenerate .env: `just dotenv`

---

### Task 4: Remove keyring dependency from Ecobee (cleanup)

**Files:**
- Modify: `pyproject.toml` (check if BlueAir still needs keyring before removing)

**Step 1: Check if keyring is still used**

BlueAir auth (`climate/blueair/auth.py`) still uses keyring. Don't remove the dependency yet, just verify the Ecobee path no longer imports it.

Run: `grep -r "import keyring" climate/ecobee/`
Expected: no matches

**Step 2: Commit (if any cleanup needed)**

No commit needed if Task 2 already removed the import.

---

### Task 5: Update docs

**Files:**
- Modify: `climate/README.md` (Ecobee setup section)

**Step 1: Update the Ecobee setup instructions**

In `climate/README.md`, replace the Ecobee setup section:

```markdown
### Ecobee thermostats

1. Get an API key from the [Ecobee Developer Portal](https://www.ecobee.com/developers/)
2. Store it in 1Password: `op item edit Ecobee --vault=picklehome api_key=<your-key>`
3. Run `just dotenv` to inject it into `.env`
4. Authorize: `just climate-auth` (follows the Ecobee PIN flow, saves tokens to `~/.local/state/picklehome/ecobee-tokens.json`)
5. Thermostats are registered in `config/thermostats.yaml`
```

**Step 2: Update the Architecture section**

Replace the Auth line:

```markdown
- **Auth:** OAuth PIN flow → access + refresh tokens, stored in `~/.local/state/picklehome/ecobee-tokens.json`. API key from `ECOBEE_API_KEY` env var (1Password via `.env`)
- **Token refresh:** The `FileTokenEcobee` subclass overrides `_write_config()` to persist refreshed tokens back to the JSON file automatically
```

**Step 3: Commit**

```
docs(climate): update auth docs for file-based token storage
```

---

## Part 2: Systemd Timer on Picklelab

### Task 6: Create a wrapper script for the comfort-switch

A simple script that the systemd service calls. Handles loading the project env, running uv, and logging.

**Files:**
- Create: `homelab/services/climate-auto-switch/run.sh`

**Step 1: Write the wrapper**

```bash
#!/usr/bin/env bash
# Run climate comfort-switch auto from the picklehome repo.
# Called by the climate-auto-switch systemd timer.
set -euo pipefail

REPO_DIR="${PICKLEHOME_DIR:-/opt/picklehome}"
cd "$REPO_DIR"

# Load .env for ECOBEE_API_KEY, AMBIENT_STATION_MACS, etc.
set -a
source .env
set +a

exec uv run python -m climate.sync comfort-switch auto --clear-holds
```

**Step 2: Commit**

```
feat(homelab): add climate-auto-switch wrapper script
```

---

### Task 7: Create systemd service and timer units

**Files:**
- Create: `homelab/services/climate-auto-switch/climate-auto-switch.service`
- Create: `homelab/services/climate-auto-switch/climate-auto-switch.timer`

**Step 1: Write the service unit**

```ini
[Unit]
Description=Climate comfort-switch auto (outdoor temp check)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/picklehome/homelab/services/climate-auto-switch/run.sh
WorkingDirectory=/opt/picklehome
User=picklehome
Environment=HOME=/home/picklehome

# Token file lives under $HOME/.local/state/picklehome/
# .env provides ECOBEE_API_KEY, AMBIENT_STATION_MACS, etc.

# Restart policy: don't retry on failure, the timer will fire again
```

**Step 2: Write the timer unit**

```ini
[Unit]
Description=Run climate comfort-switch auto every 6 hours

[Timer]
# Fire at 6am, noon, 6pm, midnight
OnCalendar=*-*-* 00,06,12,18:00:00
# Catch up if the machine was off
Persistent=true
# Spread across a 5-minute window to avoid thundering herd
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

**Step 3: Commit**

```
feat(homelab): add systemd timer for climate-auto-switch

Runs comfort-switch auto every 6 hours (midnight, 6am, noon, 6pm).
Checks outdoor temp and switches between heat/cool comfort modes.
```

---

### Task 8: Document the deployment steps

**Files:**
- Modify: `homelab/README.md`

**Step 1: Add a services section**

```markdown
## Services

### climate-auto-switch

Runs `climate comfort-switch auto` every 6 hours via systemd timer. Checks outdoor temperature and switches between heat/cool comfort modes.

**Setup on picklelab:**

```bash
# Clone the repo (if not already)
git clone https://github.com/technicalpickles/picklehome.git /opt/picklehome

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Generate .env from 1Password
cd /opt/picklehome
op signin  # if not already
scripts/dotenv

# Copy token file from Mac (one-time)
scp ~/.local/state/picklehome/ecobee-tokens.json picklelab:~/.local/state/picklehome/

# Install and enable the timer
sudo ln -s /opt/picklehome/homelab/services/climate-auto-switch/climate-auto-switch.service /etc/systemd/system/
sudo ln -s /opt/picklehome/homelab/services/climate-auto-switch/climate-auto-switch.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now climate-auto-switch.timer

# Verify
systemctl status climate-auto-switch.timer
sudo journalctl -u climate-auto-switch.service  # check last run
```

**Manual trigger:**

```bash
sudo systemctl start climate-auto-switch.service
```
```

**Step 2: Commit**

```
docs(homelab): document climate-auto-switch deployment
```

---

## Open Questions

- **Timer interval:** 6 hours (4x/day) seems reasonable for seasonal switching. Weather doesn't change that fast. Could go to every 2 hours if desired.
- **Failure alerting:** The systemd units don't notify on failure yet. Could add `OnFailure=` to email or post to Slack. Worth adding later.
- **BlueAir auth:** Still uses keyring. Out of scope for this plan, but should follow the same migration pattern if BlueAir commands need to run on picklelab.
- **Token bootstrap on picklelab:** The PIN auth flow requires a browser to approve. Run `just climate-auth` on picklelab, then open the Ecobee URL from any browser to approve. Or just copy the token file from the Mac.
