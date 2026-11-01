#!/usr/bin/env bash
# Print everything a host-identity change could alter, in a fixed order, so
# `diff before after` proves a refactor left a host's behavior untouched.
# Read-only, no sudo. Run on the host from /opt/homelab:
#   cd /opt/homelab && homelab/scripts/host-snapshot.sh > before.txt
set -euo pipefail

DATA_DIR=/srv/data/openclaw

# systemctl cat starts each unit with "# /etc/systemd/system/<unit>", so that
# output is its own header.
systemctl cat openclaw.service brineworks-server.service

echo
echo "# service env templates (path: key=ref)"
shopt -s nullglob
for f in homelab/services/*/.env.op*.template; do
    sed "s|^|$f: |" "$f"
done | LC_ALL=C sort

echo
echo "# homelab/services/brineworks-server/.env.build"
if [ -f homelab/services/brineworks-server/.env.build ]; then
    cat homelab/services/brineworks-server/.env.build
else
    echo "# missing: homelab/services/brineworks-server/.env.build"
fi

echo
echo "# tailscale serve status"
tailscale serve status

echo
echo "# $DATA_DIR/gog-config/config.json"
if [ -f "$DATA_DIR/gog-config/config.json" ]; then
    cat "$DATA_DIR/gog-config/config.json"
else
    echo "# missing: $DATA_DIR/gog-config/config.json"
fi

echo
echo "# git -C $DATA_DIR/workspace config user.name"
if [ -d "$DATA_DIR/workspace/.git" ]; then
    git -C "$DATA_DIR/workspace" config user.name || echo "# unset"
else
    echo "# missing: $DATA_DIR/workspace/.git"
fi

echo
echo "# git -C $DATA_DIR/workspace config user.email"
if [ -d "$DATA_DIR/workspace/.git" ]; then
    git -C "$DATA_DIR/workspace" config user.email || echo "# unset"
else
    echo "# missing: $DATA_DIR/workspace/.git"
fi
