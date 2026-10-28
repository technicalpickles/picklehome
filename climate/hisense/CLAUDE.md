# CLAUDE.md: climate/hisense/

See @README.md for API reference, CLI commands, and the device property model.

## Library source

The `connectlife` package is a pip dependency (pinned in `pyproject.toml`), installed into the venv at `.venv/lib/python3.12/site-packages/connectlife/`. `api.py` has `ConnectLifeApi` (auth flow, the overridable `_client_session()`). `python -m connectlife.dump --username <u> --password <p>` dumps every property each appliance reports, the starting point for confirming device support.
