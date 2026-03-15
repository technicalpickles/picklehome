---
title: 'Ecobee Schedule Sync'
slug: 'ecobee-schedule-sync'
created: '2026-03-15'
status: 'completed'
stepsCompleted: [1, 2, 3, 4]
tech_stack: ['Python 3.12+', 'uv', 'mise', 'just', 'python-ecobee-api==0.3.2', 'keyring', 'pyyaml']
files_to_modify:
  - '.gitignore'
  - '.mise.toml'
  - 'pyproject.toml'
  - 'ecobee/__init__.py'
  - 'ecobee/auth.py'
  - 'ecobee/schedule.py'
  - 'ecobee/sync.py'
  - 'ecobee/schedule.yaml'
  - 'Justfile'
  - 'docs/ecobee-setup.md'
code_patterns:
  - 'keychain-only: all credentials stored in macOS Keychain; no env vars, no 1Password for now'
  - 'library-auth: KeychainEcobee(Ecobee) subclass overrides _write_config() for Keychain integration'
  - 'no-circular-imports: auth.py owns KeychainEcobee subclass and factory; schedule.py takes ecobee object as parameter'
  - 'read-before-write: always GET current program before POSTing schedule update'
  - 'auto-token-refresh: _request_with_refresh() in pyecobee handles code-14 expiry transparently; _write_config() hook saves new tokens to Keychain'
  - 'forward-fill-inclusive: expand_day fills range [slot, next_slot) for intermediate; [slot, 48) for last'
  - 'path-relative-to-file: default schedule path resolved relative to sync.py, not cwd'
  - 'none-check-after-request: _request_with_refresh returns None on network/timeout/non-token errors; always check before subscripting'
  - 'endpoint-name-not-url: _request_with_refresh takes endpoint name (e.g. ECOBEE_ENDPOINT_THERMOSTAT) not a full URL'
test_patterns: ['manual integration test only; run just ecobee-sync-dry to verify without pushing']
---

## Review Notes
- Adversarial review completed
- Findings: 11 total, 9 fixed, 2 skipped (by-design: F8 race window per spec, F9 private API per spec)
- Resolution approach: auto-fix

# Tech-Spec: Ecobee Schedule Sync

**Created:** 2026-03-15

## Overview

### Problem Statement

The Ecobee thermostat weekly schedule cannot be managed in a version-controlled, scriptable way. Updating it requires navigating the Ecobee web/app UI manually. When switching from Google Home management, the schedule was lost and must be re-entered by hand each time.

### Solution

A YAML file defines the weekly thermostat schedule using human-readable time transitions (e.g., `06:30: home`). A Python script reads the YAML, validates climate references against the live thermostat, expands transitions to Ecobee's 7×48-slot format, reads the current thermostat program to preserve climate temperature settings, and pushes the updated schedule via the Ecobee API. All invocation is via `just` targets. All credentials and tokens are stored exclusively in macOS Keychain — never committed to the repo.

The `python-ecobee-api==0.3.2` library (the same library used by Home Assistant) handles OAuth2 token management. A `KeychainEcobee` subclass overrides the single `_write_config()` hook to persist tokens to macOS Keychain instead of a file.

### Scope

**In Scope:**
- YAML schedule format for defining weekly comfort profile assignments (no device IDs in YAML)
- Ecobee developer app registration instructions (in repo docs)
- First-time OAuth2 PIN-based authorization flow with token + thermostat ID storage in macOS Keychain
- Automatic access token refresh using stored refresh token (handled transparently by `python-ecobee-api`)
- `just ecobee-auth`: PIN flow + thermostat discovery; stores all credentials in Keychain; prints available climates
- `just ecobee-sync`: parse YAML → validate climates → expand slots → read current program → push
- `just ecobee-sync-dry`: parse YAML → validate climates → GET current program → print resolved schedule; no POST
- `mise` + `uv` toolchain setup

**Out of Scope:**
- 1Password / env var credential injection (future work)
- Google Home integration
- Ecobee "holds" or temporary overrides
- Multiple thermostat support (single thermostat for now)
- Any non-Ecobee smart home devices
- Automated/scheduled sync (cron/launchd)

---

## Context for Development

### Module Dependency Graph

```
ecobee/
├── auth.py      # KeychainEcobee(Ecobee), make_ecobee(), pin_auth_flow()
│                #   imports: pyecobee.Ecobee, keyring, sys, time
├── schedule.py  # YAML parse/validate, slot expansion, API calls
│                #   imports: json, pathlib, sys, yaml, pyecobee.const.ECOBEE_ENDPOINT_THERMOSTAT
└── sync.py      # CLI entry point
                 #   imports: auth, schedule, argparse, sys, pathlib, pyecobee.errors.InvalidTokenError
```

