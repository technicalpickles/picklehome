#!/usr/bin/env bash
set -euo pipefail

# One mutation of picklelab at a time (shared with the deploy scripts).
source "$(dirname "${BASH_SOURCE[0]}")/deploy-lock.sh"

echo "==> Configuring journald log rotation (500MB cap)"
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/size.conf > /dev/null <<'EOF'
[Journal]
SystemMaxUse=500M
EOF

echo "==> Restarting journald"
sudo systemctl restart systemd-journald

echo "==> Verifying"
journalctl --disk-usage

echo "Done!"
