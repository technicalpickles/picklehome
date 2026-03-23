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

echo "==> Waiting for container sshd to be ready"
for i in $(seq 1 30); do
  if ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=accept-new -p "$CONTAINER_SSH_PORT" "$CONTAINER_USER@$CONTAINER_HOST" true 2>/dev/null; then
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: container sshd not ready after 30 seconds" >&2
    exit 1
  fi
  sleep 1
done

echo "==> Running bootstrap inside container"
ssh -A -o StrictHostKeyChecking=accept-new -p "$CONTAINER_SSH_PORT" "$CONTAINER_USER@$CONTAINER_HOST" "bash /workspace/homelab/dev/bootstrap.sh"

echo ""
echo "Done! Connect with: ssh picklelab-dev"