No circular imports. `auth.py` owns `KeychainEcobee`, all Keychain I/O, and the `make_ecobee()` factory. `schedule.py` imports nothing from `ecobee.auth` — it receives the `KeychainEcobee` object as a parameter. `sync.py` calls `auth.make_ecobee()` and passes the result into schedule functions.

### Library: `python-ecobee-api==0.3.2`

This is the same library used by Home Assistant's Ecobee integration. Key API (verified from source):

- `from pyecobee import Ecobee` — main class
- `from pyecobee.const import ECOBEE_ENDPOINT_THERMOSTAT` — endpoint name constant (`"thermostat"`)
- `from pyecobee.errors import InvalidTokenError` — raised for token invalid
- `Ecobee(config={"API_KEY": key, "ACCESS_TOKEN": at, "REFRESH_TOKEN": rt})` — constructor; fields use string constant names from `pyecobee.const`
- `ecobee.request_pin()` — initiates PIN auth flow; **returns `True`/`False`** (bool); on success sets `ecobee.pin` (the PIN string) and `ecobee.authorization_code` internally; `expires_in` and `interval` are NOT stored on the object — use hardcoded defaults: 9-minute expiry, 30-second poll interval
- `ecobee.request_tokens()` — exchanges `ecobee.authorization_code` for tokens; **returns `True`/`False`**; on success sets `ecobee.access_token`, `ecobee.refresh_token`, and calls `_write_config()`; returns `False` for BOTH pending and error states (indistinguishable)
- `ecobee.refresh_tokens()` — refreshes using `ecobee.refresh_token`; calls `_write_config()` on success
- `ecobee.get_thermostats()` — fetches all registered thermostats; stores in `ecobee.thermostats` (list of dicts); **returns `True`/`False`**; includes full program data (`includeProgram: true`); raises `InvalidTokenError` if tokens are invalid
- `ecobee._request_with_refresh(method, endpoint, log_msg_action, params=None, body=None)` — makes an authenticated request using endpoint **name** (e.g. `ECOBEE_ENDPOINT_THERMOSTAT`, not a full URL); constructs URL as `https://api.ecobee.com/1/{endpoint}`; on `ExpiredTokenError` (code 14) calls `refresh_tokens()` and retries once; raises `InvalidTokenError` for codes 1 or 16; **returns `None` on all other errors** (network, timeout, non-500 HTTP) — these are only logged; always check return value before subscripting
- `ecobee.access_token`, `ecobee.refresh_token`, `ecobee.pin`, `ecobee.authorization_code` — instance attributes
- `ecobee._write_config()` — called after every successful token write; override this single method for custom storage; no need to call `super()._write_config()` — the base implementation only updates the in-memory `self.config` dict which is not read by any method after construction

**`_write_config()` is the single integration point.** It is called by both `request_tokens()` and `refresh_tokens()`, so overriding it once is sufficient to intercept all token saves.

**`InvalidTokenError`** (`pyecobee.errors.InvalidTokenError`) is raised by `_request_with_refresh()` for HTTP-500 responses with status code 1 or 16 (token invalid / revoked). Callers catch this and exit with code 1.

**`_request_with_refresh` returns `None` silently on non-token errors.** All network errors, timeouts, and unexpected HTTP responses are logged by the library but NOT raised — the method returns `None`. Callers must check the return value and raise their own `RuntimeError` if it is `None`.

### Codebase Patterns

- **Clean slate**: no existing conventions; establishes patterns for future device subdirectories
- **Public repo — nothing sensitive in files**: thermostat_id, API key, and tokens are all in macOS Keychain. `schedule.yaml` contains only schedule data (climate names and times), safe to commit.
- **Keychain-only credentials**: no env var fallbacks in this version
- **Toolchain**: `mise` manages Python version via `.mise.toml`; `uv` manages virtualenv/deps; `just` is the user-facing interface
- **Library auth**: `KeychainEcobee` subclass; `_write_config()` override is the entire Keychain integration for tokens; token refresh is transparent
- **Read-before-write**: always GET current `program` before POSTing — preserves `climates` temperature/fan settings; also used by dry-run for climate validation
- **Slot expansion**: `expand_day` uses `range(slot, next_slot)` for intermediate transitions and `range(slot, 48)` for the last — inclusive of slot 47 (23:30)
- **Default path relative to file**: `--schedule` default resolved as `Path(__file__).parent / "schedule.yaml"` — works regardless of cwd

### Credential Mapping Table

