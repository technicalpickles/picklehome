# Source this from a deploy.sh / setup-*.sh (after `set -euo pipefail`).
# Takes the one host-wide deploy lock, or exits 75 saying who holds it.
#
# `just deploy-*` recipes already hold the lock for their whole run (several ssh
# calls, see scripts/deploy-lock.sh) and set HOMELAB_DEPLOY_LOCK_HELD=1 on the
# final ssh, so this is a no-op for them. A hand-run script takes the lock itself.
#
# flock(1) on fd 9: the kernel drops it when this process dies, so there is no
# stale-lock state to clean up. /run/lock is tmpfs, world-writable, no sudo needed.
if [ "${HOMELAB_DEPLOY_LOCK_HELD:-}" != 1 ]; then
    exec 9>>/run/lock/homelab-deploy.lock
    if ! flock -n 9; then
        echo "ERROR: another deploy holds the picklelab lock: $(cat /run/lock/homelab-deploy.info 2>/dev/null || echo unknown)" >&2
        exit 75
    fi
    echo "$(basename "$0") by ${USER:-?}@$(hostname -s) (pid $$) since $(date -Is)" >/run/lock/homelab-deploy.info
fi
