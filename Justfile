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
