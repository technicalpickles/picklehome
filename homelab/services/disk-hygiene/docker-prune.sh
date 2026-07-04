#!/usr/bin/env bash
# Weekly disk hygiene: prune dangling images + build cache on BOTH docker roots
# (main dockerd + rootless ci dockerd at uid 2000).
#
# Dangling-only: never -a, never --volumes. A deployed image keeps its tag, so
# dangling prune only reaps the PREVIOUS build (now <none>) and never a running
# service's image. No keep-list needed — the tag is the keep marker.
#
# Runs as root via docker-prune.service. root reaches the main daemon directly
# and the rootless ci daemon via `sudo -iu ci` (no password: it's root).
set -uo pipefail

THRESHOLD=85   # fail the unit if /srv is still above this % after pruning

echo "### disk-report BEFORE ###"
/usr/local/sbin/disk-report

echo
echo "### Pruning main dockerd ###"
docker builder prune -f
docker image prune -f

echo
echo "### Pruning rootless ci dockerd (uid 2000) ###"
sudo -iu ci docker builder prune -f
sudo -iu ci docker image prune -f

echo
echo "### disk-report AFTER ###"
/usr/local/sbin/disk-report

# Guard: surface a still-full disk instead of letting the prune quietly fall
# behind until we're back at 100%. df --output=pcent is GNU coreutils (Ubuntu).
USE=$(df --output=pcent /srv | tail -1 | tr -dc '0-9')
echo
if [ "$USE" -gt "$THRESHOLD" ]; then
    echo "WARNING: /srv still at ${USE}% (> ${THRESHOLD}%) after prune" >&2
    exit 1
fi
echo "/srv at ${USE}% after prune — healthy"
