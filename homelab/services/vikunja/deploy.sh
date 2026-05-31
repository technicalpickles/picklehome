#!/usr/bin/env bash
# Deploy Vikunja on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/vikunja"
DATA_DIR=/srv/data/vikunja

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Creating data directories"
sudo mkdir -p "$DATA_DIR/db" "$DATA_DIR/files"
# Vikunja container runs as UID 1000: files dir must be writable by it
sudo chown 1000:1000 "$DATA_DIR/files"

echo "==> Configuring Tailscale serve for vikunja"
# Registers vikunja.<tailnet>.ts.net → https, proxied to localhost:3456.
# Idempotent: re-running updates the config in tailscaled's state.
# Requires HTTPS to be enabled in the Tailscale admin console.
sudo tailscale serve --service=svc:vikunja --https=443 http://127.0.0.1:3456

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/vikunja.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable vikunja.service
sudo systemctl restart vikunja.service

echo "==> Status"
systemctl status vikunja.service --no-pager

echo ""
echo "Done! Vikunja available at https://vikunja.$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')"
