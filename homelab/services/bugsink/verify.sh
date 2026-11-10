#!/usr/bin/env bash
# Read-only post-deploy verification for bugsink. Runs ON picklelab.
#
#   1. /health/ready answers on the loopback port
#   2. the running Bugsink version matches the version pinned in compose.yaml
#   3. the Postgres container reports healthy
#   4. the daily vacuum timer (90-day age cap) is active
#
# Reads state only: curl, `docker exec ... bugsink-show-version`, `docker inspect`,
# `systemctl is-active`. By container name rather than `docker compose`, because
# compose needs the root-only 1Password token to interpolate its env.
#
# Run it from the Mac with `just bugsink-verify`, which feeds this file to ssh on
# stdin (so it works even when the host's checkout predates this script):
#   ssh picklelab 'bash -s' < homelab/services/bugsink/verify.sh
#
# Exits 1 if any check fails. The deploy itself doesn't call this.
set -uo pipefail

SERVICE_DIR=${SERVICE_DIR:-/opt/homelab/homelab/services/bugsink}
WEB=${WEB:-bugsink-web-1}
DB=${DB:-bugsink-db-1}

failures=0
pass() { echo "    PASS: $1"; }
fail() { echo "    FAIL: $1"; failures=$((failures + 1)); }

cd "$SERVICE_DIR" || { echo "ERROR: $SERVICE_DIR not found (is this running on picklelab?)" >&2; exit 2; }

PORT=$(sed -n 's/^BUGSINK_PORT=//p' .env.build 2>/dev/null | tail -n 1)
PORT=${PORT:-8380}
# The tag in `image: bugsink/bugsink:<version>@sha256:...`.
PINNED=$(sed -n 's|^ *image: bugsink/bugsink:\([^@]*\)@.*|\1|p' compose.yaml | head -n 1)

echo "==> Health (http://127.0.0.1:$PORT/health/ready)"
if curl -fsS --connect-timeout 2 --max-time 10 -o /dev/null "http://127.0.0.1:$PORT/health/ready" </dev/null 2>/dev/null; then
    pass "/health/ready answered"
else
    fail "/health/ready did not answer"
fi

echo "==> Version (pinned: ${PINNED:-unknown})"
if running=$(docker exec "$WEB" bugsink-show-version </dev/null 2>&1); then
    running=$(printf '%s' "$running" | tail -n 1)
    echo "    running $running"
    if [ -n "$PINNED" ] && [ "$running" = "$PINNED" ]; then
        pass "running version matches compose.yaml"
    else
        fail "running version $running is not the pinned ${PINNED:-<none found>}"
    fi
else
    printf '%s\n' "$running" | tail -n 3 | sed 's/^/    /'
    fail "could not run bugsink-show-version in $WEB"
fi

echo "==> Database ($DB)"
db_health=$(docker inspect --format '{{.State.Health.Status}}' "$DB" </dev/null 2>/dev/null)
if [ "$db_health" = "healthy" ]; then
    pass "Postgres is healthy"
else
    fail "Postgres health is '${db_health:-missing}'"
fi

echo "==> Age cap (bugsink-vacuum.timer)"
if [ "$(systemctl is-active bugsink-vacuum.timer </dev/null 2>/dev/null)" = "active" ]; then
    pass "vacuum timer is active"
else
    fail "vacuum timer is not active, so events older than 90 days are never deleted"
fi

echo ""
if [ "$failures" -eq 0 ]; then
    echo "All bugsink checks passed."
else
    echo "$failures check(s) failed. Logs: just bugsink-logs"
    exit 1
fi
