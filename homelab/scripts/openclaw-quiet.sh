#!/usr/bin/env bash
# Refuse to proceed while Brent (the OpenClaw Telegram bot) was recently active.
#
#   openclaw-quiet.sh [MINUTES]
#
# Exit 0 when quiet (or when the gateway is down), 75 when a session was active
# in the last MINUTES minutes. Prints the verdict and the active sessions on stdout.
# Called by the openclaw and brineworks-server deploy.sh, and by `just openclaw-quiet`
# (which feeds this file to a remote `bash -s`, so nothing in here may read stdin).
#
# Why: restarting the gateway container kills any Brent turn that is in flight, and
# the user only finds out when the reply never comes. See docs/adr/0003.
#
# Why minutes: it is what `openclaw sessions --active` takes. A turn can sit between
# tool calls for a while, so recent activity (updatedAt) is the signal, not run state.
# Heartbeat sessions tick on a timer whether or not anyone is talking, so they are ignored.
#
# Why exit 75: EX_TEMPFAIL, the same BUSY code deploy-lock.sh uses. Callers already
# treat it as "try again later", not as a broken deploy.
#
# Why node in the container: the image has node but no jq, and the host may not either.
# The CLI output is parsed where the CLI runs, the way pickleclaw's
# scripts/pull-openclaw-session.sh does.
#
# Env:
#   OPENCLAW_CONTAINER            gateway container (default: openclaw-openclaw-1;
#                                 the dev VM's is dev-vm-openclaw-1)
#   HOMELAB_DEPLOY_QUIET_MINUTES  window when no MINUTES arg is given (default: 5)
#   HOMELAB_DEPLOY_EVEN_IF_BUSY   any non-empty value: report BUSY but exit 0
set -euo pipefail

MINUTES=${1:-${HOMELAB_DEPLOY_QUIET_MINUTES:-5}}
CONTAINER=${OPENCLAW_CONTAINER:-openclaw-openclaw-1}

# Prints one line per non-heartbeat session, newest first.
read -r -d '' NODE_PROG <<'JS' || true
let s = "";
process.stdin.on("data", d => s += d).on("end", () => {
  const now = Date.now();
  JSON.parse(s).sessions
    .filter(x => !x.key.includes("heartbeat"))
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .forEach(x => console.log(
      `    ${x.key}  kind=${x.kind}  status=${x.status ?? "none"}  last activity ${Math.max(0, Math.round((now - x.updatedAt) / 1000))}s ago`));
});
JS

# No -i and </dev/null: when this script arrives over `ssh host bash -s`, docker
# exec would otherwise swallow the rest of the script from stdin.
if ! LINES=$(docker exec "$CONTAINER" sh -c '
    LIST=$(openclaw sessions --json --all-agents --active "$1") || exit 1
    printf "%s" "$LIST" | node -e "$2"
  ' _ "$MINUTES" "$NODE_PROG" </dev/null); then
    echo "WARNING: could not list openclaw sessions in $CONTAINER (gateway down?); treating as quiet"
    exit 0
fi

if [ -z "$LINES" ]; then
    echo "quiet: no Brent session activity in the last $MINUTES min"
    exit 0
fi

COUNT=$(printf '%s\n' "$LINES" | wc -l | tr -d ' ')
echo "BUSY: $COUNT session(s) active in the last $MINUTES min:"
printf '%s\n' "$LINES"

if [ -n "${HOMELAB_DEPLOY_EVEN_IF_BUSY:-}" ]; then
    echo "    proceeding anyway (HOMELAB_DEPLOY_EVEN_IF_BUSY=1)"
    exit 0
fi

echo "    Wait for Brent to go quiet, or override with: HOMELAB_DEPLOY_EVEN_IF_BUSY=1 just deploy-<service>" >&2
exit 75
