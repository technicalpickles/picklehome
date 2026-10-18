#!/usr/bin/env bash
set -euo pipefail

# One mutation of picklelab at a time (shared with the deploy scripts).
source "$(dirname "${BASH_SOURCE[0]}")/deploy-lock.sh"

echo "==> Installing Tailscale"
curl -fsSL https://tailscale.com/install.sh | sh

echo "==> Starting Tailscale (follow the login URL)"
sudo tailscale up

echo ""
echo "==> Verify with: tailscale status"
echo "    Then from your Mac: ssh technicalpickles@<tailscale-ip>"
