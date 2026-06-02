#!/usr/bin/env bash
# Deploy backup service on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/backup"
BACKUP_DIR=/srv/backups/restic
CACHE_DIR=/srv/backups/restic-cache

cd "$REPO_DIR"

BACKUP_USER="backup"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Installing dependencies"
NEEDED=()
command -v restic  &> /dev/null || NEEDED+=(restic)
command -v setfacl &> /dev/null || NEEDED+=(acl)
if [ "${#NEEDED[@]}" -gt 0 ]; then
    sudo apt-get update
    sudo apt-get install -y "${NEEDED[@]}"
fi

echo "==> Creating backup user"
if ! id "$BACKUP_USER" &> /dev/null; then
    sudo useradd --system --shell /usr/sbin/nologin "$BACKUP_USER"
fi
# Docker group gives access to `docker exec` for pg_dump
if ! id -nG "$BACKUP_USER" | grep -qw docker; then
    sudo usermod -aG docker "$BACKUP_USER"
fi

echo "==> Creating directories"
sudo mkdir -p "$BACKUP_DIR" "$CACHE_DIR"
sudo chown "$BACKUP_USER:$BACKUP_USER" "$BACKUP_DIR" "$CACHE_DIR"
# Pre-create dump directories so backup user can write to them.
# No Postgres services currently deployed. When one returns, add it here:
#   for svc in <service>; do
#       sudo mkdir -p "/srv/data/$svc/dumps"
#       sudo chown "$BACKUP_USER:$BACKUP_USER" "/srv/data/$svc/dumps"
#   done

echo "==> Granting backup user read ACLs on service data"
# Ecobee tokens are seeded by the human user with mode 600
sudo setfacl -m u:"$BACKUP_USER":r /srv/data/climate-auto-switch/ecobee-tokens.json

echo "==> Initializing restic repo (if needed)"
# Source the env file for RESTIC_REPOSITORY and RESTIC_PASSWORD.
set -a
source "$SERVICE_DIR/.env"
set +a
if ! sudo -u "$BACKUP_USER" -E restic snapshots &> /dev/null; then
    echo "    Initializing new restic repository at $RESTIC_REPOSITORY"
    sudo -u "$BACKUP_USER" -E restic init
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
