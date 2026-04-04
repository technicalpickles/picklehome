#!/usr/bin/env bash
# Deploy Baserow on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/baserow"
DATA_DIR=/srv/data/baserow

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Creating data directories"
sudo mkdir -p "$DATA_DIR/db" "$DATA_DIR/data"
# Baserow container runs as UID 9999 — data dir must be writable by it
sudo chown 9999:9999 "$DATA_DIR/data"

echo "==> Configuring Tailscale serve for baserow"
# Registers baserow.<tailnet>.ts.net → https, proxied to localhost:8080.
# Idempotent: re-running updates the config in tailscaled's state.
# Requires HTTPS to be enabled in the Tailscale admin console.
sudo tailscale serve --service=svc:baserow --https=443 http://127.0.0.1:8080

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/baserow.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable baserow.service
sudo systemctl restart baserow.service

echo "==> Status"
systemctl status baserow.service --no-pager

echo ""
echo "Done! Baserow available at https://baserow.$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')"
