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

echo ""
echo "Done! Brineworks available at https://brineworks.$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')"
