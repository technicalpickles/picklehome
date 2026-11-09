#!/usr/bin/env bash
set -euo pipefail

python3 /opt/homelab/homelab/services/disk_monitor/disk_monitor.py \
    | /opt/homelab/homelab/scripts/notify-telegram.sh
