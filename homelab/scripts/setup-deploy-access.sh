#!/usr/bin/env bash
# Set up passwordless sudo for deploy operations on picklelab.
# Idempotent: safe to re-run.
# Run on the target host (picklelab), not from Mac.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/homelab}"
SUDOERS_SRC="$REPO_DIR/homelab/config/sudoers-deploy-ops"
SUDOERS_DST="/etc/sudoers.d/deploy-ops"

echo "==> Validating sudoers file syntax"
# visudo -cf does a syntax check without installing. Catches errors before
# they lock you out of sudo.
if ! sudo visudo -cf "$SUDOERS_SRC"; then
    echo "ERROR: sudoers file has syntax errors. Not installing."
    exit 1
fi

echo "==> Installing sudoers drop-in to $SUDOERS_DST"
sudo cp "$SUDOERS_SRC" "$SUDOERS_DST"
sudo chmod 0440 "$SUDOERS_DST"

echo "==> Verifying passwordless sudo works for a deploy command"
if sudo -n systemctl daemon-reload 2>/dev/null; then
    echo "    OK: passwordless sudo confirmed"
else
    echo "    WARNING: passwordless sudo not working. Check $SUDOERS_DST"
    exit 1
fi

echo ""
echo "Done! Deploy commands no longer require a password or TTY."
