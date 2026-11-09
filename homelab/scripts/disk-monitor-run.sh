#!/usr/bin/env bash
# Run by disk-monitor.service. pipefail turns a failed monitor or a failed send
# into a failed unit.
set -euo pipefail

python3 /opt/homelab/homelab/services/disk_monitor/disk_monitor.py \
    | /opt/homelab/homelab/scripts/notify-telegram.sh
