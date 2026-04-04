#!/usr/bin/env bash
# Deploy backup service on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/backup"
BACKUP_DIR=/srv/backups/restic

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Installing restic"
if ! command -v restic &> /dev/null; then
    sudo apt-get update && sudo apt-get install -y restic
fi

echo "==> Creating backup directory"
sudo mkdir -p "$BACKUP_DIR"

echo "==> Initializing restic repo (if needed)"
# Source the env file for RESTIC_REPOSITORY and RESTIC_PASSWORD.
# Run restic as root since the backup service runs as root (system unit).
set -a
source "$SERVICE_DIR/.env"
set +a
if ! sudo -E restic snapshots &> /dev/null; then
    echo "    Initializing new restic repository at $RESTIC_REPOSITORY"
    sudo -E restic init
else
    echo "    Restic repository already initialized"
fi

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/backup.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/backup.timer" /etc/systemd/system/

echo "==> Reloading systemd and enabling timer"
sudo systemctl daemon-reload
sudo systemctl enable backup.timer
sudo systemctl restart backup.timer

echo "==> Status"
systemctl status backup.timer --no-pager

echo ""
echo "Done! Next run:"
systemctl list-timers backup.timer --no-pager
