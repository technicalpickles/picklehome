set dotenv-load

# First-time setup: PIN flow + thermostat discovery
ecobee-auth:
    uv run python -m ecobee.sync auth

# List thermostats and climate refs on this account
ecobee-list:
    uv run python -m ecobee.sync list

# Push schedule.yaml to Ecobee (pass --schedule PATH to override default)
ecobee-sync *ARGS:
    uv run python -m ecobee.sync sync {{ARGS}}

# Validate schedule.yaml matches the live schedule on Ecobee
ecobee-validate *ARGS:
    uv run python -m ecobee.sync validate {{ARGS}}

# Snapshot current comfort mode temps from Ecobee into comforts.yaml
ecobee-comforts-capture *ARGS:
    uv run python -m ecobee.sync capture-comforts {{ARGS}}

# Push comforts.yaml setpoints to Ecobee
ecobee-comforts-sync *ARGS:
    uv run python -m ecobee.sync sync-comforts {{ARGS}}

# Preview comfort changes without pushing
ecobee-comforts-sync-dry *ARGS:
    uv run python -m ecobee.sync sync-comforts --dry-run {{ARGS}}

# Install dependencies (run once after clone)
install:
    uv sync

# Generate .env from 1Password (run after clone or when secrets change)
dotenv:
    op inject -i .env.template -o .env

# ISP and CDN status: Cloudflare status + Radar BGP/traffic + AT&T outage by ZIP
isp-status zip="":
    uv run --with requests --with python-dotenv --with playwright network/isp_status.py {{ if zip != "" { "--zip " + zip } else { "" } }}

# Preview expanded schedule without pushing (pass --schedule PATH to override default)
ecobee-sync-dry *ARGS:
    uv run python -m ecobee.sync sync --dry-run {{ARGS}}
