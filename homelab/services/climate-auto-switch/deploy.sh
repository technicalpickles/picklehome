#!/usr/bin/env bash
# Deploy climate-auto-switch on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

# One deploy at a time on picklelab (no-op when `just` already holds the lock).
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/deploy-lock.sh"

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/climate-auto-switch"
DATA_DIR=/srv/data/climate-auto-switch

cd "$REPO_DIR"

echo "==> Writing filtered op-run template"
"$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" > "$SERVICE_DIR/.env.op.template"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Creating data directory"
sudo mkdir -p "$DATA_DIR"

echo "==> Pulling the published image"
# Private package, so the pull runs as root (credential helper, see
# setup-ghcr-pull-auth.sh) through compose-pull@, which retries until CI has pushed
# this commit's image. The timer is paused (below) but the pull still has to work.
echo "IMAGE_SHA=$(git rev-parse HEAD)" > "$SERVICE_DIR/.env.image"
sudo ln -sf "$REPO_DIR/homelab/config/compose-pull@.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start compose-pull@climate-auto-switch.service

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/climate-auto-switch.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/climate-auto-switch.timer" /etc/systemd/system/

echo "==> Reloading systemd"
sudo systemctl daemon-reload
# PAUSED 2026-10-18 (see docs/adr/0001-pause-climate-auto-switch-timer.md): the timer is
# stopped by hand while comfort is tuned manually, so a deploy must not enable or restart
# it. Flip back to 0 (or delete the guard) to resume normal deploys.
TIMER_PAUSED=1
if [[ "$TIMER_PAUSED" == "1" ]]; then
  echo "==> Timer paused: skipping enable/restart of climate-auto-switch.timer"
else
  echo "==> Enabling and restarting timer"
  sudo systemctl enable climate-auto-switch.timer
  sudo systemctl restart climate-auto-switch.timer
fi

echo "==> Status"
systemctl status climate-auto-switch.timer --no-pager

echo ""
echo "Done! Next run:"
systemctl list-timers climate-auto-switch.timer --no-pager
