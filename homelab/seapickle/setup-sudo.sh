#!/usr/bin/env bash
# Set up passwordless sudo for running bootstrap.sh on seapickle.
# Idempotent: safe to re-run.
# Run on the Pi itself (not from the Mac): ./setup-sudo.sh
set -euo pipefail

SUDOERS_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sudoers-seapickle"
SUDOERS_DST="/etc/sudoers.d/seapickle"

echo "==> Validating sudoers file syntax"
if ! sudo visudo -cf "$SUDOERS_SRC"; then
    echo "ERROR: sudoers file has syntax errors. Not installing."
    exit 1
fi

echo "==> Installing sudoers drop-in to $SUDOERS_DST"
sudo cp "$SUDOERS_SRC" "$SUDOERS_DST"
sudo chmod 0440 "$SUDOERS_DST"

echo "==> Verifying passwordless sudo works for bootstrap.sh"
if sudo -n -l 2>/dev/null | grep -q 'bootstrap\.sh'; then
    echo "    OK: passwordless sudo confirmed"
else
    echo "    WARNING: could not confirm passwordless sudo. Check $SUDOERS_DST"
    exit 1
fi

echo ""
echo "Done! bootstrap.sh no longer requires a password."
