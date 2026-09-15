#!/usr/bin/env bash
# Deploy Open WebUI on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/open-webui"
DATA_DIR=/srv/data/open-webui
OPEN_TERMINAL_DATA_DIR=/srv/data/open-terminal
# Loopback port tailscaled proxies to; the container listens on 8080 internally.
PORT=8090
# See homelab/services/README.md "Container user model".
CONTAINER_UID=1000
CONTAINER_GID=1000

cd "$REPO_DIR"
echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Writing filtered op-run templates (dual vault)"
# open-webui draws secrets from both 1Password vaults (see .env.template):
# OPEN_WEBUI_HOST/ADMIN_EMAIL/ADMIN_PASSWORD/SECRET_KEY/OPEN_TERMINAL_API_KEY
# are picklehome-vault, but OLLAMA_API_KEY is Brent Pickleclaw-vault. op run
# only authenticates against one service-account token at a time, so these
# are filtered into two templates and chained via op-run-dual.sh -- same
# mechanism open-webui.service's ExecStart/ExecStop use.
# [A-Z0-9_]*, not [A-Z_]*: a var-name class without digits silently drops any
# var whose name contains one from BOTH filtered templates, since the anchored
# `^...=` match fails outright rather than matching a shorter prefix. No
# open-webui var name currently contains a digit, but openclaw's deploy.sh hit
# this for real (OPENCLAW_WORKSPACE_DEPLOY_KEY_B64 et al) -- same script
# shape, so fixed here too rather than leaving a latent trap for the next var.
"$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" \
    | grep '^[A-Z0-9_]*=op://picklehome/' > "$SERVICE_DIR/.env.op.picklehome.template"
"$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" \
    | grep '^[A-Z0-9_]*=op://Brent Pickleclaw/' > "$SERVICE_DIR/.env.op.pickleclaw.template"

echo "==> Creating data directory"
sudo mkdir -p "$DATA_DIR"
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$DATA_DIR"

echo "==> Creating Open Terminal data directory"
sudo mkdir -p "$OPEN_TERMINAL_DATA_DIR"
# The image's `user` account is uid 1000 (Debian `useradd -m` default, no
# explicit --uid; same expectation already confirmed for woodpecker-server's
# equivalent image on this host -- no userns-remap, 1:1 uid mapping). Verify
# with `docker top open-webui-open-terminal-1 -o uid` after first deploy; if
# it's ever different on a future image bump, update CONTAINER_UID here and
# re-chown (see homelab/services/CLAUDE.md "When changing a service's uid").
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$OPEN_TERMINAL_DATA_DIR"

echo "==> Configuring Tailscale serve for openwebui"
sudo tailscale serve --service=svc:openwebui --https=443 "http://127.0.0.1:$PORT"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/open-webui.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable open-webui.service
sudo systemctl restart open-webui.service

echo "==> Status"
systemctl status open-webui.service --no-pager || true

echo ""
echo "==> Checking local health endpoint"
# 20 attempts x 5s = 100s: first boot runs DB migrations and downloads the
# default embedding model from HuggingFace before /health responds. Observed
# ~70s end-to-end on the first real deploy (2026-07-21) -- the original 12x5s
# (60s) budget cut it off ~9s early even though the container came up fine
# moments later. Cached on later restarts, so this budget is first-boot-only
# headroom, not the steady-state cost.
for i in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:$PORT/health" -o /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 20 ]; then
        echo "    WARNING: local health check failed after 20 attempts"
        echo "    Logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for Open WebUI to start (attempt $i/20)..."
    sleep 5
done

echo ""
echo "==> Checking Open Terminal health"
COMPOSE="docker compose -f $SERVICE_DIR/compose.yaml -f $SERVICE_DIR/compose.picklelab.yaml"
# compose.yaml's environment: entries use ${VAR:?required}, so compose refuses to
# even parse the file unless every var is set in the process environment --
# regardless of whether the command being run (exec) actually consumes them.
# This execs into the already-running open-terminal container (started by the
# real op-run-dual-wrapped systemd unit), so placeholder values just satisfy
# compose's interpolation check for this unwrapped, unprivileged step -- same
# rule as woodpecker's equivalent health-check exec (Task 7). Derive placeholder
# assignments from .env.vars so adding/removing a var propagates automatically.
# `|| [[ -n "$line" ]]` also picks up a final line with no trailing newline,
# which a plain `while read` would otherwise silently drop.
declare -a env_overrides
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^#|^[[:space:]]*$ ]] && continue
    env_overrides+=("${line}=build-placeholder")
done < "$SERVICE_DIR/.env.vars"
COMPOSE="env ${env_overrides[*]} $COMPOSE"
for i in $(seq 1 12); do
    if $COMPOSE exec -T open-terminal curl -fsS http://localhost:8000/health -o /dev/null 2>&1; then
        echo "    Open Terminal health check passed"
        break
    fi
    if [ "$i" -eq 12 ]; then
        echo "    WARNING: Open Terminal health check failed after 12 attempts"
        echo "    Logs: $COMPOSE logs open-terminal"
        exit 1
    fi
    echo "    Waiting for Open Terminal to start (attempt $i/12)..."
    sleep 5
done

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
URL="https://openwebui.${TAILNET}"

echo ""
echo "==> Checking Tailscale endpoint"
if curl -fsS "${URL}/health" -o /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! Open WebUI is reachable at ${URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${URL}"
    echo ""
    echo "    If this is the first deploy, this is expected -- every new Service on"
    echo "    picklelab has needed this exact sequence (see the tailscale-cli skill,"
    echo "    'Setting up a brand-new Service'):"
    echo "    1. Define the Service (if not already): https://login.tailscale.com/admin/services"
    echo "       -> 'Define Service' -> Name 'openwebui', Ports '443'"
    echo "    2. This script already ran: sudo tailscale serve --service=svc:openwebui --https=443 http://127.0.0.1:$PORT"
    echo "    3. Restart tailscaled to actually advertise the pending host -- a serve"
    echo "       off/on toggle is NOT a substitute for this:"
    echo "       sudo systemctl restart tailscaled"
    echo "    4. Approve the pending host: https://login.tailscale.com/admin/services"
    echo "    5. Verify: curl ${URL}/health"
fi
