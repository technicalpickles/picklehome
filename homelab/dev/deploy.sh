#!/usr/bin/env bash
# Deploy the dev container to picklelab and run bootstrap.
# Run from anywhere — uses SSH to execute commands on picklelab.
# Requires: SSH agent forwarding configured for picklelab.
set -euo pipefail

HOST="picklelab"
REMOTE_DIR="/opt/homelab"
COMPOSE_FILES="-f compose.yaml -f compose.picklelab.yaml"
CONTAINER_SSH_PORT=2222
CONTAINER_USER="technicalpickles"

echo "==> Pulling latest on picklelab"
ssh "$HOST" "cd $REMOTE_DIR && git pull"

echo "==> Building and starting dev container"
ssh "$HOST" "cd $REMOTE_DIR/homelab/dev && docker compose $COMPOSE_FILES up -d --build"

echo "==> Waiting for container sshd to be ready"
for i in $(seq 1 30); do
  if ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=accept-new -p "$CONTAINER_SSH_PORT" "$CONTAINER_USER@$HOST" true 2>/dev/null; then
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: container sshd not ready after 30 seconds" >&2
    exit 1
  fi
  sleep 1
done

echo "==> Running bootstrap inside container"
ssh -A -p "$CONTAINER_SSH_PORT" "$CONTAINER_USER@$HOST" "bash /workspace/homelab/dev/bootstrap.sh"

echo ""
echo "Done! Connect with: ssh picklelab-dev"
