#!/usr/bin/env bash
# Deploy Brineworks PRM server on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

# One deploy at a time on picklelab (no-op when `just` already holds the lock).
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/deploy-lock.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/host-identity.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/wait-for-health.sh"

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/brineworks-server"
# Dev hosts swap a few secrets via an overlay (see scripts/service-env); on
# picklelab HOMELAB_ENV_OVERLAY is empty and this stays an empty array.
OVERLAY_ARGS=()
if [ -n "${HOMELAB_ENV_OVERLAY?}" ]; then
    OVERLAY_ARGS=(--overlay "$REPO_DIR/homelab/hosts/overlays/${HOMELAB_ENV_OVERLAY}.env.template")
fi
DATA_DIR=/srv/data/brineworks-server
BRINEWORKS_REPO=/opt/brineworks

# Default server port -- override by exporting BRINEWORKS_SERVER_PORT before running.
# Must match the port configured in the brineworks repo (see brineworks_cli/config.py
# and server/brineworks_server/config.py). Compose files also read this env var.
export BRINEWORKS_SERVER_PORT="${BRINEWORKS_SERVER_PORT:-8765}"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Checking Gmail keyring"
# check-keyring.sh runs as root via a pinned NOPASSWD grant (sudoers-deploy-ops): the
# keyring dir is root-owned mode 700, so a plain [ -f ] from this user would report an
# existing file as missing. -n so a missing grant fails fast instead of hanging on a
# password prompt over plain ssh. The wrapper exits 3 for "missing"; any other nonzero
# means sudo never ran it, which is NOT the same as the file being absent.
set +e
sudo -n "$SERVICE_DIR/check-keyring.sh"
keyring_rc=$?
set -e
case "$keyring_rc" in
    0) ;;
    3)
        echo "ERROR: $DATA_DIR/keyring/cryptfile.cfg is missing." >&2
        echo "    brineworks-server refuses to start in production without Gmail credentials," >&2
        echo "    and a restart without them takes PRM, tasks and /health down with it." >&2
        echo "    From the Mac, run: just seed-brineworks-gmail" >&2
        exit 1
        ;;
    *)
        echo "ERROR: could not check the keyring (sudo exited $keyring_rc), which is not the same as it being missing." >&2
        echo "    Most likely the sudoers grant for check-keyring.sh isn't installed yet." >&2
        echo "    On picklelab, run once (needs your password): $REPO_DIR/homelab/scripts/setup-deploy-access.sh" >&2
        exit 1
        ;;
esac

echo "==> Updating brineworks source"
if [ -d "$BRINEWORKS_REPO/.git" ]; then
    git -C "$BRINEWORKS_REPO" pull --ff-only
else
    echo "    Cloning brineworks to $BRINEWORKS_REPO"
    sudo mkdir -p "$BRINEWORKS_REPO"
    sudo chown "$(id -u):$(id -g)" "$BRINEWORKS_REPO"
    git clone git@github.com:technicalpickles/brineworks.git "$BRINEWORKS_REPO"
fi
BRINEWORKS_SHA=$(git -C "$BRINEWORKS_REPO" rev-parse --short HEAD)
echo "    Brineworks at $BRINEWORKS_SHA"

echo "==> Writing build metadata"
# .env.build is loaded by both the systemd unit (EnvironmentFile=) and the
# container (compose env_file:). The unit path is what makes compose's strict
# ${BRINEWORKS_SERVER_PORT:?...} interpolation succeed when systemd restarts
# the service with an otherwise-empty user env.
{
    echo "BRINEWORKS_GIT_SHA=$BRINEWORKS_SHA"
    echo "BRINEWORKS_SERVER_PORT=$BRINEWORKS_SERVER_PORT"
} > "$SERVICE_DIR/.env.build"

echo "==> Writing filtered op-run template"
"$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" ${OVERLAY_ARGS[@]+"${OVERLAY_ARGS[@]}"} > "$SERVICE_DIR/.env.op.template"

echo "==> Creating data directories"
sudo mkdir -p "$DATA_DIR/db"

echo "==> Configuring Tailscale serve for brineworks"
# Registers brineworks.<tailnet>.ts.net, proxied to localhost:$BRINEWORKS_SERVER_PORT.
# Idempotent: re-running updates the config in tailscaled's state.
# Requires HTTPS to be enabled in the Tailscale admin console.
sudo tailscale serve --service=svc:brineworks${HOMELAB_SERVICE_SUFFIX?} --https=443 "http://127.0.0.1:$BRINEWORKS_SERVER_PORT"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/brineworks-server.service" /etc/systemd/system/

echo "==> Linking liveness watchdog (timer + service)"
sudo ln -sf "$SERVICE_DIR/brineworks-server-watch.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/brineworks-server-watch.timer" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable brineworks-server.service
sudo systemctl restart brineworks-server.service
sudo systemctl enable brineworks-server-watch.timer
sudo systemctl start brineworks-server-watch.timer

echo "==> Status"
systemctl status brineworks-server.service --no-pager

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
BRINEWORKS_URL="https://brineworks${HOMELAB_SERVICE_SUFFIX?}.${TAILNET}"

echo ""
echo "==> Checking local health endpoint"
# Verify the app is responding locally before checking Tailscale.
# 120s budget: the container took ~26-37s to report healthy after the 2026-09-27
# deploy and gave up at the old 5x3s (~15s) even though it came up fine moments later.
if ! wait_for_health "brineworks-server" "http://127.0.0.1:$BRINEWORKS_SERVER_PORT/health" 120; then
    echo "    Check container logs: op run --env-file=.env.op.template -- docker compose --project-directory $SERVICE_DIR --env-file .env.build -f /opt/brineworks/server/compose.yaml -f compose.picklelab.yaml logs"
    exit 1
fi

echo ""
echo "==> Checking Tailscale endpoint"
if curl -sf "${BRINEWORKS_URL}/health" > /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! Brineworks available at ${BRINEWORKS_URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${BRINEWORKS_URL}"
    echo ""
    echo "    If this is the first deploy, you need to approve the service:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Find 'brineworks' and approve the pending host"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect approval):"
    echo "       sudo tailscale serve --service=svc:brineworks${HOMELAB_SERVICE_SUFFIX?} --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:brineworks${HOMELAB_SERVICE_SUFFIX?} --https=443 http://127.0.0.1:\$BRINEWORKS_SERVER_PORT"
    echo "    4. Verify: curl ${BRINEWORKS_URL}/health"
fi