| Purpose | Keychain username | Notes |
|---------|------------------|-------|
| Ecobee developer API key | `api_key` | Set once; never rotates |
| OAuth2 access token | `access_token` | Rotates hourly; auto-refreshed by library |
| OAuth2 refresh token | `refresh_token` | Rotates on every exchange; `_write_config()` saves immediately |
| Thermostat identifier | `thermostat_id` | Set once during `just ecobee-auth` |

All entries use Keychain service name `"picklehome-ecobee"`.

### Files to Reference

| File | Purpose |
|------|---------|
| `.gitignore` | Excludes credentials, venv, bytecode — see Task 1 |
| `.mise.toml` | Python 3.12 + pinned uv version |
| `pyproject.toml` | Full project metadata, deps, hatchling config |
| `ecobee/__init__.py` | Empty package marker |
| `ecobee/auth.py` | `KeychainEcobee` subclass, Keychain r/w, PIN flow |
| `ecobee/schedule.py` | YAML parse/validate, slot expansion, API calls |
| `ecobee/sync.py` | CLI entry point |
| `ecobee/schedule.yaml` | User-defined weekly schedule (safe to commit) |
| `Justfile` | `ecobee-auth`, `ecobee-sync`, `ecobee-sync-dry` |
| `docs/ecobee-setup.md` | Setup guide |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | User/config error (missing credentials, bad YAML, unknown climate, invalid token) |
| 2 | Network/transport error |
| 3 | Ecobee API error (non-zero status code other than recoverable token expiry) |

### Technical Decisions

- **Language**: Python 3.12+ via mise
- **Package manager**: `uv` with committed `uv.lock` for reproducibility
- **HTTP / Auth**: `python-ecobee-api==0.3.2` — handles token management; `KeychainEcobee` subclass persists to macOS Keychain via `_write_config()` override
- **Credential storage**: `keyring` library, macOS Keychain, service `"picklehome-ecobee"`
- **Task runner**: `just`; `set dotenv-load` enabled (`.env` supported but not required)
- **Entry point**: `uv run python -m ecobee.sync` — no installed script

### Ecobee Schedule Structure

- `program.schedule`: 7-element array, index 0=Sunday … 6=Saturday; each element = 48 `climateRef` strings
- Slot formula: `slot = hour * 2 + minute // 30` (slot 0=00:00, slot 16=08:00, slot 47=23:30)
- Default `climateRef` values: `"home"`, `"away"`, `"sleep"`; custom climates have server-generated refs
- Full `climates` array must be re-sent with every POST to preserve temperature settings

### YAML Schedule Format

`thermostat_id` is NOT in `schedule.yaml` — it lives in Keychain. `schedule.yaml` is safe to commit.

```yaml
# ecobee/schedule.yaml
# Climate values must be climateRef strings from your Ecobee thermostat.
# Defaults: home, away, sleep. Custom climates shown by 'just ecobee-auth'.
# All times must be on 30-minute boundaries (:00 or :30).
# Every day must start with time: "00:00". All 7 days are required.

schedule:
  _weekday: &weekday
    - time: "00:00"
      climate: sleep
    - time: "06:30"
      climate: home
    - time: "08:30"
      climate: away
    - time: "17:00"
      climate: home
    - time: "22:00"
      climate: sleep

  sunday:
    - time: "00:00"
      climate: sleep
    - time: "08:00"
      climate: home
    - time: "23:00"
      climate: sleep
  monday: *weekday
  tuesday: *weekday
  wednesday: *weekday
  thursday: *weekday
  friday: *weekday
  saturday:
    - time: "00:00"
      climate: sleep
    - time: "08:00"
      climate: home
    - time: "23:00"
      climate: sleep
```

Validation rules (all enforced before any API call):
1. All 7 day keys required; raise `ValueError` listing missing days
2. Each day's first entry must be `time: "00:00"`; raise `ValueError` naming the day
3. All times must be 30-minute aligned (minute == 0 or 30); raise `ValueError` with `"Use :00 or :30 — Ecobee uses 30-minute slots"`
4. Hour must be in `[0, 23]`; raise `ValueError` with `"Invalid hour in time {time_str}"`
5. All climate values validated against live `climateRef` values from thermostat after GET; raise `ValueError` listing unknowns and valid options

---

## Implementation Plan

### Tasks

- [x] **Task 1: Repo scaffolding**
  - File: `.gitignore`
  - Action: Create with exactly these entries:
    ```
    # Python
    __pycache__/
    *.pyc
    .venv/

    # Credentials — never commit
    .env

    # OS
    .DS_Store
    ```
  - Notes: `uv.lock` committed (reproducibility). `schedule.yaml` committed (no secrets).

