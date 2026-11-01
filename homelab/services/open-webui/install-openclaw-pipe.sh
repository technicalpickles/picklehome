#!/usr/bin/env bash
# Install or update the OpenClaw pipe in picklelab's Open WebUI.
#
#   just install-openclaw-pipe [host]
#
# Runs on the Mac, not on picklelab. Needs `just dotenv` first (admin login and
# the gateway token come from .env) and the tailnet up.
#
# The pipe is Eliav2/openclaw-openwebui-integration: it runs INSIDE the Open WebUI
# backend and drives the gateway agent with its full privileges, so the ref below is
# a pinned commit, not a branch. Bumping it means reading the diff first.
#
# Dev testing: OPENCLAW_PIPE_OWUI_URL, OPENCLAW_PIPE_GATEWAY_URL and
# OPENCLAW_PIPE_DEV_CONTAINER (a local gateway container, used instead of ssh to the
# host) point the script at a local Open WebUI and gateway.
#
# Idempotent. The installer keeps the existing DEVICE_IDENTITY valve, so a rerun
# updates the function in place and does not need a new pairing.
set -euo pipefail

HOST="${1:-picklelab}"

# main as of 2026-10-30: v1.0.0 plus 39 commits. Slash command sync (#234, 2026-10-28)
# is not in the v1.0.0 tag, and SYNC_SLASH_COMMANDS is silently ignored without it.
# Move back to a tag once there is one that has it.
PIPE_REPO=https://github.com/Eliav2/openclaw-openwebui-integration
PIPE_REF=ce6257f7f8fc740ca7f0539653acb3e129e86d5a

# openclaw-proxy is the socat sidecar in compose.picklelab.yaml that forwards to the
# gateway. It is what keeps open-webui off openclaw's network.
GATEWAY_URL="${OPENCLAW_PIPE_GATEWAY_URL:-openclaw-proxy:18789}"
# Must be on the persisted volume. The default (/data/openclaw-bridge) isn't
# writable by uid 1000, and the fallback in /tmp loses the device key on recreate.
STATE_DIR=/app/backend/data/openclaw-bridge
FUNCTION_ID=openclaw_gateway

: "${OPEN_WEBUI_HOST:?run just dotenv}"
: "${OPEN_WEBUI_ADMIN_EMAIL:?run just dotenv}"
: "${OPEN_WEBUI_ADMIN_PASSWORD:?run just dotenv}"
: "${OPENCLAW_GATEWAY_TOKEN:?run just dotenv}"

OWUI_URL="${OPENCLAW_PIPE_OWUI_URL:-https://$OPEN_WEBUI_HOST}"

# Run `openclaw ...` in the gateway container on $HOST (or a local dev container).
gateway_cli() {
    if [ -n "${OPENCLAW_PIPE_DEV_CONTAINER:-}" ]; then
        docker exec "$OPENCLAW_PIPE_DEV_CONTAINER" openclaw "$@"
    else
        # shellcheck disable=SC2029  # the args are meant to expand locally
        ssh "$HOST" docker exec openclaw-openclaw-1 openclaw "$@"
    fi
}

CHECKOUT="${XDG_STATE_HOME:-$HOME/.local/state}/picklehome/openclaw-pipe"

# The checkout persists because install.py keeps the device key in it
# (.pipe_device_identity.json, gitignored) next to the copy in the valves.
if [ ! -d "$CHECKOUT/.git" ]; then
    mkdir -p "$(dirname "$CHECKOUT")"
    git clone --quiet "$PIPE_REPO" "$CHECKOUT"
fi
git -C "$CHECKOUT" fetch --quiet origin
git -C "$CHECKOUT" checkout --quiet --detach "$PIPE_REF"
[ "$(git -C "$CHECKOUT" rev-parse HEAD)" = "$PIPE_REF" ] || { echo "ERROR: checkout is not at $PIPE_REF" >&2; exit 1; }

echo "==> Installing the pipe ($(git -C "$CHECKOUT" describe --tags --always)) into $OWUI_URL"
# A "pairing required" smoke-test failure is expected on the first run.
(
    cd "$CHECKOUT"
    OWUI_URL="$OWUI_URL" \
    OWUI_EMAIL="$OPEN_WEBUI_ADMIN_EMAIL" \
    OWUI_PASSWORD="$OPEN_WEBUI_ADMIN_PASSWORD" \
    GATEWAY_URL="$GATEWAY_URL" \
    GATEWAY_TOKEN="$OPENCLAW_GATEWAY_TOKEN" \
    OPENCLAW_BRIDGE_STATE_DIR="$STATE_DIR" \
        uv run --no-project --with click --with rich --with cryptography \
        python install.py install --no-auto-approve
) || echo "    (installer exited non-zero; continuing to the pairing check)"

echo "==> Approving the device on the gateway if it is pending"
device_id=$(jq -r '.id // empty' "$CHECKOUT/.pipe_device_identity.json")
[ -n "$device_id" ] || { echo "ERROR: no device id in $CHECKOUT/.pipe_device_identity.json" >&2; exit 1; }
request_id=$(gateway_cli devices list --json \
    | jq -r --arg d "$device_id" '[.pending[]? | select(.deviceId == $d)][0] | .requestId // .id // empty')
if [ -n "$request_id" ]; then
    gateway_cli devices approve "$request_id"
else
    echo "    nothing pending for ${device_id:0:12}... (already paired)"
fi

echo "==> Setting valves (owner, file server, slash commands)"
token=$(curl -fsS "$OWUI_URL/api/v1/auths/signin" -H 'Content-Type: application/json' \
    -d "$(jq -n --arg e "$OPEN_WEBUI_ADMIN_EMAIL" --arg p "$OPEN_WEBUI_ADMIN_PASSWORD" '{email:$e,password:$p}')" \
    | jq -r .token)
valves_url="$OWUI_URL/api/v1/functions/id/$FUNCTION_ID/valves"
# OWNER_USERS: only the admin acts as the gateway owner. ENABLE_FILE_SERVER off:
# it is an unauthenticated listener on 0.0.0.0:18791, and install.py turns it back
# on every run, which is why this is here and not a one-time step.
curl -fsS "$valves_url" -H "Authorization: Bearer $token" \
    | jq --arg owner "$OPEN_WEBUI_ADMIN_EMAIL" \
        '. + {OWNER_USERS: $owner, ENABLE_FILE_SERVER: false, SYNC_SLASH_COMMANDS: true}' \
    | curl -fsS -X POST "$valves_url/update" -H "Authorization: Bearer $token" \
        -H 'Content-Type: application/json' -d @- > /dev/null

echo "==> Done. Pick \"OpenClaw · Default\" in the model menu at $OWUI_URL"
