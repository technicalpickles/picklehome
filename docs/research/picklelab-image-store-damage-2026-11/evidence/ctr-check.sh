#!/usr/bin/env bash
# Read-only containerd inventory for the 2026-11-14 image store investigation. Writes /tmp/ctr-check.out.
OUT=/tmp/ctr-check.out
B=/srv/containerd/io.containerd.content.v1.content/blobs/sha256
S=/srv/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots
{
  echo "== date: $(date -u +%FT%TZ)"
  echo "== namespaces"; ctr namespaces ls
  echo "== images check (moby)"; ctr -n moby images check 2>&1
  echo "== counts"
  echo "content meta=$(ctr -n moby content ls -q | wc -l) disk=$(ls $B | wc -l)"
  echo "snapshots meta=$(ctr -n moby snapshots ls | tail -n +2 | wc -l) disk=$(ls $S | wc -l)"
  echo "content-in-meta-but-no-file=$(for d in $(ctr -n moby content ls -q); do [ -e $B/${d#sha256:} ] || echo x; done | wc -l)"
  echo "leases=$(ctr -n moby leases ls | tail -n +2 | wc -l)"
  echo "== other namespaces content counts"
  for ns in $(ctr namespaces ls -q); do echo "$ns content=$(ctr -n $ns content ls -q | wc -l) snapshots=$(ctr -n $ns snapshots ls | tail -n +2 | wc -l)"; done
  echo "== newest and oldest snapshot dirs on disk"
  ls -lt --time-style=long-iso $S | sed -n "2,4p"; ls -ltr --time-style=long-iso $S | sed -n "2,4p"
  echo "== metadata db files"
  ls -la --time-style=full-iso /srv/containerd/io.containerd.metadata.v1.bolt/ /srv/containerd/io.containerd.snapshotter.v1.overlayfs/metadata.db 2>&1
} > $OUT 2>&1
chmod 644 $OUT
echo "wrote $OUT"
