#!/usr/bin/env bash
# Weekly disk hygiene: prune dangling images + build cache on BOTH docker roots
# (main dockerd + rootless ci dockerd at uid 2000).
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

log "=== Docker prune started ==="

log "### disk-report BEFORE ###"
/usr/local/sbin/disk-report | tee -a "$LOGFILE"

# Capture before usage for delta calculation
BEFORE_USE=$(df --output=pcent /srv | tail -1 | tr -dc '0-9')

log
log "### Pruning main dockerd ###"
docker builder prune -f 2>&1 | tee -a "$LOGFILE"
docker image prune -f 2>&1 | tee -a "$LOGFILE"

log
log "### Pruning rootless ci dockerd (uid 2000) ###"
sudo -iu ci docker builder prune -f 2>&1 | tee -a "$LOGFILE"
sudo -iu ci docker image prune -f 2>&1 | tee -a "$LOGFILE"

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
log "/srv at ${USE}% after prune: healthy"
log "=== Docker prune completed ==="
