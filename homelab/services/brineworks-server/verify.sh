#!/usr/bin/env bash
# Read-only post-deploy verification for brineworks-server. Runs ON picklelab.
#
# Bundles the checks that used to be four manual commands after every deploy:
#   1. /health answers locally, and its sha matches /opt/brineworks HEAD
#   2. alembic is at head (the container runs `alembic upgrade head` on start)
#   3. no Gmail/credential errors in the recent container logs
#
# Reads state only: curl, git rev-parse, `docker exec ... alembic current`,
# `docker logs`. Nothing here restarts, rebuilds, or writes anything.
#
# It talks to the container by name instead of through `docker compose`: compose
# needs the 1Password service-account token (root-only) to interpolate its env,
# which an ssh session can't read, and plain exec/logs need no env at all.
#
# Run it from the Mac with `just brineworks-server-verify`, which feeds this file to
# ssh on stdin (so it works even when the host's checkout predates this script):
#   ssh picklelab 'bash -s -- [since]' < homelab/services/brineworks-server/verify.sh
#
# Exits 1 if any check fails. The deploy itself doesn't call this.
set -uo pipefail

SINCE=${1:-30m}
SERVICE_DIR=${SERVICE_DIR:-/opt/homelab/homelab/services/brineworks-server}
BRINEWORKS_REPO=${BRINEWORKS_REPO:-/opt/brineworks}
CONTAINER=${CONTAINER:-brineworks-server-server-1}
# What a broken Gmail keyring looks like in the server log (see
# server/brineworks_server/mcp/gmail_bootstrap.py in brineworks): the production
# boot failure message, the exception types behind it, and Google's revoked-token errors.
LOG_PATTERN=${LOG_PATTERN:-'Gmail credentials unavailable|AuthError|KeyringError|RefreshError|invalid_grant'}

failures=0
pass() { echo "    PASS: $1"; }
fail() { echo "    FAIL: $1"; failures=$((failures + 1)); }

cd "$SERVICE_DIR" || { echo "ERROR: $SERVICE_DIR not found (is this running on picklelab?)" >&2; exit 2; }

PORT=$(sed -n 's/^BRINEWORKS_SERVER_PORT=//p' .env.build 2>/dev/null | tail -n 1)
PORT=${PORT:-8765}

echo "==> Health (http://127.0.0.1:$PORT/health)"
if body=$(curl -fsS --connect-timeout 2 --max-time 10 "http://127.0.0.1:$PORT/health" </dev/null 2>&1); then
    echo "    $body"
    pass "/health answered"
    deployed_sha=$(git -C "$BRINEWORKS_REPO" rev-parse --short HEAD 2>/dev/null || true)
    if [ -z "$deployed_sha" ]; then
        echo "    (could not read $BRINEWORKS_REPO HEAD, skipping the sha comparison)"
    elif printf '%s' "$body" | grep -q "\"sha\": *\"$deployed_sha\""; then
        pass "running sha matches $BRINEWORKS_REPO HEAD ($deployed_sha)"
    else
        fail "running sha doesn't match $BRINEWORKS_REPO HEAD ($deployed_sha): stale build layers, or the build-arg didn't thread through"
    fi
else
    echo "    $body"
    fail "/health did not answer (503 means the database probe failed)"
fi

echo "==> Migrations (alembic current)"
if alembic_out=$(docker exec "$CONTAINER" alembic current </dev/null 2>&1); then
    printf '%s\n' "$alembic_out" | sed 's/^/    /'
    if printf '%s' "$alembic_out" | grep -q '(head)'; then
        pass "alembic is at head"
    else
        fail "alembic is not at head"
    fi
else
    printf '%s\n' "$alembic_out" | sed 's/^/    /'
    fail "could not run alembic current in the server container"
fi

echo "==> Logs (last $SINCE, looking for: $LOG_PATTERN)"
if log_out=$(docker logs --since "$SINCE" "$CONTAINER" </dev/null 2>&1); then
    if hits=$(printf '%s\n' "$log_out" | grep -E "$LOG_PATTERN"); then
        printf '%s\n' "$hits" | tail -n 10 | sed 's/^/    /'
        fail "Gmail/credential errors in the server log"
    else
        pass "no Gmail/credential errors"
    fi
else
    printf '%s\n' "$log_out" | tail -n 5 | sed 's/^/    /'
    fail "could not read the server logs"
fi

echo ""
if [ "$failures" -eq 0 ]; then
    echo "All brineworks-server checks passed."
else
    echo "$failures check(s) failed. Logs: just brineworks-server-logs"
    exit 1
fi
