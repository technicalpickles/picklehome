#!/usr/bin/env bash
set -euo pipefail

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
