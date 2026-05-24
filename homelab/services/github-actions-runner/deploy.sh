#!/usr/bin/env bash
# Deploy github-actions-runner on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/github-actions-runner"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Pulling runner image"
cd "$SERVICE_DIR"
docker compose -f compose.yaml -f compose.picklelab.yaml pull

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/github-actions-runner.service" /etc/systemd/system/

echo "==> Reloading systemd and (re)starting service"
sudo systemctl daemon-reload
sudo systemctl enable github-actions-runner.service
sudo systemctl restart github-actions-runner.service

echo "==> Status"
systemctl status github-actions-runner.service --no-pager
