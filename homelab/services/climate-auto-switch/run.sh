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
