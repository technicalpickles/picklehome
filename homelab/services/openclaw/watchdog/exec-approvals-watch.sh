#!/usr/bin/env bash
# Watch OpenClaw exec policy for drift, under any exec-policy mode (full/off
# or allowlist/on-miss). This does not assume allowlist is active anywhere --
# the gateway's own exec policy flip to allowlist/on-miss was deferred
# pending an upstream node-precheck bug, but the policy can still change
# underneath a running container with nothing surfacing it. That
# silent-change gap is the exact detection hole this closes.
#
# Two things get checked, every run, independent of each other:
#   1. Any wildcard allowlist pattern present (full exec in disguise) --
#      always re-checked, not gated on the hash having changed. Only
#      meaningful for file-backed (allowlist-capable) targets; skipped for
#      config-backed targets, see below.
#   2. The read-out content (minus pure bookkeeping fields) hashed and
#      compared to the last known-good hash. First run per container just
#      establishes a baseline (no alert).
#
# Alerts always go to the journal (this is a oneshot systemd unit, so
# stdout/stderr are captured automatically). Telegram delivery on top is
# best-effort: it resolves the send target from the gateway's own configured
# owner (commands.ownerAllowFrom) at alert time, so nothing here hardcodes a
# chat id. If delivery fails for any reason, the journal record still
# stands -- delivery failure is itself logged, never silently swallowed.
set -euo pipefail

STATE_DIR=/var/lib/openclaw-approvals-watch
mkdir -p "$STATE_DIR"

GATEWAY_CONTAINER=openclaw-openclaw-1

# name -> "kind:container:path-or-config-key". Two kinds:
#   file   -- `docker exec <container> cat <path>`. Paths verified by hand
#             per container (they differ: the gateway image runs as uid
#             1000 / "node", the goplaces-node image runs as root).
#   config -- `docker exec <container> openclaw config get <key> --json`.
#
# gateway switched from file to config 2026-09-03: 2026.8.1's `doctor --fix`
# gates on no legacy exec-approvals.json existing (upstream bug, taskwarrior
# 514 / https://github.com/openclaw/openclaw/issues -- see pickleclaw's
# docs/setup-notes.md "still-open blocker on the same upgrade"), so the
# earlier upgrade fix renamed the file aside rather than letting doctor
# migrate it into SQLite (the migration itself never completed --
# confirmed live 2026-09-03, `exec_approvals_config` table is empty). The
# file is not coming back on its own. Under `tools.exec.mode: "full"`
# (picklelab's current policy) there's no allowlist to speak of anyway, so
# `tools.exec` config is now the real drift surface for the gateway --
# revisit this back to a file/SQLite target if picklelab ever flips to
# allowlist mode (tracked: taskwarrior 189ae39b) and the upstream migration
# bug is fixed.
declare -A TARGETS=(
  [gateway]="config:openclaw-openclaw-1:tools.exec"
  [goplaces-node]="file:openclaw-goplaces-node-1:/root/.openclaw/exec-approvals.json"
)

# Log an alert to the journal, then best-effort relay it over the gateway's
# own configured Telegram channel. Every branch returns 0 on purpose: this
# runs under `set -e`, and a non-zero return here (e.g. Telegram being down)
# must never abort the caller's loop before the remaining containers are
# checked.
alert() {
  local msg=$1
  echo "ALERT: $msg"

  local owner_json owner_target
  if ! owner_json=$(docker exec "$GATEWAY_CONTAINER" openclaw config get commands.ownerAllowFrom --json 2>/dev/null); then
    echo "ALERT-DELIVERY-FAILED: could not read commands.ownerAllowFrom from $GATEWAY_CONTAINER (is it running?)"
    return 0
  fi
  if ! owner_target=$(printf '%s' "$owner_json" | jq -r '.[0] // empty' 2>/dev/null); then
    echo "ALERT-DELIVERY-FAILED: could not parse owner target out of commands.ownerAllowFrom"
    return 0
  fi
  if [ -z "$owner_target" ]; then
    echo "ALERT-DELIVERY-FAILED: commands.ownerAllowFrom is empty, nowhere to send"
    return 0
  fi

  if ! docker exec "$GATEWAY_CONTAINER" openclaw message send \
      --channel telegram --target "$owner_target" \
      --message "🚨 approvals-watch: $msg" --json >/dev/null 2>&1; then
    echo "ALERT-DELIVERY-FAILED: telegram send failed (journal record above stands regardless)"
  fi
  return 0
}

for name in "${!TARGETS[@]}"; do
  entry=${TARGETS[$name]}
  kind=${entry%%:*}
  rest=${entry#*:}
  container=${rest%%:*}
  source_ref=${rest#*:}

  if [ "$kind" = "config" ]; then
    if ! current=$(docker exec "$container" openclaw config get "$source_ref" --json 2>/dev/null); then
      alert "$name: cannot read config $source_ref (container down or config key missing)"
      continue
    fi
  else
    if ! current=$(docker exec "$container" cat "$source_ref" 2>/dev/null); then
      alert "$name: cannot read $source_ref (container down, path wrong, or permission denied)"
      continue
    fi

    # Wildcard entries are full-exec in disguise: loudest alert, every run,
    # regardless of whether the hash below has changed. Only meaningful for
    # file-backed targets -- config-backed targets (gateway) have no
    # allowlist field to check under mode="full".
    if printf '%s' "$current" | jq -e '[.agents[]?.allowlist[]?.pattern] | any(. == "*")' >/dev/null 2>&1; then
      alert "$name: WILDCARD allowlist entry present in $source_ref (this is full exec in disguise)"
    fi
  fi

  # Hash with pure bookkeeping fields stripped so routine use (a command
  # actually being run through an existing allowlist entry) doesn't trip a
  # false "changed" alert -- only real policy/allowlist edits should.
  if ! hash=$(printf '%s' "$current" \
      | jq -S 'del(.agents[]?.allowlist[]?.lastUsedAt, .agents[]?.allowlist[]?.lastUsedCommand, .agents[]?.allowlist[]?.lastResolvedPath)' \
      | sha256sum | cut -d' ' -f1); then
    alert "$name: failed to hash $source_ref (unexpected content/format)"
    continue
  fi

  state_file="$STATE_DIR/$name.sha256"
  if [ -f "$state_file" ]; then
    known=$(cat "$state_file")
    if [ "$hash" != "$known" ]; then
      alert "$name: exec policy changed (was ${known:0:12} now ${hash:0:12}). Diff it: docker exec $container $([ "$kind" = config ] && echo "openclaw config get $source_ref --json" || echo "cat $source_ref"), compare with session trajectories."
    fi
  fi
  echo "$hash" > "$state_file"
done
