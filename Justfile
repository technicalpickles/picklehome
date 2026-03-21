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

# Discover nearby Ambient Weather stations (--radius N miles)
climate-weather-discover *ARGS:
    uv run python -m climate.sync discover-stations {{ARGS}}

# Show current outdoor temp and comfort mode recommendation
climate-weather *ARGS:
    uv run python -m climate.sync weather {{ARGS}}

# Switch schedule comfort mode: heat | cool | auto
climate-comfort-switch MODE *ARGS:
    uv run python -m climate.sync comfort-switch {{MODE}} {{ARGS}}

# Preview comfort mode switch without writing or syncing
climate-comfort-switch-dry MODE *ARGS:
    uv run python -m climate.sync comfort-switch {{MODE}} --dry-run {{ARGS}}

# Store BlueAir credentials in Keychain
blueair-auth:
    uv run python climate/blueair_cli.py auth

# Discover BlueAir devices and create purifiers.yaml
blueair-discover *ARGS:
    uv run python climate/blueair_cli.py discover {{ARGS}}

# Show purifier status (sensor data, fan, filter life)
blueair-status *ARGS:
    uv run python climate/blueair_cli.py status {{ARGS}}

# ISP and CDN status: Cloudflare + Radar BGP/traffic + RIPE BGP state + AT&T outage by ZIP
network-status zip="":
    uv run network/isp_status.py {{ if zip != "" { "--zip " + zip } else { "" } }}

# Full point-in-time network snapshot: BGW fiber + broadband, USG WAN, DNS, traceroute
network-snapshot *ARGS:
    uv run network/snapshot.py {{ARGS}}

# DNS resolution comparison across Cloudflare, Google, BGW, and USG resolvers
network-resolve *ARGS:
    uv run network/resolve.py {{ARGS}}

# Profile a URL with a headless browser: per-hostname latency and errors
network-profile *ARGS:
    uv run network/profile.py {{ARGS}}

# AT&T BGW gateway diagnostics: just bgw fiber | broadband | trace <ip> | ping <ip> | nslookup <host>
bgw *ARGS:
    uv run network/bgw.py {{ARGS}}

# UniFi USG diagnostics: just usg wan | wan-detail | devices | stats | dns
usg *ARGS:
    uv run network/usg.py {{ARGS}}

# Client WiFi and connectivity diagnostic (run on any Mac in the house)
wifi-diag *ARGS:
    uv run network/wifi-diag.py {{ARGS}}

# UniFi WiFi diagnostics: AP radio stats and per-client signal/retries from the AP side
unifi-wifi *ARGS:
    uv run network/unifi-wifi.py {{ARGS}}

# Raw UniFi API wrapper for debugging: just unifi-api get /stat/device
unifi-api *ARGS:
    uv run network/unifi-api.py {{ARGS}}

# Install dependencies (run once after clone)
install:
    uv sync

# Generate .env from 1Password (run after clone or when secrets change)
dotenv *ARGS:
    scripts/dotenv {{ARGS}}
