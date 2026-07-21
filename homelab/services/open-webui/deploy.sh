#!/usr/bin/env bash
# Deploy Open WebUI on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/open-webui"
DATA_DIR=/srv/data/open-webui
# Loopback port tailscaled proxies to; the container listens on 8080 internally.
PORT=8090
# See homelab/services/README.md "Container user model".
CONTAINER_UID=1000
CONTAINER_GID=1000

cd "$REPO_DIR"
echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Creating data directory"
sudo mkdir -p "$DATA_DIR"
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$DATA_DIR"

echo "==> Configuring Tailscale serve for openwebui"
sudo tailscale serve --service=svc:openwebui --https=443 "http://127.0.0.1:$PORT"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/open-webui.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable open-webui.service
sudo systemctl restart open-webui.service

echo "==> Status"
systemctl status open-webui.service --no-pager || true

echo ""
echo "==> Checking local health endpoint"
# 20 attempts x 5s = 100s: first boot runs DB migrations and downloads the
# default embedding model from HuggingFace before /health responds. Observed
# ~70s end-to-end on the first real deploy (2026-07-21) -- the original 12x5s
# (60s) budget cut it off ~9s early even though the container came up fine
# moments later. Cached on later restarts, so this budget is first-boot-only
# headroom, not the steady-state cost.
for i in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:$PORT/health" -o /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 20 ]; then
        echo "    WARNING: local health check failed after 20 attempts"
        echo "    Logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for Open WebUI to start (attempt $i/20)..."
    sleep 5
done

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
URL="https://openwebui.${TAILNET}"

echo ""
echo "==> Checking Tailscale endpoint"
if curl -fsS "${URL}/health" -o /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! Open WebUI is reachable at ${URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${URL}"
    echo ""
    echo "    If this is the first deploy, this is expected -- every new Service on"
    echo "    picklelab has needed this exact sequence (see the tailscale-cli skill,"
    echo "    'Setting up a brand-new Service'):"
    echo "    1. Define the Service (if not already): https://login.tailscale.com/admin/services"
    echo "       -> 'Define Service' -> Name 'openwebui', Ports '443'"
    echo "    2. This script already ran: sudo tailscale serve --service=svc:openwebui --https=443 http://127.0.0.1:$PORT"
    echo "    3. Restart tailscaled to actually advertise the pending host -- a serve"
    echo "       off/on toggle is NOT a substitute for this:"
    echo "       sudo systemctl restart tailscaled"
    echo "    4. Approve the pending host: https://login.tailscale.com/admin/services"
    echo "    5. Verify: curl ${URL}/health"
fi
