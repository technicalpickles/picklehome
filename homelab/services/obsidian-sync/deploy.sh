#!/usr/bin/env bash
# Deploy Obsidian Sync on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/obsidian-sync"
DATA_DIR=/srv/data/obsidian-sync

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Creating data directories"
sudo mkdir -p "$DATA_DIR/config" "$DATA_DIR/vaults/rpg"

echo "==> Building image"
cd "$SERVICE_DIR"
docker compose -f compose.yaml -f compose.picklelab.yaml build cli

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/obsidian-sync.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable obsidian-sync.service
sudo systemctl restart obsidian-sync.service

echo "==> Status"
systemctl status obsidian-sync.service --no-pager

echo ""
echo "Done!"
echo ""
echo "If this is first setup, authenticate and link vaults from your laptop:"
echo "  just obsidian-sync-exec login"
echo "  just obsidian-sync-exec sync-setup"
echo "Then restart the service:"
echo "  just deploy-obsidian-sync"
