#!/usr/bin/env bash
# Weekly disk hygiene: prune dangling images on BOTH docker roots
# (main dockerd + rootless ci dockerd at uid 2000), and verify the main image
# store before and after.
#
# No `docker builder prune`: 2026-11-14 a prune that freed 9G was followed by
# locally built images missing layers on disk (docs/research/picklelab-image-
# store-damage-2026-11). Not reproduced in a clean store, so the cause is unproven;
# build cache is cheap to leave until it is.
#
# Dangling-only: never -a, never --volumes. A deployed image keeps its tag, so
# dangling prune only reaps the PREVIOUS build (now <none>) and never a running
# service's image. No keep-list needed: the tag is the keep marker.
#
# Runs as root via docker-prune.service. root reaches the main daemon directly
# and the rootless ci daemon via `sudo -iu ci` (no password: it's root).
set -uo pipefail

THRESHOLD=85   # fail the unit if /srv is still above this % after prune
LOGFILE="/var/log/docker-prune.log"

log() {
    echo "[$(date -Iseconds)] $*" | tee -a "$LOGFILE"
}

# docker system df reads metadata and cannot see layers missing on disk, so ask
# containerd directly. Any error or incomplete image fails the unit.
check_images() {
    local out
    out=$(ctr -n moby images check 2>&1) || true
    echo "$out" >> "$LOGFILE"
    if echo "$out" | grep -qE 'level=error|incomplete|^ctr:'; then
        log "ERROR: image store check ($1) found damaged images:" >&2
        echo "$out" | grep -E 'level=error|incomplete|^ctr:' | cut -c1-200 | tee -a "$LOGFILE" >&2
        IMAGES_DAMAGED=1
    else
        log "image store check ($1): ok"
    fi
}
IMAGES_DAMAGED=0

log "=== Docker prune started ==="
check_images before

log "### disk-report BEFORE ###"
/usr/local/sbin/disk-report | tee -a "$LOGFILE"

# Capture before usage for delta calculation
BEFORE_USE=$(df --output=pcent /srv | tail -1 | tr -dc '0-9')

log
log "### Pruning main dockerd ###"
docker image prune -f 2>&1 | tee -a "$LOGFILE"

log
log "### Pruning rootless ci dockerd (uid 2000) ###"
sudo -iu ci docker image prune -f 2>&1 | tee -a "$LOGFILE"

check_images after

log
log "### disk-report AFTER ###"
/usr/local/sbin/disk-report | tee -a "$LOGFILE"

# Capture after usage for delta calculation
AFTER_USE=$(df --output=pcent /srv | tail -1 | tr -dc '0-9')

# Calculate and log delta
if ! [[ "$BEFORE_USE" =~ ^[0-9]+$ ]] || ! [[ "$AFTER_USE" =~ ^[0-9]+$ ]]; then
    log "WARNING: could not read /srv usage (before='${BEFORE_USE}', after='${AFTER_USE}')"
else
    DELTA=$((BEFORE_USE - AFTER_USE))
    log
    log "### Summary ###"
    log "/srv before: ${BEFORE_USE}%, after: ${AFTER_USE}%, freed: ${DELTA}%"
fi

# Guard: surface a still-full disk instead of letting the prune quietly fall
# behind until we're back at 100%. df --output=pcent is GNU coreutils (Ubuntu).
USE=$(df --output=pcent /srv | tail -1 | tr -dc '0-9')
if ! [[ "$USE" =~ ^[0-9]+$ ]]; then
    log "ERROR: could not read /srv usage after prune (df gave: '${USE}')" >&2
    exit 1
fi
log
if [ "$USE" -gt "$THRESHOLD" ]; then
    log "WARNING: /srv still at ${USE}% (> ${THRESHOLD}%) after prune (may be non-docker growth; run: sudo disk-report)" >&2
    exit 1
fi
if [ "$IMAGES_DAMAGED" -ne 0 ]; then
    exit 1
fi
log "/srv at ${USE}% after prune: healthy"
log "=== Docker prune completed ==="
