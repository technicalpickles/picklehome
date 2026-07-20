# CLAUDE.md: climate/hisense/

See @README.md for API reference, CLI commands, and the device property model.

## Library source

The `connectlife` package is a pip dependency (pinned in `pyproject.toml`),
installed into the venv at `.venv/lib/python3.12/site-packages/connectlife/`.
Key files for reference:
- `api.py`: `ConnectLifeApi` (auth flow, `get_appliances`, `update_appliance`,
  the overridable `_client_session()`)
- `appliance.py`: `ConnectLifeApplianceProperties`, `status_list` and its `convert()`
- `dump.py`: `python -m connectlife.dump --username <u> --password <p>` dumps every
  property each appliance reports (starting point for confirming device support)

## Live calls need the sandbox off this session

The ConnectLife hosts are in `.claude/settings.local.json`, but that is read at
session start. In a session where it was just added, run live `just hisense *`
with the sandbox disabled (the `SandboxConnectLifeApi` trust_env override makes it
sandbox-native once the allowlist is active).
