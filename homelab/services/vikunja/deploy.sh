#!/usr/bin/env bash
# Deploy Vikunja on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/vikunja"
DATA_DIR=/srv/data/vikunja
CERT_DIR=/srv/certs

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

# Load VIKUNJA_HOST from .env (needed for tailscale cert provisioning)
set -a
# shellcheck source=/dev/null
source "$REPO_DIR/.env"
set +a

if [ -z "${VIKUNJA_HOST:-}" ]; then
    echo "ERROR: VIKUNJA_HOST is not set in .env"
    echo "  Set it to your Tailscale MagicDNS hostname, e.g. picklelab.your-tailnet.ts.net"
    exit 1
fi

echo "==> Creating data directories"
sudo mkdir -p "$DATA_DIR/db" "$DATA_DIR/files" "$DATA_DIR/caddy" "$DATA_DIR/caddy-config" "$CERT_DIR"
# Vikunja container runs as UID 1000 — files dir must be writable by it
sudo chown 1000:1000 "$DATA_DIR/files"

echo "==> Provisioning Tailscale HTTPS cert for $VIKUNJA_HOST"
sudo tailscale cert \
    --cert-file="$CERT_DIR/$VIKUNJA_HOST.crt" \
    --key-file="$CERT_DIR/$VIKUNJA_HOST.key" \
    "$VIKUNJA_HOST"
# Caddy runs as root in the container and needs to read the key
sudo chmod 644 "$CERT_DIR/$VIKUNJA_HOST.crt"
sudo chmod 600 "$CERT_DIR/$VIKUNJA_HOST.key"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/vikunja.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable vikunja.service
sudo systemctl restart vikunja.service

echo "==> Status"
systemctl status vikunja.service --no-pager

echo ""
echo "Done! Vikunja available at https://$VIKUNJA_HOST"
