#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/deploy-lock.sh"

REPO_DIR="${REPO_DIR:-/opt/homelab}"
SRC="$REPO_DIR/homelab/config/needrestart-containerd.conf"
DST="/etc/needrestart/conf.d/50-picklehome-containerd.conf"
MAIN_CONF="/etc/needrestart/needrestart.conf"
OVERRIDE="$REPO_DIR/homelab/scripts/needrestart-override"

if [ ! -r "$MAIN_CONF" ]; then
    echo "ERROR: $MAIN_CONF not found; is needrestart installed?" >&2
    exit 1
fi

# needrestart evals conf.d as root Perl during apt runs, so the installed copy is
# root-owned rather than a link into this user-writable checkout.
echo "==> Installing $DST"
sudo install -D -m 0644 -o root -g root "$SRC" "$DST"

echo "==> Verifying needrestart skips containerd and docker"
result=$(sudo perl "$OVERRIDE" "$MAIN_CONF" containerd.service docker.service)
echo "$result" | sed 's/^/    /'
if [ "$(awk '$2 == 0' <<<"$result" | wc -l)" -ne 2 ]; then
    echo "ERROR: needrestart would still restart one of them. Check $DST" >&2
    exit 1
fi

echo ""
echo "Done! needrestart now defers containerd and docker; host-state's runtime-docker check says when they need a restart."
