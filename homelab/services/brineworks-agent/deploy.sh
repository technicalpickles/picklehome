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
# The agent runs as its own Tailscale node (ts-agent sidecar in compose), so
# sshd (:22) and mosh UDP are reachable directly at brineworks-agent.<tailnet>.
# No host port publish, no tailscale serve. See brineworks ADR 0006.

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
# config:    OAuth client-secrets JSON (app-credentials.json, copied during the
#            Gmail bootstrap; PFA_APP_CREDENTIALS in compose points here).
# ts-state:  the ts-agent sidecar's Tailscale node identity (TS_STATE_DIR), so the
#            node persists across recreates instead of churning the device list.
sudo mkdir -p "$DATA_DIR/ssh/host_keys" "$DATA_DIR/keyring" "$DATA_DIR/workspace" "$DATA_DIR/config" "$DATA_DIR/ts-state"
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

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/brineworks-agent.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable brineworks-agent.service
sudo systemctl restart brineworks-agent.service

echo "==> Status"
systemctl status brineworks-agent.service --no-pager

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
AGENT_HOST="brineworks-agent.${TAILNET}"

echo ""
echo "==> Waiting for the agent node's sshd at ${AGENT_HOST}:22"
# The agent is its own tailnet node now (ts-agent sidecar). Once the node has
# registered and (first deploy only) been approved, this host can reach its
# sshd over the tailnet directly. No host loopback port, no serve.
for i in 1 2 3 4 5 6 7 8 9 10; do
    if timeout 2 bash -c "cat < /dev/null > /dev/tcp/${AGENT_HOST}/22" 2>/dev/null; then
        echo "    Reachable at ${AGENT_HOST}:22"
        echo ""
        echo "Done! Connect with: ssh technicalpickles@${AGENT_HOST}"
        echo "Then: tmux attach   (or tmux new -s main)"
        echo "Phone (mosh): mosh technicalpickles@${AGENT_HOST} then tmux attach"
        exit 0
    fi
    echo "    Waiting for the node (attempt $i/10)..."
    sleep 2
done

echo "    WARNING: ${AGENT_HOST}:22 not reachable after 10 attempts"
echo ""
echo "    Check the node registered:"
echo "      tailscale status | grep brineworks-agent"
echo "      docker compose -f compose.yaml -f compose.picklelab.yaml logs ts-agent"
echo "    First deploy only: approve the device at https://login.tailscale.com/admin/machines"
echo "    (and remove the old 'brineworks-agent' Service at .../admin/services so the"
echo "     name doesn't collide with the node). MagicDNS for the node can lag a few seconds."
