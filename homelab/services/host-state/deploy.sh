#!/usr/bin/env bash
# Deploy the host-state collector timer on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

# One deploy at a time on picklelab (no-op when `just` already holds the lock).
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/deploy-lock.sh"

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/host-state"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/host-state.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/host-state.timer" /etc/systemd/system/

echo "==> Reloading systemd and enabling timer"
sudo systemctl daemon-reload
sudo systemctl enable host-state.timer
sudo systemctl restart host-state.timer

# The timer's first run is 60s after boot or restart; write a report now.
echo "==> Writing the first report"
sudo systemctl start host-state.service

echo ""
echo "Done! Next run:"
systemctl list-timers host-state.timer --no-pager
