set dotenv-load

# First-time setup: PIN flow + thermostat discovery
climate-auth:
    uv run python -m climate.sync auth

# List thermostats and climate refs on this account
climate-list:
    uv run python -m climate.sync list

# Show current thermostat state
climate-status *ARGS:
    uv run python -m climate.sync status {{ARGS}}

# Push schedule.yaml to Ecobee
climate-sync *ARGS:
    uv run python -m climate.sync sync {{ARGS}}

# Preview expanded schedule without pushing
climate-sync-dry *ARGS:
    uv run python -m climate.sync sync --dry-run {{ARGS}}

# Validate schedule.yaml matches the live schedule on Ecobee
climate-validate *ARGS:
    uv run python -m climate.sync validate {{ARGS}}

# Snapshot current comfort mode temps from Ecobee into comforts.yaml
climate-comforts-capture *ARGS:
    uv run python -m climate.sync capture-comforts {{ARGS}}

# Push comforts.yaml setpoints to Ecobee
climate-comforts-sync *ARGS:
    uv run python -m climate.sync sync-comforts {{ARGS}}

# Preview comfort changes without pushing
climate-comforts-sync-dry *ARGS:
    uv run python -m climate.sync sync-comforts --dry-run {{ARGS}}

# ISP and CDN status: Cloudflare + Radar BGP/traffic + RIPE BGP state + AT&T outage by ZIP
network-status zip="":
    uv run --with requests --with python-dotenv --with playwright network/isp_status.py {{ if zip != "" { "--zip " + zip } else { "" } }}

# Client WiFi and connectivity diagnostic (run on any Mac in the house)
wifi-diag *ARGS:
    uv run --with requests network/wifi-diag.py {{ARGS}}

# Install dependencies (run once after clone)
install:
    uv sync

# Generate .env from 1Password (run after clone or when secrets change)
dotenv *ARGS:
    scripts/dotenv {{ARGS}}
