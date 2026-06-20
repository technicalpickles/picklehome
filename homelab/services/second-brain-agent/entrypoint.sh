#!/usr/bin/env bash
set -euo pipefail

USERNAME="technicalpickles"
GITHUB_USER="technicalpickles"
HOME_DIR="/home/$USERNAME"

# SSH host keys: generate once into the persistent volume so the fingerprint
# doesn't churn across container redeploys (SSH clients remember the old key
# and refuse to connect after a container rebuild otherwise).
HOST_KEY_DIR="/data/ssh/host_keys"
if [ ! -f "$HOST_KEY_DIR/ssh_host_ed25519_key" ]; then
  ssh-keygen -A
  mv /etc/ssh/ssh_host_* "$HOST_KEY_DIR/"
fi
for key in "$HOST_KEY_DIR"/ssh_host_*_key; do
  echo "HostKey $key" >> /etc/ssh/sshd_config
done

# Authorized keys: fetch from GitHub on first boot (deploy key pattern: keys live
# on github.com/<user>.keys, same source as brineworks-agent and homelab/dev).
AUTH_KEYS="$HOME_DIR/.ssh/authorized_keys"
if [ ! -s "$AUTH_KEYS" ]; then
  mkdir -p "$HOME_DIR/.ssh"
  curl -fsSL "https://github.com/$GITHUB_USER.keys" > "$AUTH_KEYS"
  chmod 700 "$HOME_DIR/.ssh"
  chmod 600 "$AUTH_KEYS"
  chown -R "$USERNAME:$USERNAME" "$HOME_DIR/.ssh"
fi

# Redirect Claude Code state to /data so credentials and sessions survive
# container redeploys. deploy.sh pre-creates /data/claude with uid 1000.
rm -rf "$HOME_DIR/.claude"
ln -sf /data/claude "$HOME_DIR/.claude"

# ~/.claude.json (OAuth + MCP state) follows the same pattern. It may not
# exist on first boot; Claude creates it when first authenticated.
rm -f "$HOME_DIR/.claude.json"
ln -sf /data/claude.json "$HOME_DIR/.claude.json"

# Ensure home dir ownership is correct
chown "$USERNAME:$USERNAME" "$HOME_DIR"

exec /usr/sbin/sshd -D
