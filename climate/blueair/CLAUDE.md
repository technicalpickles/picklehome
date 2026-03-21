# CLAUDE.md — climate/blueair/

See @README.md for API reference, CLI commands, and device specifics.

## Library source

Local clone at `~/github.com/technicalpickles/blueair_api/` for reference. Key files:
- `src/blueair_api/device_aws.py` — device model, all set_* methods
- `src/blueair_api/http_aws_blueair.py` — API endpoints, auth flow
- `src/blueair_api/model_enum.py` — SKU-to-model mapping
