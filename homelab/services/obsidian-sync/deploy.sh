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
sudo mkdir -p \
    "$DATA_DIR/config/rpg" \
    "$DATA_DIR/config/pickled-knowledge" \
    "$DATA_DIR/vaults/rpg" \
    "$DATA_DIR/vaults/pickled-knowledge"

echo "==> Building image"
cd "$SERVICE_DIR"
docker compose -f compose.yaml -f compose.picklelab.yaml build

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
echo "To run ob commands against a specific vault (e.g. for sync-status):"
echo "  just obsidian-sync-exec rpg sync-status"
echo "  just obsidian-sync-exec pickled-knowledge sync-status"