- [x] **Task 2: Toolchain config**
  - Files: `.mise.toml`, `pyproject.toml`
  - `.mise.toml`:
    ```toml
    [tools]
    python = "3.12"
    uv = "0.6.6"   # substitute current stable uv version if 0.6.6 is unavailable
    ```
  - `pyproject.toml`:
    ```toml
    [build-system]
    requires = ["hatchling"]
    build-backend = "hatchling.build"

    [tool.hatch.build.targets.wheel]
    packages = ["ecobee"]

    [project]
    name = "picklehome-ecobee"
    version = "0.1.0"
    requires-python = ">=3.12"
    dependencies = [
        "python-ecobee-api==0.3.2",
        "keyring>=24",
        "pyyaml>=6",
    ]
    ```
  - Notes: No `[project.scripts]` — Justfile uses `-m ecobee.sync` as canonical entry point.

- [x] **Task 3: Justfile**
  - File: `Justfile`
  - Action:
    ```makefile
    set dotenv-load

    # First-time setup: PIN flow + thermostat discovery
    ecobee-auth:
        uv run python -m ecobee.sync auth

    # Push schedule.yaml to Ecobee (pass --schedule PATH to override default)
    ecobee-sync *ARGS:
        uv run python -m ecobee.sync sync {{ARGS}}

    # Install dependencies (run once after clone)
    install:
        uv sync

    # Preview expanded schedule without pushing (pass --schedule PATH to override default)
    ecobee-sync-dry *ARGS:
        uv run python -m ecobee.sync sync --dry-run {{ARGS}}
    ```
  - Note: `*ARGS` allows `just ecobee-sync --schedule /path/to/other.yaml` and `just ecobee-sync-dry --schedule /path/to/other.yaml`; `{{ARGS}}` expands to whatever extra args were passed

- [x] **Task 4: `ecobee/__init__.py`**
  - `ecobee/__init__.py`: empty file

