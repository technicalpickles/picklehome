#!/usr/bin/env bash
# Deploy the Bugsink error tracker on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

# One deploy at a time on picklelab (no-op when `just` already holds the lock).
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/deploy-lock.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/host-identity.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/wait-for-health.sh"

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/bugsink"
DATA_DIR=/srv/data/bugsink
SERVICE_NAME="bugsink${HOMELAB_SERVICE_SUFFIX?}"

# Override by exporting BUGSINK_PORT before running. The loopback bind and the
# Tailscale Service both read this one value.
export BUGSINK_PORT="${BUGSINK_PORT:-8380}"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
BUGSINK_URL="https://${SERVICE_NAME}.${TAILNET}"

echo "==> Writing build metadata"
# Loaded by the systemd unit (EnvironmentFile=). BASE_URL goes into every DSN and
# derives Django's ALLOWED_HOSTS, so it has to be the name tailscale serves.
{
    echo "BUGSINK_PORT=$BUGSINK_PORT"
    echo "BUGSINK_BASE_URL=$BUGSINK_URL"
} > "$SERVICE_DIR/.env.build"

echo "==> Writing filtered op-run template"
"$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" > "$SERVICE_DIR/.env.op.template"

echo "==> Creating data directories"
# db/ is owned by the postgres image's own entrypoint (it chowns on first start).
sudo mkdir -p "$DATA_DIR/db" "$DATA_DIR/dumps"
# backup.sh's dump_postgres writes here as the backup user.
if id backup &> /dev/null; then
    sudo chown backup:backup "$DATA_DIR/dumps"
fi

echo "==> Configuring Tailscale serve for $SERVICE_NAME"
sudo tailscale serve --service=svc:bugsink${HOMELAB_SERVICE_SUFFIX?} --https=443 "http://127.0.0.1:$BUGSINK_PORT"

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/bugsink.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/bugsink-vacuum.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/bugsink-vacuum.timer" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable bugsink.service
sudo systemctl restart bugsink.service
sudo systemctl enable bugsink-vacuum.timer
sudo systemctl start bugsink-vacuum.timer

echo "==> Status"
systemctl status bugsink.service --no-pager

echo ""
echo "==> Checking local health endpoint"
# First start runs every migration on an empty Postgres, so give it the full budget.
if ! wait_for_health "bugsink" "http://127.0.0.1:$BUGSINK_PORT/health/ready" 180; then
    echo "    Check container logs: docker logs bugsink-web-1"
    exit 1
fi

echo ""
echo "==> Checking Tailscale endpoint"
if curl -sf "${BUGSINK_URL}/health/ready" > /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! Bugsink available at ${BUGSINK_URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${BUGSINK_URL}"
    echo ""
    echo "    If this is the first deploy, you need to approve the service:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Find '${SERVICE_NAME}' and approve the pending host"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect approval):"
    echo "       sudo tailscale serve --service=svc:bugsink${HOMELAB_SERVICE_SUFFIX?} --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:bugsink${HOMELAB_SERVICE_SUFFIX?} --https=443 http://127.0.0.1:\$BUGSINK_PORT"
    echo "    4. Verify: just bugsink-verify"
fi
