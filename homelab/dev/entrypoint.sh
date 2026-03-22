#!/usr/bin/env bash
set -euo pipefail

USERNAME="${DEV_USERNAME:-technicalpickles}"
GITHUB_USER="${DEV_GITHUB_USER:-technicalpickles}"
HOME_DIR="/home/$USERNAME"

# Fetch SSH keys from GitHub if authorized_keys doesn't exist or is empty
AUTH_KEYS="$HOME_DIR/.ssh/authorized_keys"
if [ ! -s "$AUTH_KEYS" ]; then
  mkdir -p "$HOME_DIR/.ssh"
  curl -fsSL "https://github.com/$GITHUB_USER.keys" > "$AUTH_KEYS"
  chmod 700 "$HOME_DIR/.ssh"
  chmod 600 "$AUTH_KEYS"
  chown -R "$USERNAME:$USERNAME" "$HOME_DIR/.ssh"
fi

# Ensure home dir ownership is correct
chown "$USERNAME:$USERNAME" "$HOME_DIR"

exec /usr/sbin/sshd -D
