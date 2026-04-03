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

# Show current outdoor air quality and pollen
climate-air-quality:
    uv run python -m climate.sync air-quality

# Switch schedule comfort mode: heat | cool | auto
climate-comfort-switch MODE *ARGS:
    uv run python -m climate.sync comfort-switch {{MODE}} {{ARGS}}

# Preview comfort mode switch without writing or syncing
climate-comfort-switch-dry MODE *ARGS:
    uv run python -m climate.sync comfort-switch {{MODE}} --dry-run {{ARGS}}

# BlueAir purifier management: just blueair auth | discover | status [--json]
blueair *ARGS:
    uv run python climate/blueair_cli.py {{ARGS}}

# Set a blueair property on a specific device (handles quoting): just blueair-set "Bedroom Purifier" brightness 25
blueair-set DEVICE PROPERTY VALUE:
    uv run python climate/blueair_cli.py set {{PROPERTY}} {{VALUE}} --device "{{DEVICE}}"

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

# UniFi network management: just unifi clients | wifi aps | usg stats | ...
unifi *ARGS:
    uv run network/unifi_cli.py {{ARGS}}

# Lutron Caseta lighting: just lutron devices | status | on <device> | off <device> | set <device> <value>
lutron *ARGS:
    uv run lighting/lutron_cli.py {{ARGS}}

# Philips Hue lighting: just hue lights | sensors | buttons | scenes | groups | on <light> | off <light> | set <light> <bri> | scene <scene> | status | pair [<host>]
hue *ARGS:
    uv run lighting/hue_cli.py {{ARGS}}

# Client WiFi and connectivity diagnostic (run on any Mac in the house)
wifi-diag *ARGS:
    uv run network/wifi-diag.py {{ARGS}}

# Install dependencies (run once after clone)
install:
    uv sync

# Generate .env from 1Password (run after clone or when secrets change)
dotenv *ARGS:
    scripts/dotenv {{ARGS}}

# Deploy climate-auto-switch to picklelab (idempotent: first setup or update)
deploy-climate host="picklelab":
    #!/usr/bin/env bash
    set -euo pipefail
    # Pre-flight: check for uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        echo "ERROR: uncommitted changes. Commit or stash first."
        exit 1
    fi
    BRANCH=$(git branch --show-current)
    if [ "$BRANCH" != "main" ]; then
        echo "ERROR: not on main (on $BRANCH). Switch to main first."
        exit 1
    fi
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Pushing to origin/main..."
        git push
    fi
    echo "Deploying commit $(git rev-parse --short HEAD) to {{host}}"
    ssh -t {{host}} "cd /opt/homelab && git pull && homelab/services/climate-auto-switch/deploy.sh"

# Push .env to picklelab (generate locally with `just dotenv` first)
push-env host="picklelab":
    scp .env {{host}}:/opt/homelab/.env

# Seed ecobee token file to picklelab (one-time, from Mac)
seed-climate-tokens host="picklelab":
    ssh -t {{host}} "sudo mkdir -p /srv/data/climate-auto-switch"
    scp ~/.local/state/picklehome/ecobee-tokens.json {{host}}:/tmp/ecobee-tokens.json
    ssh -t {{host}} "sudo mv /tmp/ecobee-tokens.json /srv/data/climate-auto-switch/ && sudo chmod 600 /srv/data/climate-auto-switch/ecobee-tokens.json"

# Show last climate auto-switch state (from picklelab)
climate-check host="picklelab":
    ssh {{host}} "cat /srv/data/climate-auto-switch/last-state.json | python3 -m json.tool"

# Show recent climate auto-switch run log (from picklelab)
climate-log host="picklelab" lines="10":
    ssh {{host}} "tail -n {{lines}} /srv/data/climate-auto-switch/run-log.jsonl | python3 -m json.tool --json-lines"

# Deploy Vikunja to picklelab (idempotent: first setup or update)
deploy-vikunja host="picklelab":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -n "$(git status --porcelain)" ]; then
        echo "ERROR: uncommitted changes. Commit or stash first."
        exit 1
    fi
    BRANCH=$(git branch --show-current)
    if [ "$BRANCH" != "main" ]; then
        echo "ERROR: not on main (on $BRANCH). Switch to main first."
        exit 1
    fi
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Pushing to origin/main..."
        git push
    fi
    echo "Deploying commit $(git rev-parse --short HEAD) to {{host}}"
    ssh -t {{host}} "cd /opt/homelab && git pull && homelab/services/vikunja/deploy.sh"

# Tail Vikunja container logs from picklelab
vikunja-logs host="picklelab" lines="50":
    ssh {{host}} "cd /opt/homelab/homelab/services/vikunja && docker compose -f compose.yaml -f compose.picklelab.yaml logs --tail={{lines}}"

# Follow Vikunja container logs live from picklelab
vikunja-logs-follow host="picklelab":
    ssh -t {{host}} "cd /opt/homelab/homelab/services/vikunja && docker compose -f compose.yaml -f compose.picklelab.yaml logs -f"

# Validate Vikunja compose config (checks syntax + interpolation using local .env)
vikunja-validate:
    #!/usr/bin/env bash
    set -euo pipefail
    cd homelab/services/vikunja
    docker compose -f compose.yaml -f compose.local.yaml config --quiet
    echo "compose config OK"

# Start Vikunja stack locally (Postgres + Vikunja, no TLS)
vikunja-local-up:
    cd homelab/services/vikunja && \
        docker compose -f compose.yaml -f compose.local.yaml up -d

# Stop and remove local Vikunja stack
vikunja-local-down:
    cd homelab/services/vikunja && \
        docker compose -f compose.yaml -f compose.local.yaml down

# Tailscale VPN overlay: just tailscale [status]
tailscale *ARGS:
    tailscale {{ if ARGS == "" { "status" } else { ARGS } }}

# Show MagicDNS hostname for the current node
tailscale-dns:
    tailscale status --self --json | jq -r '.Self.DNSName | rtrimstr(".")'

# Aladdin garage door: just garage auth | status | open | close
garage *ARGS:
    uv run python garage/garage_cli.py {{ARGS}}
