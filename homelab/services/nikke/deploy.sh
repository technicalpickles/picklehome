#!/usr/bin/env bash
# Deploy the nikke roster dashboard on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/nikke"
DATA_DIR=/srv/data/nikke
NIKKE_REPO=/opt/nikke-roster-scanner
CONTAINER_UID=1000
CONTAINER_GID=1000

# Override by exporting NIKKE_PORT before running. Must match the port the
# Tailscale Service proxies to; both are set from this one value.
export NIKKE_PORT="${NIKKE_PORT:-8770}"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Updating nikke-roster-scanner source"
if [ -d "$NIKKE_REPO/.git" ]; then
    git -C "$NIKKE_REPO" pull --ff-only
else
    echo "    Cloning nikke-roster-scanner to $NIKKE_REPO"
    sudo mkdir -p "$NIKKE_REPO"
    sudo chown "$(id -u):$(id -g)" "$NIKKE_REPO"
    # github-nikke, not github.com: nikke-roster-scanner is private, and
    # picklelab's default ~/.ssh/id_ed25519 is a deploy key scoped to the
    # picklehome repo alone, so a plain github.com URL gets "Repository not
    # found". The github-nikke alias in ~/.ssh/config points at a dedicated
    # read-only deploy key (~/.ssh/id_nikke), same pattern as github-brineworks.
    git clone git@github-nikke:technicalpickles/nikke-roster-scanner.git "$NIKKE_REPO"
fi
NIKKE_SHA=$(git -C "$NIKKE_REPO" rev-parse --short HEAD)
echo "    nikke-roster-scanner at $NIKKE_SHA"

echo "==> Writing build metadata"
{
    echo "NIKKE_GIT_SHA=$NIKKE_SHA"
    echo "NIKKE_PORT=$NIKKE_PORT"
} > "$SERVICE_DIR/.env.build"

echo "==> Creating data directory"
# roster.db and .blablalink-session.json live here. Chown before compose up so
# the container's uid 1000 can write; see homelab/services/README.md.
sudo mkdir -p "$DATA_DIR"
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$DATA_DIR"

echo "==> Configuring Tailscale serve for nikke"
# Registers nikke.<tailnet>.ts.net, proxied to localhost:$NIKKE_PORT.
# Idempotent: re-running updates the config in tailscaled's state.
# Requires HTTPS to be enabled in the Tailscale admin console.
sudo tailscale serve --service=svc:nikke --https=443 "http://127.0.0.1:$NIKKE_PORT"

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/nikke.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/nikke-sync.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/nikke-sync.timer" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable nikke.service
sudo systemctl restart nikke.service
sudo systemctl enable --now nikke-sync.timer

echo "==> Status"
systemctl status nikke.service --no-pager
systemctl list-timers nikke-sync.timer --no-pager

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
NIKKE_URL="https://nikke.${TAILNET}"

echo ""
echo "==> Checking local endpoint"
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sf "http://127.0.0.1:$NIKKE_PORT/" > /dev/null 2>&1; then
        echo "    Local check passed"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "    WARNING: local check failed after 10 attempts"
        echo "    Check container logs:"
        echo "      cd $SERVICE_DIR && docker compose --env-file .env.build -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for serve to start (attempt $i/10)..."
    sleep 3
done

echo ""
echo "==> Checking Tailscale endpoint"
if curl -sf "${NIKKE_URL}/" > /dev/null 2>&1; then
    echo "    Tailscale check passed"
    echo ""
    echo "Done! Nikke roster available at ${NIKKE_URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${NIKKE_URL}"
    echo ""
    echo "    If this is the first deploy, you need to approve the service:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Find 'nikke' and approve the pending host"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect approval):"
    echo "       sudo tailscale serve --service=svc:nikke --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:nikke --https=443 http://127.0.0.1:$NIKKE_PORT"
    echo "    4. Verify: curl ${NIKKE_URL}/"
fi
