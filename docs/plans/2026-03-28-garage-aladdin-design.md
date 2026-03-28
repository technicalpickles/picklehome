# Garage Door Integration: Aladdin Connect by Genie

## Overview

Add garage door status and control to picklehome via the Aladdin Connect by Genie smart garage door opener. Uses the official `genie-partner-sdk` Python library with OAuth credentials from the Home Assistant HACS integration.

## Module Structure

```
garage/
├── __init__.py
├── aladdin/
│   ├── __init__.py
│   ├── auth.py        # OAuth flow, token storage/refresh
│   └── client.py      # Wraps genie-partner-sdk, status + control
├── garage_cli.py      # CLI entry point
└── README.md
```

Vendor-specific code lives under `garage/aladdin/`, matching the pattern of `climate/ecobee/` and `climate/blueair/`. CLI sits at the module top level.

## Auth & Secrets

**1Password / `.env.template`:**

- `ALADDIN_EMAIL` - Genie account email
- `ALADDIN_PASSWORD` - Genie account password

API key and OAuth endpoints are constants in code (already public in the HA integration source).

**Token storage:**

- `~/.local/state/picklehome/aladdin-tokens.json`
- `auth.py` authenticates with email/password against Genie's OAuth endpoint, persists access + refresh tokens, refreshes on expiry
- Token file written with 600 permissions
- `just garage auth` handles initial authentication (non-interactive once creds are in `.env`)

## Client

`GarageClient` wraps `genie-partner-sdk`:

- Creates `aiohttp.ClientSession(trust_env=True)` for sandbox proxy compatibility
- `async status()` returns door state (open/closed/opening/closing), battery level, signal strength
- `async open()` / `async close()` sends command, returns resulting state
- Raises with diagnostic context on errors

## CLI

`garage_cli.py` with argparse subcommands:

- `auth` - run OAuth flow, persist tokens
- `status` - print door name, state, battery %
- `open` / `close` - send command, print resulting state

## Justfile

```just
# Aladdin garage door: just garage status | open | close | auth
garage *ARGS:
    uv run python garage/garage_cli.py {{ARGS}}
```

## pyproject.toml

- Add `"garage"` to `tool.hatch.build.targets.wheel.packages`
- Add `"genie-partner-sdk>=1.0.11"` to dependencies

## Future (out of scope)

Automation via `garage/auto_close.py` on a systemd timer (picklelab), similar to `climate-auto-switch`:

- Close door if open longer than N minutes
- Close door at bedtime
- JSONL run log

Deployment would go in `homelab/services/garage-auto-close/`.
