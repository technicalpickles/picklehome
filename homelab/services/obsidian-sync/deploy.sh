#!/usr/bin/env bash
# Deploy Obsidian Sync on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

# One deploy at a time on picklelab (no-op when `just` already holds the lock).
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/deploy-lock.sh"

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

echo "==> Fixing ownership: all vaults and configs → uid 1000"
sudo chown -R 1000:1000 \
    "$DATA_DIR/config/rpg" \
    "$DATA_DIR/config/pickled-knowledge" \
    "$DATA_DIR/vaults/rpg" \
    "$DATA_DIR/vaults/pickled-knowledge"

echo "==> Pulling the published image"
# The package is private, so the pull has to run as root (credential helper, see
# setup-ghcr-pull-auth.sh). compose-pull@ does it, retrying until CI has pushed
# this commit's image, and runs before the restart so the old container stays up.
IMAGE_SHA=$(git rev-parse HEAD)
echo "IMAGE_SHA=$IMAGE_SHA" > "$SERVICE_DIR/.env.image"
sudo ln -sf "$REPO_DIR/homelab/config/compose-pull@.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start compose-pull@obsidian-sync.service

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
