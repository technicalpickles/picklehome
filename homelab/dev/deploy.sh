#!/usr/bin/env bash
# Deploy the dev container to picklelab and run bootstrap.
# Works both locally on picklelab and remotely via SSH.
# Requires: SSH agent forwarding configured for picklelab (if remote).
set -euo pipefail

REMOTE_DIR="/opt/homelab"
COMPOSE_FILES="-f compose.yaml -f compose.picklelab.yaml"
CONTAINER_SSH_PORT=2222
CONTAINER_USER="technicalpickles"

# Detect if we're already on picklelab
if [ "$(hostname)" = "picklelab" ]; then
  run() { bash -c "$1"; }
  CONTAINER_HOST="localhost"
else
  HOST="picklelab"
  run() { ssh "$HOST" "$1"; }
  CONTAINER_HOST="$HOST"
fi

echo "==> Pulling latest"
run "cd $REMOTE_DIR && git pull"

echo "==> Building and starting dev container"
run "cd $REMOTE_DIR/homelab/dev && docker compose $COMPOSE_FILES up -d --build"

echo "==> Updating known_hosts for container"
ssh-keygen -R "[$CONTAINER_HOST]:$CONTAINER_SSH_PORT" 2>/dev/null || true

echo "==> Waiting for container sshd to be ready"
for i in $(seq 1 30); do
  if ssh-keyscan -p "$CONTAINER_SSH_PORT" "$CONTAINER_HOST" 2>/dev/null | head -1 | grep -q .; then
    ssh-keyscan -p "$CONTAINER_SSH_PORT" "$CONTAINER_HOST" >> ~/.ssh/known_hosts 2>/dev/null
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: container sshd not ready after 30 seconds" >&2
    exit 1
  fi
  sleep 1
done

echo "==> Ensuring SSH config for picklelab-dev"
SSH_CONFIG="$HOME/.ssh/config"
if ! grep -q "Host picklelab-dev" "$SSH_CONFIG" 2>/dev/null; then
  mkdir -p "$HOME/.ssh"
  cat >> "$SSH_CONFIG" <<SSH

Host picklelab-dev
  HostName $CONTAINER_HOST
  Port $CONTAINER_SSH_PORT
  User $CONTAINER_USER
  ForwardAgent yes
SSH
  echo "    Added picklelab-dev to $SSH_CONFIG"
else
  echo "    Already configured"
fi

echo "==> Running bootstrap inside container"
ssh -A -p "$CONTAINER_SSH_PORT" "$CONTAINER_USER@$CONTAINER_HOST" "bash /workspace/homelab/dev/bootstrap.sh"

echo ""
echo "Done! Connect with: ssh picklelab-dev"
