#!/usr/bin/env bash
# Deploy the notify service on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

# One deploy at a time on picklelab (no-op when `just` already holds the lock).
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/deploy-lock.sh"

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/notify"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Writing filtered op-run template"
"$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" > "$SERVICE_DIR/.env.op.template"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/notify-failure@.service" /etc/systemd/system/

echo "==> Reloading systemd"
sudo systemctl daemon-reload

echo ""
echo "Done! Units opt in with OnFailure=notify-failure@%n.service"
