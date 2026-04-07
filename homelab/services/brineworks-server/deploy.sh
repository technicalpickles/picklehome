#!/usr/bin/env bash
# Deploy Brineworks PRM server on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/brineworks-server"
DATA_DIR=/srv/data/brineworks-server
BRINEWORKS_REPO=/opt/brineworks

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Updating brineworks source"
if [ -d "$BRINEWORKS_REPO/.git" ]; then
    git -C "$BRINEWORKS_REPO" pull --ff-only
else
    echo "    Cloning brineworks to $BRINEWORKS_REPO"
    sudo mkdir -p "$BRINEWORKS_REPO"
    sudo chown "$(id -u):$(id -g)" "$BRINEWORKS_REPO"
    git clone git@github.com:technicalpickles/brineworks.git "$BRINEWORKS_REPO"
fi
echo "    Brineworks at $(git -C "$BRINEWORKS_REPO" rev-parse --short HEAD)"

echo "==> Creating data directories"
sudo mkdir -p "$DATA_DIR/db"

echo "==> Configuring Tailscale serve for brineworks"
# Registers brineworks.<tailnet>.ts.net, proxied to localhost:8000.
# Idempotent: re-running updates the config in tailscaled's state.
# Requires HTTPS to be enabled in the Tailscale admin console.
sudo tailscale serve --service=svc:brineworks --https=443 http://127.0.0.1:8000

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/brineworks-server.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable brineworks-server.service
sudo systemctl restart brineworks-server.service

echo "==> Status"
systemctl status brineworks-server.service --no-pager

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
BRINEWORKS_URL="https://brineworks.${TAILNET}"

echo ""
echo "==> Checking local health endpoint"
# Verify the app is responding locally before checking Tailscale
for i in 1 2 3 4 5; do
    if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
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
if curl -sf "${BRINEWORKS_URL}/health" > /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! Brineworks available at ${BRINEWORKS_URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${BRINEWORKS_URL}"
    echo ""
    echo "    If this is the first deploy, you need to approve the service:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Find 'brineworks' and approve the pending host"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect approval):"
    echo "       sudo tailscale serve --service=svc:brineworks --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:brineworks --https=443 http://127.0.0.1:8000"
    echo "    4. Verify: curl ${BRINEWORKS_URL}/health"
fi
