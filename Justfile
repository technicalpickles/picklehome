set dotenv-load
set positional-arguments

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
    echo "==> Copying .env to {{host}}"
    mkdir -p tmp
    scripts/service-env homelab/services/climate-auto-switch/.env.vars > tmp/climate-auto-switch.env
    scp tmp/climate-auto-switch.env {{host}}:/opt/homelab/homelab/services/climate-auto-switch/.env
    rm tmp/climate-auto-switch.env
    ssh {{host}} "cd /opt/homelab && git pull && homelab/services/climate-auto-switch/deploy.sh"

# Seed ecobee token file to picklelab (one-time, from Mac)
seed-climate-tokens host="picklelab":
    ssh {{host}} "sudo mkdir -p /srv/data/climate-auto-switch"
    scp ~/.local/state/picklehome/ecobee-tokens.json {{host}}:/tmp/ecobee-tokens.json
    ssh {{host}} "sudo mv /tmp/ecobee-tokens.json /srv/data/climate-auto-switch/ && sudo chmod 600 /srv/data/climate-auto-switch/ecobee-tokens.json"

# Show last climate auto-switch state (from picklelab)
climate-check host="picklelab":
    ssh {{host}} "cat /srv/data/climate-auto-switch/last-state.json | python3 -m json.tool"

# Show recent climate auto-switch run log (from picklelab)
climate-log host="picklelab" lines="10":
    ssh {{host}} "tail -n {{lines}} /srv/data/climate-auto-switch/run-log.jsonl | python3 -m json.tool --json-lines"

# Deploy github-actions-runner to picklelab
deploy-github-runner host="picklelab":
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
    echo "==> Copying .env to {{host}}"
    mkdir -p tmp
    scripts/service-env homelab/services/github-actions-runner/.env.vars > tmp/github-actions-runner.env
    scp tmp/github-actions-runner.env {{host}}:/opt/homelab/homelab/services/github-actions-runner/.env
    rm tmp/github-actions-runner.env
    ssh {{host}} "cd /opt/homelab && git pull && homelab/services/github-actions-runner/deploy.sh"

# Tail github-actions-runner container logs from picklelab
github-runner-logs host="picklelab":
    ssh {{host}} "docker logs --tail 100 -f \$(docker ps -q --filter name=github-actions-runner)"

# Show github-actions-runner systemd status and container info from picklelab
github-runner-status host="picklelab":
    ssh {{host}} "systemctl status github-actions-runner.service --no-pager && docker ps --filter name=github-actions-runner"

# Deploy TaskChampion sync server to picklelab (idempotent: first setup or update)
deploy-taskchampion host="picklelab":
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
    echo "==> Pulling on {{host}}"
    ssh {{host}} "cd /opt/homelab && git pull"
    echo "==> Copying .env to {{host}}"
    mkdir -p tmp
    scripts/service-env homelab/services/taskchampion-sync/.env.vars > tmp/taskchampion-sync.env
    scp tmp/taskchampion-sync.env {{host}}:/opt/homelab/homelab/services/taskchampion-sync/.env
    rm tmp/taskchampion-sync.env
    ssh {{host}} "cd /opt/homelab && homelab/services/taskchampion-sync/deploy.sh"

# Status check for TaskChampion sync (systemd + loopback HTTP + tailscale routing)
taskchampion-status host="picklelab":
    #!/usr/bin/env bash
    set -uo pipefail
    echo "==> systemd unit on {{host}}"
    ssh {{host}} "sudo systemctl status taskchampion-sync.service --no-pager" || true
    echo ""
    echo "==> loopback HTTP on {{host}}"
    ssh {{host}} "curl -fsS http://127.0.0.1:9080/ -w '\nHTTP %{http_code}  %{time_total}s\n'" || echo "loopback FAILED"
    echo ""
    echo "==> tailscale routing (from this machine)"
    if [ -z "${TASKCHAMPION_SYNC_SERVER_URL:-}" ]; then
        echo "TASKCHAMPION_SYNC_SERVER_URL not set in shell env (fnox not loaded?)"
    else
        curl -fsS "$TASKCHAMPION_SYNC_SERVER_URL" -w "\nHTTP %{http_code}  %{time_total}s\n" || echo "tailscale routing FAILED"
    fi

# Tail TaskChampion container logs from picklelab
taskchampion-logs host="picklelab" lines="50":
    ssh {{host}} "cd /opt/homelab/homelab/services/taskchampion-sync && docker compose -f compose.yaml -f compose.picklelab.yaml logs --tail={{lines}}"

