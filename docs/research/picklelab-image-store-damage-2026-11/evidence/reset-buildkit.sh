#!/usr/bin/env bash
# Reset buildkit's state wholesale so containerd GC can drop the dead cache records it still leases.
# `docker builder prune -a` left records whose data was already gone, and their leases pin
# content records with no blob file (e.g. node:22-slim's base layer), which breaks pulls.
# Dry run by default; --apply stops docker (and the units that require it), moves
# /srv/docker/buildkit aside, deletes every non-container lease in moby with a synchronous GC,
# starts docker and restarts the units that were active. Run as root. Writes /tmp/reset-buildkit.out.
set -u
OUT=/tmp/reset-buildkit.out
BK=/srv/docker/buildkit
APPLY=0; [ "${1:-}" = "--apply" ] && APPLY=1
exec > >(tee "$OUT") 2>&1
echo "== date $(date -u +%FT%TZ) apply=$APPLY"
[ -d "$BK" ] || { echo "ABORT: $BK not found"; exit 1; }
# container leases are 64-hex container ids; everything else is buildkit's
mapfile -t DROP < <(ctr -n moby leases ls -q | grep -vE '^[0-9a-f]{64}$')
KEEP=$(ctr -n moby leases ls -q | grep -cE '^[0-9a-f]{64}$')
mapfile -t UNITS < <(systemctl list-dependencies --reverse --plain --no-legend docker.service \
  | sed 's/^[[:space:]]*//' | grep '\.service$' | grep -vx docker.service | while read -r u; do systemctl is-active -q "$u" && echo "$u"; done)
echo "leases to delete=${#DROP[@]} container leases kept=$KEEP"
echo "active units to restart: ${UNITS[*]}"
echo "content records without file before: $(for d in $(ctr -n moby content ls -q); do [ -e /srv/containerd/io.containerd.content.v1.content/blobs/sha256/${d#sha256:} ] || echo x; done | wc -l)"
du -sh "$BK"
[ "$APPLY" = 1 ] || { echo "dry run, nothing changed"; chmod 644 "$OUT"; exit 0; }
systemctl stop docker.socket docker.service
mv "$BK" "$BK.broken-$(date -u +%Y%m%dT%H%MZ)" && echo "moved $BK aside"
[ ${#DROP[@]} -gt 0 ] && ctr -n moby leases delete --sync "${DROP[@]}" >/dev/null; echo "leases delete rc $?"
systemctl start docker.service; echo "docker start rc $?"
for u in "${UNITS[@]}"; do systemctl start "$u"; echo "start $u rc $?"; done
echo "leases now=$(ctr -n moby leases ls -q | wc -l)"
echo "content records without file after: $(for d in $(ctr -n moby content ls -q); do [ -e /srv/containerd/io.containerd.content.v1.content/blobs/sha256/${d#sha256:} ] || echo x; done | wc -l)"
chmod 644 "$OUT"
