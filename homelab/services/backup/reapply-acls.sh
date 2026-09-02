#!/usr/bin/env bash
# Re-grant the backup user's read ACLs on service data. Must run as root
# (via `ExecStartPre=+` on backup.service, or `sudo` from deploy.sh) --
# it does not sudo internally.
#
# Any chmod() call on a file or directory -- even one unrelated to us, e.g. a
# service locking a freshly-written token down to 600 -- recalculates the
# POSIX ACL mask and silently collapses our grant back to nothing. A one-shot
# setfacl doesn't survive that, so this script re-applies the full grant list
# unconditionally. It's meant to run via `ExecStartPre=+` on backup.service
# (root, regardless of the unit's own User=) right before every backup, and
# also from deploy.sh so a fresh deploy doesn't have to wait for the first
# scheduled run.
#
# -R applies the grant to everything that exists today; -d sets a default ACL
# so files created after this runs inherit it too (until their own chmod()
# wipes it again, which is exactly why this script needs to keep re-running).
set -euo pipefail

BACKUP_USER="backup"

# Whole-tree grants: everything under these paths should be backup-readable.
TREES=(
    /srv/data/second-brain-agent
    /srv/data/brineworks-agent
    /srv/data/nikke
    /srv/data/taskchampion-sync
    /srv/data/climate-auto-switch
)

# Narrower grants: only a specific subpath needs it, the rest of the service
# dir is already readable (or intentionally excluded).
#
# openclaw is scoped to config/ and workspace/ deliberately -- NOT the whole
# /srv/data/openclaw tree. gog-keyring/ and ssh/ hold live secrets
# (auth-profile keyring, deploy keys); granting backup standing plaintext
# read there was explicitly rejected as a tradeoff, not just unaddressed --
# do not add /srv/data/openclaw itself, or those, to this list.
#
# config/ includes config/state/ (openclaw.sqlite), which is the one whose
# ACL mask kept getting reset between backups even after a one-shot setfacl
# -- see the backup README's "Why ACLs get re-applied" section and
# taskwarrior a949871a. This recursive re-grant may well fix that gap for
# real now that it re-runs before every backup; worth confirming on the
# first post-deploy run rather than assuming.
PATHS=(
    /srv/data/openclaw/config
    /srv/data/openclaw/workspace
    /srv/data/woodpecker/ts-state
)

for path in "${TREES[@]}" "${PATHS[@]}"; do
    [ -e "$path" ] || continue
    setfacl -R -m u:"$BACKUP_USER":rX -m d:u:"$BACKUP_USER":rX "$path"
done
