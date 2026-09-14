#!/usr/bin/env bash
# Deploy climate-auto-switch on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/climate-auto-switch"
DATA_DIR=/srv/data/climate-auto-switch

cd "$REPO_DIR"

echo "==> Writing filtered op-run template"
"$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" > "$SERVICE_DIR/.env.op.template"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Creating data directory"
sudo mkdir -p "$DATA_DIR"

echo "==> Building image"
cd "$SERVICE_DIR"
# compose.yaml's environment: entries use ${VAR:?required}, so compose refuses to even
# parse the file unless every var is set in the process environment - regardless of
# whether the command being run (build) actually consumes them. The Dockerfile has no
# ARGs and never reads these at build time; only the systemd unit's `op run`-wrapped
# ExecStart needs the real values. Placeholder values here just satisfy compose's
# interpolation check so the build step (unwrapped, unprivileged) can run standalone.
HOME_LAT=build-placeholder \
HOME_LON=build-placeholder \
AMBIENT_STATION_MACS=build-placeholder \
ECOBEE_API_KEY=build-placeholder \
BLUEAIR_USERNAME=build-placeholder \
BLUEAIR_PASSWORD=build-placeholder \
BLUEAIR_REGION=build-placeholder \
GOOGLE_POLLEN_API_KEY=build-placeholder \
  docker compose -f compose.yaml -f compose.picklelab.yaml build

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/climate-auto-switch.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/climate-auto-switch.timer" /etc/systemd/system/

echo "==> Reloading systemd and restarting timer"
sudo systemctl daemon-reload
sudo systemctl enable climate-auto-switch.timer
sudo systemctl restart climate-auto-switch.timer

echo "==> Status"
systemctl status climate-auto-switch.timer --no-pager

echo ""
echo "Done! Next run:"
systemctl list-timers climate-auto-switch.timer --no-pager
