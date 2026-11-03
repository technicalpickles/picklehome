#!/usr/bin/env bash
# Preflight: write 30GB of zeros to the blank PNY over the USB bridge and
# check dmesg for uas resets. DESTRUCTIVE to $NEW. Run with NEW set.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

require_new_disk
before=$(sudo dmesg | wc -l)

sudo dd if=/dev/zero of="$NEW" bs=1M count=30000 oflag=direct status=progress

echo "--- new kernel messages matching uas|reset|abort:"
if sudo dmesg | tail -n +"$((before + 1))" | grep -iE 'uas|reset|abort'; then
  echo "FAIL: the bridge misbehaved, see the runbook for the quirks fallback" >&2
  exit 1
fi
echo "PASS: no resets during the write"
