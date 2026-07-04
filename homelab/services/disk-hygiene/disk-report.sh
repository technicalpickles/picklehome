#!/usr/bin/env bash
# Read-only disk diagnostic bundle for picklelab.
#
# Installed to /usr/local/sbin/disk-report (root-owned) and made
# passwordless-sudo-able for the technicalpickles user via
# /etc/sudoers.d/docker-prune. Bundles the read-only commands that need root
# (du over root-owned /srv dirs, LVM reads) with the ones that don't, so "what
# does the disk look like" is a single `sudo disk-report` instead of a chain of
# sudo prompts. Must stay READ-ONLY: it is pinned in sudoers, so anything it
# runs, it runs as root without a password.
set -uo pipefail

section() { printf '\n=== %s ===\n' "$1"; }

section "Filesystem usage"
df -h /srv /

section "/srv top-level breakdown"
du -xh -d1 /srv 2>/dev/null | sort -rh

section "/srv/data breakdown"
du -xh -d1 /srv/data 2>/dev/null | sort -rh

section "LVM volume group free space"
vgs
lvs
pvs

section "Docker disk usage (main)"
docker system df

section "Docker disk usage (rootless ci, uid 2000)"
sudo -iu ci docker system df 2>&1 || echo "ci rootless docker unreachable"
