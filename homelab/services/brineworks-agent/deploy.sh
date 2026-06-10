#!/usr/bin/env bash
# Deploy the Brineworks mobile agent container on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/brineworks-agent"
DATA_DIR=/srv/data/brineworks-agent
BRINEWORKS_REPO=/opt/brineworks
# The in-container user (agent/Dockerfile USER_UID default). The /data volume
# must be writable by this uid for the keyring and session workspace.
CONTAINER_UID=1000
CONTAINER_GID=1000
# Internal sshd port (loopback-published by compose). tailscale serve maps the
# service's public port 22 onto this.
CONTAINER_SSH_PORT=2222

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Updating brineworks source (lockstep build input, shared with the server)"
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

echo "==> Creating data directories on the volume"
# host_keys: sshd host keys (root-owned, written by the entrypoint).
# keyring:   cryptfile keyring file (written by the agent as uid $CONTAINER_UID).
# workspace: email session workspace + scratch (written by the agent).
sudo mkdir -p "$DATA_DIR/ssh/host_keys" "$DATA_DIR/keyring" "$DATA_DIR/workspace"
# Make the volume writable by the in-container user. sshd still reads its
# root-created host keys fine (root can read uid-owned dirs).
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$DATA_DIR"

echo "==> Installing the workspace-repo deploy key (if provided)"
# The agent clones/pushes the brineworks-workspace repo (triage rules + session
# data) with a scoped read-write deploy key. It arrives base64-encoded in the
# filtered .env (single line, so service-env's line-based filter keeps it whole)
# and must land uid-owned 0600: ssh refuses a private key it does not own, and the
# agent user both clones at boot and pushes interactively with it.
# No Obsidian-vault mount is wired (grep -n 'pickled-knowledge\|obsidian'
# compose.picklelab.yaml is empty); rules reach the agent via this clone, not a mount.
ENV_FILE="$SERVICE_DIR/.env"
DEPLOY_KEY_FILE="$DATA_DIR/ssh/workspace_deploy_key"
KEY_B64=""
if [ -f "$ENV_FILE" ]; then
    KEY_B64=$(grep -m1 '^WORKSPACE_DEPLOY_KEY_B64=' "$ENV_FILE" | cut -d= -f2- || true)
fi
if [ -n "$KEY_B64" ]; then
    # The chown -R above made $DATA_DIR (incl. ssh/) owned by uid $CONTAINER_UID,
    # which is the deploy user's own uid -- the host<->container volume-sharing
    # invariant this whole service relies on. So write the key unprivileged: no
    # sudo, which keeps the narrow sudoers allowlist intact (install/tee are not
    # allowlisted and would prompt for a password over non-interactive ssh).
    # umask 077 makes the file 0600 the instant it is created, before any bytes
    # land (never world-readable); the deploy user owns it, so it is uid-owned too.
    ( umask 077; echo "$KEY_B64" | base64 -d > "$DEPLOY_KEY_FILE" )
    echo "    Wrote $DEPLOY_KEY_FILE (0600, uid $CONTAINER_UID)"
else
    echo "    WARNING: WORKSPACE_DEPLOY_KEY_B64 not in $ENV_FILE."
    echo "    The agent can't clone or push brineworks-workspace, so the rules"
    echo "    pipeline is unavailable. Add WORKSPACE_DEPLOY_KEY_B64 to .env.vars +"
    echo "    .env.template (see README 'Prerequisites'), re-run 'just dotenv', redeploy."
fi

echo "==> Configuring Tailscale serve (TCP) for brineworks-agent"
# Registers brineworks-agent.<tailnet>.ts.net:22, raw-TCP passthrough to the
# loopback-published sshd (SSH does its own crypto -- no TLS termination).
# First non-HTTPS Tailscale service in this homelab; if --tcp serve is
# unsupported/fussy, the fallback is to bind the published port to the host's
# tailscale IP instead of loopback and reach it as picklelab:$CONTAINER_SSH_PORT
# (see the WARNING block at the end of this script).
sudo tailscale serve --service=svc:brineworks-agent --tcp=22 "tcp://127.0.0.1:$CONTAINER_SSH_PORT"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/brineworks-agent.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable brineworks-agent.service
sudo systemctl restart brineworks-agent.service

echo "==> Status"
systemctl status brineworks-agent.service --no-pager

echo ""
echo "==> Waiting for container sshd to accept connections on 127.0.0.1:$CONTAINER_SSH_PORT"
for i in 1 2 3 4 5 6 7 8 9 10; do
    if timeout 1 bash -c "cat < /dev/null > /dev/tcp/127.0.0.1/$CONTAINER_SSH_PORT" 2>/dev/null; then
        echo "    sshd is accepting connections"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "    WARNING: sshd not accepting connections after 10 attempts"
        echo "    Check container logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for sshd (attempt $i/10)..."
    sleep 2
done

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
AGENT_HOST="brineworks-agent.${TAILNET}"

echo ""
echo "==> Checking Tailscale service endpoint"
if timeout 3 bash -c "cat < /dev/null > /dev/tcp/${AGENT_HOST}/22" 2>/dev/null; then
    echo "    Tailscale service reachable at ${AGENT_HOST}:22"
    echo ""
    echo "Done! Connect with: ssh technicalpickles@${AGENT_HOST}"
    echo "Then: tmux attach   (or tmux new -s main)"
else
    echo "    WARNING: Tailscale service not reachable at ${AGENT_HOST}:22"
    echo ""
    echo "    If this is the first deploy, approve the service:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Find 'brineworks-agent' and approve the pending host"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect approval):"
    echo "       sudo tailscale serve --service=svc:brineworks-agent --tcp=22 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:brineworks-agent --tcp=22 tcp://127.0.0.1:$CONTAINER_SSH_PORT"
    echo "    4. Verify: ssh technicalpickles@${AGENT_HOST}"
    echo ""
    echo "    Fallback (if TCP serve isn't supported): change the compose port"
    echo "    bind in compose.picklelab.yaml from 127.0.0.1:$CONTAINER_SSH_PORT to the"
    echo "    host's tailscale IP, redeploy, then reach it directly:"
    echo "       ssh -p $CONTAINER_SSH_PORT technicalpickles@picklelab.${TAILNET}"
fi
