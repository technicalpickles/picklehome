#!/usr/bin/env bash
# Deploy disk-hygiene tooling on picklelab.
# Idempotent: safe on first setup or any subsequent deploy. Run from the repo
# root on the target host (invoked by `just deploy-disk-hygiene`).
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/disk-hygiene"

cd "$REPO_DIR"
echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Installing disk-report to /usr/local/sbin (root-owned, not user-writable)"
sudo install -o root -g root -m 0755 "$SERVICE_DIR/disk-report.sh" /usr/local/sbin/disk-report

echo "==> Validating + installing sudoers drop-in"
# Validate BEFORE activating: a broken /etc/sudoers.d file can lock out sudo.
TMP_SUDOERS=$(mktemp)
cp "$SERVICE_DIR/docker-prune.sudoers" "$TMP_SUDOERS"
if ! sudo visudo -cf "$TMP_SUDOERS"; then
    echo "ERROR: sudoers file failed validation, not installing" >&2
    rm -f "$TMP_SUDOERS"
    exit 1
fi
rm -f "$TMP_SUDOERS"
sudo install -o root -g root -m 0440 "$SERVICE_DIR/docker-prune.sudoers" /etc/sudoers.d/docker-prune

echo "==> Verifying rootless ci docker is reachable (prune must cover both roots)"
if ! sudo -iu ci docker version >/dev/null 2>&1; then
    echo "ERROR: rootless ci docker unreachable ('sudo -iu ci docker version' failed)." >&2
    echo "       The prune job would silently cover only the main daemon." >&2
    echo "       Fix ci lingering / rootless docker before relying on this." >&2
    exit 1
fi

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/docker-prune.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/docker-prune.timer" /etc/systemd/system/

echo "==> Reloading systemd and enabling timer"
sudo systemctl daemon-reload
sudo systemctl enable --now docker-prune.timer

echo "==> Status"
systemctl status docker-prune.timer --no-pager || true
echo ""
echo "Done! Next run:"
systemctl list-timers docker-prune.timer --no-pager
