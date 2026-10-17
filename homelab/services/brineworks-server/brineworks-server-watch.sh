#!/usr/bin/env bash
# Liveness check for brineworks-server, run every 5 min by brineworks-server-watch.timer.
# Exists because the server sat dead Oct 10-16 2026 after a reboot with nothing noticing.
#
# Probes the local /health endpoint. State is a consecutive-failure counter: alert once
# after FAIL_THRESHOLD failures in a row (rides out deploys and restarts), then once on
# recovery. Silent while healthy. Alerts always hit the journal; Telegram delivery goes
# through the OpenClaw gateway, same as openclaw's exec-approvals-watch, and is
# best-effort (if the gateway is down too, the journal record still stands).
set -euo pipefail

HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:8765/health}
STATE_DIR=${STATE_DIR:-${STATE_DIRECTORY:-/var/lib/brineworks-server-watch}}
FAIL_THRESHOLD=${FAIL_THRESHOLD:-2}
GATEWAY_CONTAINER=${GATEWAY_CONTAINER:-openclaw-openclaw-1}
UNIT=brineworks-server.service

mkdir -p "$STATE_DIR"
FAILS_FILE="$STATE_DIR/consecutive-failures"
ALERTED_FILE="$STATE_DIR/alerted"

alert() {
  local msg=$1
  echo "ALERT: $msg"

  local owner_json owner_target
  if ! owner_json=$(docker exec "$GATEWAY_CONTAINER" openclaw config get commands.ownerAllowFrom --json 2>/dev/null); then
    echo "ALERT-DELIVERY-FAILED: could not read commands.ownerAllowFrom from $GATEWAY_CONTAINER (is it running?)"
    return 0
  fi
  owner_target=$(printf '%s' "$owner_json" | jq -r '.[0] // empty' 2>/dev/null || true)
  if [ -z "$owner_target" ]; then
    echo "ALERT-DELIVERY-FAILED: no owner target in commands.ownerAllowFrom"
    return 0
  fi
  if ! docker exec "$GATEWAY_CONTAINER" openclaw message send \
      --channel telegram --target "$owner_target" \
      --message "$msg" --json >/dev/null 2>&1; then
    echo "ALERT-DELIVERY-FAILED: telegram send failed (journal record above stands regardless)"
  fi
  return 0
}

fails=$(cat "$FAILS_FILE" 2>/dev/null || echo 0)

if curl -sf --max-time 10 "$HEALTH_URL" >/dev/null; then
  if [ -e "$ALERTED_FILE" ]; then
    alert "✅ brineworks-server is healthy again (after $fails failed checks)"
    rm -f "$ALERTED_FILE"
  fi
  echo 0 > "$FAILS_FILE"
  exit 0
fi

fails=$((fails + 1))
echo "$fails" > "$FAILS_FILE"
state=$(systemctl is-active "$UNIT" 2>/dev/null || true)
echo "health check failed ($fails in a row): $HEALTH_URL, $UNIT is '${state:-unknown}'"

if [ "$fails" -ge "$FAIL_THRESHOLD" ] && [ ! -e "$ALERTED_FILE" ]; then
  alert "🚨 brineworks-server is DOWN: $fails failed health checks in a row ($UNIT is '${state:-unknown}'). Email triage MCP is unavailable. Try: ssh picklelab journalctl -u $UNIT -n 50"
  touch "$ALERTED_FILE"
fi
exit 0
