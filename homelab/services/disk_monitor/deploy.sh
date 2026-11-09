#!/usr/bin/env bash
# Deploy the disk monitor timer on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

# One deploy at a time on picklelab (no-op when `just` already holds the lock).
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/deploy-lock.sh"

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/disk_monitor"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

if [ ! -f "$REPO_DIR/homelab/services/notify/.env.op.template" ]; then
    echo "ERROR: $REPO_DIR/homelab/services/notify/.env.op.template is missing." >&2
    echo "Run 'just deploy-notify' first, then deploy the disk monitor again." >&2
    exit 1
fi

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/disk-monitor.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/disk-monitor.timer" /etc/systemd/system/

echo "==> Reloading systemd and enabling timer"
sudo systemctl daemon-reload
sudo systemctl enable disk-monitor.timer
sudo systemctl restart disk-monitor.timer

echo "==> Status"
systemctl status disk-monitor.timer --no-pager

echo ""
echo "Done! Next run:"
systemctl list-timers disk-monitor.timer --no-pager
