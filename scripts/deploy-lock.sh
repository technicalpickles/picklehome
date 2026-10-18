# Source from a bash recipe; then call `deploy_lock_acquire <host> <label>`.
#
# Holds picklelab's host-wide deploy lock (flock on /run/lock/@NAME@.lock)
# for the rest of the recipe, across all of its ssh/scp calls. One background ssh
# runs `flock -n` and then blocks reading stdin (a fifo we keep open); when this
# recipe exits, or the Mac or network dies, stdin closes, the remote shell exits,
# and the kernel releases the lock. Fail fast: if held, prints who by and returns 1.
#
# The remote script is inline on purpose: it must work before the host has pulled
# this repo. It contains no single quotes (it is wrapped in them for the ssh call).

DEPLOY_LOCK_REMOTE='
exec 9>>/run/lock/@NAME@.lock
if ! flock -n 9; then
    echo "BUSY: $(cat /run/lock/@NAME@.info 2>/dev/null || echo unknown)"
    exit 75
fi
read -r info
echo "$info" >/run/lock/@NAME@.info
echo LOCKED
cat >/dev/null
: >/run/lock/@NAME@.info
'

deploy_lock_release() {
    exec 8>&- 2>/dev/null || true
    if [ -n "${DEPLOY_LOCK_PID:-}" ]; then
        wait "$DEPLOY_LOCK_PID" 2>/dev/null || true
    fi
    [ -n "${DEPLOY_LOCK_DIR:-}" ] && rm -rf "$DEPLOY_LOCK_DIR"
    DEPLOY_LOCK_PID=""
    DEPLOY_LOCK_DIR=""
}

deploy_lock_acquire() {
    local host=$1 label=$2 i
    # DEPLOY_LOCK_NAME exists so tests can use a throwaway lock, never the real one.
    local remote=${DEPLOY_LOCK_REMOTE//@NAME@/${DEPLOY_LOCK_NAME:-homelab-deploy}}
    DEPLOY_LOCK_DIR=$(mktemp -d)
    mkfifo "$DEPLOY_LOCK_DIR/in"
    ssh -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
        "$host" "sh -c '$remote'" \
        <"$DEPLOY_LOCK_DIR/in" >"$DEPLOY_LOCK_DIR/out" 2>&1 &
    DEPLOY_LOCK_PID=$!
    exec 8>"$DEPLOY_LOCK_DIR/in"
    echo "$label from $(whoami)@$(hostname -s):$PWD since $(date '+%Y-%m-%dT%H:%M:%S%z')" >&8
    trap deploy_lock_release EXIT
    for i in $(seq 1 400); do
        if grep -q '^LOCKED' "$DEPLOY_LOCK_DIR/out" 2>/dev/null; then
            echo "==> Holding picklelab deploy lock ($label)"
            return 0
        fi
        if ! kill -0 "$DEPLOY_LOCK_PID" 2>/dev/null; then
            break
        fi
        sleep 0.1
    done
    echo "ERROR: could not take the picklelab deploy lock." >&2
    sed 's/^BUSY: /Held by: /' "$DEPLOY_LOCK_DIR/out" >&2
    deploy_lock_release
    return 1
}