- [x] **Task 5: `ecobee/auth.py` — KeychainEcobee subclass and OAuth2**
  - File: `ecobee/auth.py`
  - Imports: `keyring`, `sys`, `time`, `pyecobee.Ecobee`

  **Constants:**
  ```python
  KEYCHAIN_SERVICE = "picklehome-ecobee"
  # Standard Ecobee PIN auth values (not exposed by library after request_pin())
  PIN_EXPIRY_SECONDS = 9 * 60   # 9 minutes
  PIN_POLL_INTERVAL = 30        # seconds between request_tokens() calls
  ```

  **`KeychainEcobee(Ecobee)` subclass:**
  ```python
  class KeychainEcobee(Ecobee):
      def _write_config(self) -> None:
          if self.access_token:
              keyring.set_password(KEYCHAIN_SERVICE, "access_token", self.access_token)
          if self.refresh_token:
              keyring.set_password(KEYCHAIN_SERVICE, "refresh_token", self.refresh_token)
  ```
  This single override is the complete Keychain integration for tokens. It is called automatically by the library after every `request_tokens()` and `refresh_tokens()` call — no other token-saving code is needed anywhere. Do NOT call `super()._write_config()` — the base implementation only updates `self.config` (an in-memory dict not read after construction); skipping it has no side effects.

  **`get_credential(key: str) -> str | None`**
  - Returns `keyring.get_password(KEYCHAIN_SERVICE, key)` or `None`

  **`save_credential(key: str, value: str) -> None`**
  - Calls `keyring.set_password(KEYCHAIN_SERVICE, key, value)`

  **`require_credential(key: str, missing_message: str) -> str`**
  - Calls `get_credential(key)`; if `None`, prints `missing_message` and calls `sys.exit(1)`
  - Returns the value

  **`get_api_key() -> str`**
  - `require_credential("api_key", "Ecobee API key not found. See docs/ecobee-setup.md.")`

  **`get_thermostat_id() -> str`**
  - `require_credential("thermostat_id", "Thermostat ID not found. Run 'just ecobee-auth' first.")`

  **`make_ecobee() -> KeychainEcobee`**
  - Calls `get_api_key()` (exits if missing)
  - Reads `refresh_token` from Keychain via `get_credential()`
  - If `refresh_token` is `None`/empty: prints `"Ecobee tokens not found. Run 'just ecobee-auth' to authorize."` and `sys.exit(1)` — the refresh token is the critical credential; access token can be missing (library will refresh it transparently)
  - Reads `access_token` from Keychain (may be `None`; pass as empty string `""` if missing)
  - Returns:
    ```python
    KeychainEcobee(config={
        "API_KEY": api_key,
        "ACCESS_TOKEN": access_token or "",
        "REFRESH_TOKEN": refresh_token,
    })
    ```
  - Note: use raw string literals `"API_KEY"`, `"ACCESS_TOKEN"`, `"REFRESH_TOKEN"` directly — these match `pyecobee.const.ECOBEE_API_KEY` etc. by value; do NOT import those constants into `auth.py`, as it adds unnecessary coupling

  **`pin_auth_flow(api_key: str) -> None`**
  - Creates `ecobee = KeychainEcobee(config={"API_KEY": api_key})`
  - Calls `result = ecobee.request_pin()`; if `False`: print `"Failed to get PIN from Ecobee. Check your API key and network connection."` and `sys.exit(1)`
  - `request_pin()` sets `ecobee.pin` (the PIN string) and `ecobee.authorization_code` internally — no manual attribute assignment needed
  - `expires_in` and `interval` are NOT stored by the library; use constants `PIN_EXPIRY_SECONDS` and `PIN_POLL_INTERVAL`
  - Print:
    ```
    Authorization required!
      PIN: {ecobee.pin}
      1. Go to https://www.ecobee.com → My Apps → Add Application
      2. Enter PIN above. You have approximately 9 minutes.

    Waiting for authorization (Ctrl-C to cancel)...
    ```
  - Poll loop — `deadline = time.time() + PIN_EXPIRY_SECONDS`:
    - Wrap entire loop in `try/except KeyboardInterrupt`: print `"\nCancelled. Re-run 'just ecobee-auth'."`, `sys.exit(0)`
    - `while time.time() < deadline`:
      - Call `result = ecobee.request_tokens()`
      - If `result is True`: break (success; `_write_config()` already called by library, tokens already in Keychain)
      - Else: print `.` (no newline, `flush=True`), `time.sleep(PIN_POLL_INTERVAL)`, continue
    - After loop (deadline exceeded without break): print `"\nTimed out waiting for authorization. Re-run 'just ecobee-auth'."`, `sys.exit(1)`
    - Note: `request_tokens()` returns `False` for both "pending" and "error" states — the loop treats both as "keep waiting" until the deadline; this is acceptable given the 9-minute window
  - Call `_discover_and_save_thermostat(ecobee)` (defined below)
  - Print `"\nSetup complete! Tokens and thermostat saved to Keychain."`

  **`_discover_and_save_thermostat(ecobee: KeychainEcobee) -> str`**
  - Calls `success = ecobee.get_thermostats()` — populates `ecobee.thermostats` with full thermostat dicts (including program data); let `InvalidTokenError` propagate
  - If `success is False` or `ecobee.thermostats` is falsy: print `"Failed to fetch thermostat list from Ecobee."` and `sys.exit(2)`
  - `ecobee.thermostats` is a list of dicts with fields including `identifier` and `name`
  - If 1 thermostat: auto-selects, no prompt
  - If multiple: prints numbered list `1. {name} (ID: {identifier})` and loops `input("Select [1-N]: ")` until valid integer in range — handles `ValueError` and out-of-range with `"Invalid selection, try again."`
  - Saves: `save_credential("thermostat_id", identifier)`
  - Climate list is already in `ecobee.thermostats[index]["program"]["climates"]` (no second API call needed — `get_thermostats()` includes `includeProgram: true`)
  - Prints:
    ```
    Thermostat: {name} (ID: {identifier})
    Available climates (use these in schedule.yaml):
      - home
      - away
      - sleep
      (- custom_ref  ← any custom climates found)
    ```
  - Returns `identifier`

