# CLAUDE.md: climate/blueair/

See @README.md for API reference, CLI commands, and device specifics.

## Library source

The `blueair-api` package is a pip dependency (pinned in `pyproject.toml`), installed into the venv at `.venv/lib/python3.12/site-packages/blueair_api/`. Key files for reference:
- `device_aws.py`: device model, all set_* methods
- `http_aws_blueair.py`: API endpoints, auth flow
- `model_enum.py`: SKU-to-model mapping