# Follow TaskChampion container logs live from picklelab
taskchampion-logs-follow host="picklelab":
    ssh -t {{host}} "cd /opt/homelab/homelab/services/taskchampion-sync && docker compose -f compose.yaml -f compose.picklelab.yaml logs -f"

# Deploy Brineworks PRM server to picklelab (idempotent: first setup or update)
deploy-brineworks-server host="picklelab":
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
    echo "==> Pulling on {{host}}"
    ssh {{host}} "cd /opt/homelab && git pull"
    echo "==> Copying .env to {{host}}"
    mkdir -p tmp
    scripts/service-env homelab/services/brineworks-server/.env.vars > tmp/brineworks-server.env
    scp tmp/brineworks-server.env {{host}}:/opt/homelab/homelab/services/brineworks-server/.env
    rm tmp/brineworks-server.env
    ssh {{host}} "cd /opt/homelab && homelab/services/brineworks-server/deploy.sh"

# Tail Brineworks server container logs from picklelab
brineworks-server-logs host="picklelab" lines="50":
    ssh {{host}} "cd /opt/homelab/homelab/services/brineworks-server && docker compose -f compose.yaml -f compose.picklelab.yaml logs --tail={{lines}}"

# Follow Brineworks server container logs live from picklelab
brineworks-server-logs-follow host="picklelab":
    ssh -t {{host}} "cd /opt/homelab/homelab/services/brineworks-server && docker compose -f compose.yaml -f compose.picklelab.yaml logs -f"

# Tailscale VPN overlay: just tailscale [status]
tailscale *ARGS:
    tailscale {{ if ARGS == "" { "status" } else { ARGS } }}

# Show MagicDNS hostname for the current node
tailscale-dns:
    tailscale status --self --json | jq -r '.Self.DNSName | rtrimstr(".")'

# Aladdin garage door: just garage auth | status | open | close
garage *ARGS:
    uv run python garage/garage_cli.py {{ARGS}}

# Yale Access locks: just locks auth | status
locks *ARGS:
    uv run python locks/locks_cli.py {{ARGS}}

# Sonos speakers: just sonos status | roster | list
sonos *ARGS:
    uv run python sonos/sonos_cli.py {{ARGS}}

# Deploy backup service to picklelab (idempotent: first setup or update)
deploy-backup host="picklelab":
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
    echo "==> Copying .env to {{host}}"
    mkdir -p tmp
    scripts/service-env homelab/services/backup/.env.vars > tmp/backup.env
    scp tmp/backup.env {{host}}:/opt/homelab/homelab/services/backup/.env
    rm tmp/backup.env
    ssh {{host}} "cd /opt/homelab && git pull && homelab/services/backup/deploy.sh"

# Run backup now on picklelab (manual trigger)
backup-now host="picklelab":
    ssh {{host}} "sudo systemctl start backup.service"

# Show recent restic snapshots from picklelab
backup-snapshots host="picklelab":
    ssh {{host}} "set -a && source /opt/homelab/homelab/services/backup/.env && restic snapshots --tag nightly"

# Show backup timer status on picklelab
backup-status host="picklelab":
    ssh {{host}} "systemctl status backup.timer --no-pager && echo '' && systemctl list-timers backup.timer --no-pager"

# Show backup service logs (last run output)
backup-logs host="picklelab" lines="50":
    ssh {{host}} "journalctl -u backup.service --no-pager -n {{lines}}"

# Deploy Obsidian Sync to picklelab (idempotent: first setup or update)
deploy-obsidian-sync host="picklelab":
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
    ssh {{host}} "cd /opt/homelab && git pull && homelab/services/obsidian-sync/deploy.sh"

# Run ob CLI against a specific vault's container (e.g. "rpg sync-status")
obsidian-sync-exec vault host="picklelab" *ARGS:
    ssh -t {{host}} "docker exec -it obsidian-sync-{{vault}}-1 ob {{ARGS}}"

# Tail Obsidian Sync container logs from picklelab
obsidian-sync-logs host="picklelab" lines="50":
    ssh {{host}} "cd /opt/homelab/homelab/services/obsidian-sync && docker compose -f compose.yaml -f compose.picklelab.yaml logs --tail={{lines}}"

# Follow Obsidian Sync container logs live from picklelab
obsidian-sync-logs-follow host="picklelab":
    ssh -t {{host}} "cd /opt/homelab/homelab/services/obsidian-sync && docker compose -f compose.yaml -f compose.picklelab.yaml logs -f"

# Show Obsidian Sync service status on picklelab
obsidian-sync-status host="picklelab":
    ssh {{host}} "systemctl status obsidian-sync.service --no-pager"