- [x] **Task 6: `ecobee/schedule.py` — parsing, validation, API**
  - File: `ecobee/schedule.py`
  - Imports: `json`, `pathlib.Path`, `sys`, `yaml`, `pyecobee.const.ECOBEE_ENDPOINT_THERMOSTAT`
  - Does NOT import `requests` or anything from `ecobee.auth` — all HTTP goes through the `ecobee` object passed as a parameter

  **`get_current_program(ecobee, thermostat_id: str) -> dict`**
  - Calls `success = ecobee.get_thermostats()` — populates `ecobee.thermostats`; raises `InvalidTokenError` on invalid tokens; returns `False` (not raises) on network/timeout errors
  - Note: calling `get_thermostats()` replaces `ecobee.thermostats` in-place; do not rely on its previous value after this call
  - If `success is False` or `ecobee.thermostats` is falsy: raise `RuntimeError("Failed to fetch thermostat data from Ecobee.")`
  - Find the thermostat: `thermostat = next((t for t in ecobee.thermostats if t["identifier"] == thermostat_id), None)`
  - If `thermostat is None`: raise `LookupError(f"Thermostat {thermostat_id} not found. Re-run 'just ecobee-auth'.")` — use `LookupError` (not `RuntimeError`) so `sync.py` can distinguish this config error from network errors and exit with code 1
  - Returns `thermostat["program"]`
  - Let `InvalidTokenError` propagate to `sync.py`

  **`push_schedule(ecobee, thermostat_id: str, schedule_array: list, climates: list) -> None`**
  - Body:
    ```python
    body = {
        "selection": {
            "selectionType": "thermostats",
            "selectionMatch": thermostat_id
        },
        "thermostat": {
            "program": {
                "schedule": schedule_array,
                "climates": climates
            }
        }
    }
    ```
  - Calls `response = ecobee._request_with_refresh("POST", ECOBEE_ENDPOINT_THERMOSTAT, "push schedule", body=body)`
  - Note: `body=` not `json=` — this is the library's parameter name; the library internally passes it as `json=body` to `requests.request()`; no `format=json` param needed (the library sets Content-Type headers automatically)
  - If `response is None`: raise `RuntimeError("Failed to push schedule to Ecobee.")` — generic message; `_request_with_refresh` may return `None` for network errors, timeouts, or unexpected API errors, so do not attribute it to network specifically
  - Let `InvalidTokenError` propagate to `sync.py`

  **`load_schedule(path: str | Path) -> dict`**
  - Reads file at `path`; on `FileNotFoundError`: prints `"Schedule file not found: {path}"` and `sys.exit(1)`
  - Calls `yaml.safe_load()`; if result is `None` or not a dict: prints `"schedule.yaml is empty or invalid"` and `sys.exit(1)`
  - If no `schedule` key: prints `"schedule.yaml must have a top-level 'schedule' key"` and `sys.exit(1)`
  - Returns the parsed dict (contains `schedule` key)

  **`time_to_slot(time_str: str) -> int`**
  - Parses `"HH:MM"`; raises `ValueError(f"Invalid time format: {time_str} — expected HH:MM")` if not parseable
  - Validates `0 <= hour <= 23`; raises `ValueError(f"Invalid hour in {time_str}")`
  - Validates `minute in (0, 30)`; raises `ValueError(f"Time {time_str} not 30-minute aligned. Use :00 or :30 — Ecobee uses 30-minute slots.")`
  - Returns `hour * 2 + minute // 30`

  **`expand_day(day_name: str, transitions: list[dict]) -> list[str]`**
  - If `transitions` is empty: raise `ValueError(f"Day '{day_name}' has no transitions.")`
  - Validates `transitions[0]["time"] == "00:00"`; raises `ValueError(f"Day '{day_name}': first transition must be time '00:00', got '{transitions[0]['time']}'")`
  - Converts all transitions to `(slot, climate)` pairs via `time_to_slot`
  - Sorts by slot
  - Initialize: `result = [""] * 48`
  - Builds 48-element result list:
    - For each transition `i` where `i < len(transitions) - 1`: fill `result[slot_i : slot_{i+1}]` with `climate_i`
    - For the last transition: fill `result[slot_last : 48]` (inclusive of slot 47)
  - Returns 48-element list

  **`build_schedule_array(schedule_dict: dict) -> list[list[str]]`**
  - Required keys: `["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]`
  - Finds missing keys; raises `ValueError(f"Missing days in schedule: {sorted(missing)}. All 7 days are required.")`
  - Calls `expand_day` for each day
  - Returns list ordered `[sunday, monday, tuesday, wednesday, thursday, friday, saturday]`

  **`validate_climate_refs(schedule_dict: dict, program: dict) -> None`**
  - Extracts valid refs: `{c["climateRef"] for c in program["climates"]}`
  - Collects all unique climate strings used across all values in `schedule_dict` — note: `yaml.safe_load()` preserves `_weekday` (and any other anchor-definition keys) as regular dict entries; iterating all values harmlessly includes them since their climates are the same as the anchored day entries; no false errors will occur
  - Finds unknowns; raises `ValueError(f"Unknown climate(s): {unknowns}. Valid climateRefs for this thermostat: {sorted(valid)}")`

  **`print_schedule_grid(schedule_array: list, program: dict) -> None`**
  - Day name list (index 0–6 matching `schedule_array` order): `["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]`
  - Builds a `climateRef → name` lookup from `program["climates"]`
  - Detects transitions: for each day, find slots where the climate changes from the previous slot
  - Output format — one block per day:
    ```
    Sunday
      00:00  sleep
      08:00  home
      23:00  sleep
    Monday
      00:00  sleep
      06:30  home
      ...
    ```
  - Uses climate `name` (display name) if available in `program["climates"]`, else `climateRef` string
  - Prints header: `"Schedule preview (transitions only):\n"`

