#!/usr/bin/env bash
# Deploy climate-auto-switch on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/climate-auto-switch"
DATA_DIR=/srv/data/climate-auto-switch

cd "$REPO_DIR"

echo "==> Creating data directory"
sudo mkdir -p "$DATA_DIR"

echo "==> Building image"
cd "$SERVICE_DIR"
docker compose -f compose.yaml -f compose.picklelab.yaml build

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/climate-auto-switch.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/climate-auto-switch.timer" /etc/systemd/system/

echo "==> Reloading systemd and restarting timer"
sudo systemctl daemon-reload
sudo systemctl reenable --now climate-auto-switch.timer
sudo systemctl restart climate-auto-switch.timer

echo "==> Status"
systemctl status climate-auto-switch.timer --no-pager

echo ""
echo "Done! Next run:"
systemctl list-timers climate-auto-switch.timer --no-pager
