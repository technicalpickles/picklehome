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
    /srv/data/openclaw
    /srv/data/second-brain-agent
    /srv/data/brineworks-agent
    /srv/data/nikke
    /srv/data/taskchampion-sync
    /srv/data/climate-auto-switch
)

# Narrower grants: only a specific subpath needs it, the rest of the service
# dir is already readable (or intentionally excluded).
PATHS=(
    /srv/data/woodpecker/ts-state
)

for path in "${TREES[@]}" "${PATHS[@]}"; do
    [ -e "$path" ] || continue
    setfacl -R -m u:"$BACKUP_USER":rX -m d:u:"$BACKUP_USER":rX "$path"
done
