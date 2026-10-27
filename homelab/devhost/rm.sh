#!/usr/bin/env bash
# Usage: rm.sh <name>
# Delete a dev host made by new.sh: the OrbStack machine, its generated identity
# file, and its marked block in ~/.ssh/config.d/hosts. A `Host <name>` entry
# outside the markers is never touched.
#
# Only machines new.sh made are deletable: it must have left homelab/hosts/local/<name>.env.
# ORB_BIN and DEVHOST_LOCAL_DIR override the orb binary and that directory (tests).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

NAME="${1-}"
devhost_check_name "$NAME"

LOCAL_ENV="$LOCAL_DIR/$NAME.env"
if [ ! -f "$LOCAL_ENV" ]; then
    echo "ERROR: refusing to delete '$NAME': $LOCAL_ENV is missing, so devhost-new did not make it." >&2
    exit 1
fi

if "$ORB" list -q </dev/null | grep -Fxq -- "$NAME"; then
    echo "==> Deleting machine $NAME"
    "$ORB" delete -f "$NAME"
else
    echo "==> No machine named $NAME, skipping delete"
fi

rm -f "$LOCAL_ENV"

if [ -f "$SSH_HOSTS_FILE" ]; then
    devhost_ssh_strip_block "$NAME" | devhost_ssh_replace
fi
echo "==> Removed $NAME"