- [x] **Task 7: `ecobee/sync.py` — CLI entry point**
  - File: `ecobee/sync.py`
  - Imports: `argparse`, `sys`, `pathlib.Path`, `pyecobee.errors.InvalidTokenError`, `ecobee.auth`, `ecobee.schedule`
  - Note: `LookupError` is a Python builtin — no import needed

  **`DEFAULT_SCHEDULE_PATH`**: `Path(__file__).parent / "schedule.yaml"`

  **`cmd_auth(args) -> None`**:
  ```python
  api_key = auth.get_api_key()
  auth.pin_auth_flow(api_key)
  ```

  **`cmd_sync(args) -> None`**:
  ```python
  ecobee = auth.make_ecobee()
  thermostat_id = auth.get_thermostat_id()

  schedule_data = schedule.load_schedule(args.schedule)
  schedule_dict = schedule_data["schedule"]

  try:
      schedule_array = schedule.build_schedule_array(schedule_dict)
  except ValueError as e:
      print(f"Error in schedule.yaml: {e}")
      sys.exit(1)

  # GET current program (needed for climate validation + preserving temperatures)
  # Note: climate validation is intentionally deferred until after GET,
  # because validate_climate_refs requires the live climates list from the thermostat.
  # Time/format validation (build_schedule_array) runs offline first.
  try:
      program = schedule.get_current_program(ecobee, thermostat_id)
  except InvalidTokenError:
      print("Tokens invalid. Re-run 'just ecobee-auth'.")
      sys.exit(1)
  except LookupError as e:
      # Thermostat ID in Keychain not found on account — config error
      print(f"Error: {e}")
      sys.exit(1)
  except RuntimeError as e:
      # Network / transport / unexpected API failure
      print(f"Error: {e}")
      sys.exit(2)

  try:
      schedule.validate_climate_refs(schedule_dict, program)
  except ValueError as e:
      print(f"Error in schedule.yaml: {e}")
      sys.exit(1)

  if args.dry_run:
      schedule.print_schedule_grid(schedule_array, program)
      print("Dry run complete. No changes pushed.")
      return

  try:
      schedule.push_schedule(ecobee, thermostat_id, schedule_array, program["climates"])
  except InvalidTokenError:
      print("Tokens invalid. Re-run 'just ecobee-auth'.")
      sys.exit(1)
  except RuntimeError as e:
      print(f"Error: {e}")
      sys.exit(2)

  print("Schedule pushed successfully.")
  ```
  Note on unhandled exceptions: `_request_with_refresh` raises only `InvalidTokenError` and `ExpiredTokenError` (the latter handled internally). All other library errors return `None` (caught and converted to `RuntimeError` in `schedule.py`). No other pyecobee exceptions should reach `sync.py`.

  **`main() -> None`**:
  - `argparse` with subcommands `auth` and `sync`
  - `sync` subcommand: `--dry-run` flag (store_true), `--schedule PATH` (default `DEFAULT_SCHEDULE_PATH`)
  - Both subcommands set their `func` attribute; `main()` calls `args.func(args)`
  - Guard: `if __name__ == "__main__": main()`

- [x] **Task 8: `ecobee/schedule.yaml` — example schedule**
  - File: `ecobee/schedule.yaml`
  - Action: Create using the YAML format shown in the Context section (with YAML anchors, no `thermostat_id`)

- [x] **Task 9: `docs/ecobee-setup.md`**
  - File: `docs/ecobee-setup.md`
  - Action: Self-contained setup guide. Include expected output for each step.
    1. **Prerequisites**: install `just`, `mise`, `uv` — link to each tool's install page
    1b. **Install Python deps**: `just install` (runs `uv sync`; creates `.venv/` — do this once after cloning)
    2. **Register Ecobee developer app**: go to `ecobee.com/developers` → create app → copy API key
    3. **Store API key in Keychain** (run `just install` first so `keyring` is available):
       ```bash
       uv run python -c "import keyring; keyring.set_password('picklehome-ecobee', 'api_key', 'YOUR_KEY_HERE')"
       ```
       Expected: macOS Keychain dialog appears requesting permission. Verify stored correctly by running `just ecobee-auth` — it will fail immediately with a clear message if the key is missing.
    4. **Run `just ecobee-auth`**: follow PIN instructions; expected output shows thermostat name, ID, and available climate refs
    5. **Edit `ecobee/schedule.yaml`**: use climate refs shown in step 4 output
    6. **Preview**: `just ecobee-sync-dry` — inspect output; expected: transitions-only grid per day
    7. **Push**: `just ecobee-sync` — verify in Ecobee app
    8. **Troubleshooting**: table of error messages + remediation (re-run auth if locked out; macOS Keychain dialog is expected)

---

### Acceptance Criteria

