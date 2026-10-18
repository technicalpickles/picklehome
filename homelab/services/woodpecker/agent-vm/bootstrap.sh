#!/usr/bin/env bash
# Build the OrbStack VM that runs a remote Woodpecker agent (laptop CI node).
#
#   ./bootstrap.sh              # VM named woodpecker-agent
#   ./bootstrap.sh some-name
#
# Idempotent. Installs docker and tailscale, then stops: joining the tailnet
# needs a tagged auth key (tag:ci-agent), so that step is separate. See the
# "Remote agents" section of ../README.md.
set -euo pipefail

VM="${1:-woodpecker-agent}"

if ! orbctl list -q | grep -qx "$VM"; then
  echo "==> Creating VM $VM"
  orbctl create ubuntu:noble "$VM"
fi

echo "==> Provisioning $VM"
orb -m "$VM" bash -s <<'VM_EOF'
set -euo pipefail

if ! command -v docker >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker.io
  sudo usermod -aG docker "$USER"
fi

if ! command -v tailscale >/dev/null; then
  sudo install -d -m 0755 /usr/share/keyrings
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg \
    | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list \
    | sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq tailscale
fi

sudo systemctl enable --now docker tailscaled
docker --version
tailscale version | head -1
tailscale status 2>&1 | head -1 || true
VM_EOF

echo "==> Done. Next: join the tailnet with a tag:ci-agent auth key (see README)."
