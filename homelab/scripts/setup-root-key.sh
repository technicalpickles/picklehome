#!/usr/bin/env bash
# Install the av-approved root login on picklelab.
# Design: docs/plans/2026-11-15-av-root-key-design.md
# Idempotent: safe to re-run.
# Run on picklelab as technicalpickles, not under sudo (it calls sudo itself).
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/deploy-lock.sh"

REPO_DIR="${REPO_DIR:-/opt/homelab}"
KEYS_SRC="$REPO_DIR/homelab/config/root-authorized-keys"
AUDIT_SRC="$REPO_DIR/homelab/config/root-ssh-audit"
SSHD_SRC="$REPO_DIR/homelab/config/sshd-root-login.conf"
KEYS_DST=/root/.ssh/authorized_keys
AUDIT_DST=/usr/local/sbin/root-ssh-audit
SSHD_DST=/etc/ssh/sshd_config.d/20-root-login.conf

# Pinned here, not read from KEYS_SRC: /opt/homelab is writable by this user and
# by anything that pushes to origin, so the repo file alone must not decide who
# gets root. Changing the key means changing this line in review.
EXPECTED_FP="SHA256:IYBegJhWPOTTDOfYSUrvjSZqn3sdUEsaWNmwgOoQKec"

echo "==> Checking $KEYS_SRC against the pinned fingerprint"
key_lines=$(grep -cvE '^[[:space:]]*(#|$)' "$KEYS_SRC" || true)
if [ "$key_lines" != 1 ]; then
    echo "ERROR: expected exactly one key in $KEYS_SRC, found $key_lines. Not installing."
    exit 1
fi
actual_fp=$(ssh-keygen -lf "$KEYS_SRC" | awk '{print $2}')
if [ "$actual_fp" != "$EXPECTED_FP" ]; then
    echo "ERROR: $KEYS_SRC has $actual_fp, expected $EXPECTED_FP. Not installing."
    exit 1
fi
if ! grep -q "command=\"$AUDIT_DST\"" "$KEYS_SRC"; then
    echo "ERROR: $KEYS_SRC must force command=\"$AUDIT_DST\". Not installing."
    exit 1
fi

if sudo test -f "$KEYS_DST"; then
    echo "==> Changes to $KEYS_DST"
    sudo diff -u "$KEYS_DST" "$KEYS_SRC" || true
fi

echo "==> Installing root key, audit wrapper, sshd drop-in"
sudo install -d -o root -g root -m 0700 /root/.ssh
sudo install -o root -g root -m 0600 "$KEYS_SRC" "$KEYS_DST"
sudo rm -f /root/.ssh/authorized_keys2
sudo install -o root -g root -m 0755 "$AUDIT_SRC" "$AUDIT_DST"
sudo install -o root -g root -m 0644 "$SSHD_SRC" "$SSHD_DST"

echo "==> Validating sshd config"
if ! sudo sshd -t; then
    echo "ERROR: sshd -t failed. Removing $SSHD_DST so a later reload can't pick it up."
    sudo rm -f "$SSHD_DST"
    exit 1
fi
sudo systemctl reload ssh

echo "==> Verifying"
installed_fp=$(sudo ssh-keygen -lf "$KEYS_DST" | awk '{print $2}')
if [ "$installed_fp" != "$EXPECTED_FP" ]; then
    echo "ERROR: installed key is $installed_fp, expected $EXPECTED_FP"
    exit 1
fi
# Older sshd -T prints prohibit-password under its legacy alias.
effective=$(sudo sshd -T | grep -Ei '^(permitrootlogin|authorizedkeysfile) ' | sed 's/without-password/prohibit-password/' | sort)
expected=$'authorizedkeysfile .ssh/authorized_keys\npermitrootlogin prohibit-password'
if [ "$effective" != "$expected" ]; then
    echo "ERROR: effective sshd settings differ from expected:"
    echo "$effective"
    exit 1
fi
echo "    OK: $installed_fp is root's only key; sshd settings confirmed"

echo ""
echo "Done! From the Mac: ssh picklelab-root id (one av approval)."
