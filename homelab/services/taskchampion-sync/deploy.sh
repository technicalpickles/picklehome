#!/usr/bin/env bash
# Deploy TaskChampion sync server on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/taskchampion-sync"
DATA_DIR=/srv/data/taskchampion-sync

# Default server port -- override by exporting TASKCHAMPION_SYNC_PORT before running.
# Compose files read this via ${TASKCHAMPION_SYNC_PORT:?...} so it must be exported.
export TASKCHAMPION_SYNC_PORT="${TASKCHAMPION_SYNC_PORT:-9080}"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Writing build metadata"
# Loaded by systemd unit (EnvironmentFile=) so compose's strict
# ${TASKCHAMPION_SYNC_PORT:?...} interpolation succeeds when systemd
# restarts the service with an otherwise-empty user env.
echo "TASKCHAMPION_SYNC_PORT=$TASKCHAMPION_SYNC_PORT" > "$SERVICE_DIR/.env.build"

echo "==> Creating data directory"
sudo mkdir -p "$DATA_DIR"

echo "==> Configuring Tailscale serve for taskchampion"
sudo tailscale serve --service=svc:taskchampion --https=443 "http://127.0.0.1:$TASKCHAMPION_SYNC_PORT"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/taskchampion-sync.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable taskchampion-sync.service
sudo systemctl restart taskchampion-sync.service

echo "==> Status"
systemctl status taskchampion-sync.service --no-pager

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
TC_URL="https://taskchampion.${TAILNET}"

echo ""
echo "==> Checking local health endpoint"
for i in 1 2 3 4 5; do
    if curl -sf "http://127.0.0.1:$TASKCHAMPION_SYNC_PORT/" > /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 5 ]; then
        echo "    WARNING: local health check failed after 5 attempts"
        echo "    Check container logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for server to start (attempt $i/5)..."
    sleep 3
done

echo ""
echo "==> Checking Tailscale endpoint"
if curl -sf "${TC_URL}/" > /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! TaskChampion available at ${TC_URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${TC_URL}"
    echo ""
    echo "    If this is the first deploy, you need to approve the service:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Find 'taskchampion' and approve the pending host"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect approval):"
    echo "       sudo tailscale serve --service=svc:taskchampion --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:taskchampion --https=443 http://127.0.0.1:\$TASKCHAMPION_SYNC_PORT"
    echo "    4. Verify: curl ${TC_URL}/"
fi
