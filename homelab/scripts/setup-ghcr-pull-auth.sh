#!/usr/bin/env bash
# Wires picklelab's root docker client to pull private GHCR images, using the
# 1Password-backed credential helper. Idempotent. Run on picklelab as the deploy
# user; needs sudo for /usr/local/bin and /root/.docker.
#
# Prerequisite (by hand): a classic PAT with only read:packages, stored in the
# picklehome vault as item "GHCR Pull", field "credential".
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/deploy-lock.sh"

HELPER_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/docker-credential-picklehome-ghcr"
HELPER=/usr/local/bin/docker-credential-picklehome-ghcr
CONFIG=/root/.docker/config.json

echo "==> Installing the credential helper"
sudo install -m 0755 -o root -g root "$HELPER_SRC" "$HELPER"

echo "==> Pointing root's docker config at it for ghcr.io"
sudo install -d -m 0700 /root/.docker
current=$(sudo cat "$CONFIG" 2>/dev/null || echo '{}')
echo "$current" | jq '.credHelpers["ghcr.io"] = "picklehome-ghcr"' | sudo tee "$CONFIG" >/dev/null
sudo chmod 0600 "$CONFIG"

echo "==> Checking the token resolves (prints the username only)"
sudo docker-credential-picklehome-ghcr get <<<"ghcr.io" | jq -r .Username
