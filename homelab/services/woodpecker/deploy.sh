#!/usr/bin/env bash
# Deploy Woodpecker CI on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/woodpecker"
DATA_DIR=/srv/data/woodpecker

cd "$REPO_DIR"
echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Checking rootless docker socket for the ci user"
# /run/user/2000 is the ci user's XDG_RUNTIME_DIR (mode 0700, owned by ci), so the
# deploy user (technicalpickles) can't stat the socket directly. Probe from a root
# vantage via a narrow sudoers entry (/usr/bin/test -S /run/user/2000/docker.sock).
# This only gates pre-flight; at runtime the agent reaches the socket fine because
# the rootful daemon performs the bind-mount as root (root ignores the 0700 bits).
if ! sudo test -S /run/user/2000/docker.sock; then
    echo "ERROR: /run/user/2000/docker.sock missing. Is the ci user's rootless dockerd running?"
    echo "       sudo -iu ci env XDG_RUNTIME_DIR=/run/user/2000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/2000/bus systemctl --user status docker"
    exit 1
fi

echo "==> Creating data directories"
sudo mkdir -p "$DATA_DIR/ts-state" "$DATA_DIR/server"
# woodpecker-server and the tailscale sidecar run as root in-container; root-owned dirs are writable.

echo "==> Pulling images"
cd "$SERVICE_DIR"
docker compose -f compose.yaml -f compose.picklelab.yaml pull

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/woodpecker.service" /etc/systemd/system/

echo "==> Reloading systemd and (re)starting service"
sudo systemctl daemon-reload
sudo systemctl enable woodpecker.service
sudo systemctl restart woodpecker.service

echo "==> Status"
systemctl status woodpecker.service --no-pager

echo ""
echo "==> Checking local Woodpecker health endpoint"
for i in 1 2 3 4 5; do
    if curl -sf "http://127.0.0.1:8000/healthz" > /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 5 ]; then
        echo "    WARNING: local health check failed after 5 attempts"
        echo "    Logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for server to start (attempt $i/5)..."
    sleep 3
done

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
echo ""
echo "Done! Woodpecker should be reachable at https://woodpecker.${TAILNET}"
echo "If the funnel hostname does not resolve yet, check: docker compose exec ts-woodpecker tailscale funnel status"
