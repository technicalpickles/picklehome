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
# 12 attempts x 5s: first boot runs DB migrations and downloads the default
# embedding model before /health responds.
for i in $(seq 1 12); do
    if curl -fsS "http://127.0.0.1:$PORT/health" -o /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 12 ]; then
        echo "    WARNING: local health check failed after 12 attempts"
        echo "    Logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for Open WebUI to start (attempt $i/12)..."
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
    echo "    If this is the first deploy, the Service likely doesn't exist yet:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Click 'Define Service': Name 'openwebui', Ports '443'"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect a newly-defined service):"
    echo "       sudo tailscale serve --service=svc:openwebui --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:openwebui --https=443 http://127.0.0.1:$PORT"
    echo "    4. Find 'openwebui' at https://login.tailscale.com/admin/services and approve the pending host"
    echo "    5. Verify: curl ${URL}/health"
fi
