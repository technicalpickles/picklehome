# shellcheck shell=bash
# Source this from a deploy.sh (after `set -euo pipefail`).
# Defines wait_for_health, a deadline-based replacement for the hand-rolled
# "for i in 1 2 3 4 5; do curl ...; sleep 3; done" loops.
#
#   wait_for_health LABEL URL [DEFAULT_DEADLINE_SECS]
#
# Polls URL until curl gets a 2xx, or the deadline passes. Returns 0 on success,
# 1 on timeout (the caller decides whether that's fatal and what to print next).
# Prints the elapsed time on every poll and on success, so the real cold-start
# time of each service shows up in deploy output instead of being guessed at.
#
# Why a deadline and not an attempt count: containers here take 25-50s to start
# answering (brineworks-server 26-37s, openclaw ~47s cold), and "N attempts x 3s"
# silently stops meaning anything once a connection-reset or a slow curl eats
# part of an attempt. A wall-clock budget says what it means.
#
# Env overrides (read on the host, so they only apply to a hand-run deploy.sh,
# not through `just deploy-*`, since ssh doesn't forward the environment):
#   HEALTH_WAIT_SECS      total budget in seconds (default: 120, or the 3rd arg)
#   HEALTH_WAIT_INTERVAL  seconds between polls (default: 3)
wait_for_health() {
    local label=$1 url=$2
    local deadline=${HEALTH_WAIT_SECS:-${3:-120}}
    local interval=${HEALTH_WAIT_INTERVAL:-3}
    local start=$SECONDS elapsed

    while :; do
        # --max-time: a wedged listener that accepts and never answers would
        # otherwise blow straight through the deadline.
        if curl -fsS --connect-timeout 2 --max-time 5 "$url" -o /dev/null 2>/dev/null; then
            echo "    Local health check passed after $((SECONDS - start))s"
            return 0
        fi
        elapsed=$((SECONDS - start))
        if [ "$elapsed" -ge "$deadline" ]; then
            echo "    WARNING: local health check failed: $label not answering at $url after ${elapsed}s (budget ${deadline}s)"
            return 1
        fi
        echo "    Waiting for $label to start (${elapsed}s/${deadline}s)..."
        sleep "$interval"
    done
}