- [x] **AC 1**: Given no `api_key` in Keychain, when `just ecobee-sync` is run, then the script exits with code 1 and a message referencing `docs/ecobee-setup.md`
- [x] **AC 2**: Given a valid `api_key` in Keychain and no tokens, when `just ecobee-auth` is run, then the script prints the PIN + instructions, polls until authorized, saves `access_token`/`refresh_token`/`thermostat_id` to Keychain, and prints available climate refs
- [x] **AC 3**: Given valid tokens and `schedule.yaml`, when `just ecobee-sync-dry` is run, then the script GETs the current program, validates climate refs, prints a transitions-only schedule grid, prints "Dry run complete", and makes no schedule POST
- [x] **AC 4**: Given valid tokens and `schedule.yaml`, when `just ecobee-sync` is run, then the Ecobee app shows the updated weekly schedule matching the YAML
- [x] **AC 5**: Given an expired `access_token` in Keychain (delete it manually, leave `refresh_token`), when `just ecobee-sync` is run, then: (1) no auth error surfaces to user; (2) a new `access_token` is present in Keychain after the run; (3) a new `refresh_token` is present in Keychain after the run; (4) schedule is updated on the thermostat
- [x] **AC 6**: Given `schedule.yaml` where a day's first transition is not `"00:00"`, when `just ecobee-sync` is run, then script exits code 1 naming the offending day
- [x] **AC 7**: Given `schedule.yaml` with a time not 30-minute aligned (e.g., `"06:45"`), when `just ecobee-sync` is run, then script exits code 1 explaining the 30-minute constraint
- [x] **AC 8**: Given `schedule.yaml` with an hour out of range (e.g., `"25:00"`), when `just ecobee-sync` is run, then script exits code 1 with a clear error
- [x] **AC 9**: Given `schedule.yaml` with a `climate` not matching any `climateRef` on the thermostat, when `just ecobee-sync` is run, then script exits code 1 listing the invalid value and valid options
- [x] **AC 10**: Given `schedule.yaml` missing one or more day keys, when `just ecobee-sync` is run, then script exits code 1 listing missing days
- [x] **AC 11**: Given `schedule.yaml` using YAML anchors for weekday reuse, when `just ecobee-sync` is run, then all anchored days expand correctly to 48 slots
- [x] **AC 12**: Given a successful `just ecobee-sync`, when thermostat program is fetched via API, then `climates` array (temperatures, fan settings) is identical to pre-sync state
- [x] **AC 13**: Given multiple thermostats on the account, when `just ecobee-auth` is run, then the user is prompted to select one by number, invalid input loops with an error, and the chosen thermostat ID is saved to Keychain

---

## Additional Context

### Dependencies

**Python packages** (`pyproject.toml`):
- `python-ecobee-api==0.3.2`
- `keyring>=24`
- `pyyaml>=6`

**External tools** (user-installed):
- `just`, `mise`, `uv`
- Ecobee developer account + API key

### Testing Strategy

- **No automated test suite**
- **Dry-run is the primary pre-flight check**: `just ecobee-sync-dry` — validates YAML, climates, expands schedule, prints grid
- **Manual integration tests**:
  1. `just ecobee-sync-dry` — inspect grid matches intent; no errors
  2. `just ecobee-sync` — verify in Ecobee app; temperatures unchanged
  3. Token refresh: delete `access_token` from Keychain, leave `refresh_token`; run `just ecobee-sync` — verify transparent recovery and new tokens in Keychain
  4. Bad climate: add typo to `schedule.yaml`; run dry-run — verify clear error with valid options
  5. Missing day: remove `friday` from `schedule.yaml`; run dry-run — verify error names the missing day

### Notes

- **Pre-mortem risks**:
  - Ecobee PIN expires in ~9 minutes — instructions must print immediately and clearly
  - macOS Keychain dialog on first access — expected, not a bug
  - If both tokens are lost (Keychain cleared), user must re-run `just ecobee-auth` from scratch
  - `climateRef` for custom climates are server-generated opaque strings — `validate_climate_refs` protects against mismatches; `just ecobee-auth` prints valid refs
  - `_write_config()` is only called on successful token operations — if `request_tokens()` returns `False`, no Keychain write occurs (correct behavior)
  - `get_thermostats()` fetches all thermostat data (runtime, sensors, weather, etc.) on every sync — only `program` is needed; if the Ecobee API rate-limits, this oversized GET is a likely cause; future optimization: use `_request_with_refresh` directly with a minimal selection
  - Additional `_`-prefixed anchor keys under `schedule:` in `schedule.yaml` (e.g., `_weekend: &weekend`) are silently ignored by `build_schedule_array` and harmlessly validated by `validate_climate_refs` — safe to add
- **Future considerations** (out of scope now):
  - 1Password / env var credential injection
  - `just ecobee-list-climates` convenience command
  - Multiple thermostat support
  - Google Home schedule export → YAML
  - Launchd plist for automatic daily sync
