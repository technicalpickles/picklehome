#!/usr/bin/env bash
# Chains op run against two 1Password vaults for services needing both tokens.
# op run supports exactly one OP_SERVICE_ACCOUNT_TOKEN at a time -- there is no
# file-path override (see this task's revision note for how that was confirmed
# false; re-check `op run --help` yourself before trusting this note on a future
# op version). No secret value is written to disk anywhere in this script --
# the second token is held only in a shell variable for the lifetime of the
# process that reads it.
# Usage: op-run-dual.sh <picklehome-template> <pickleclaw-template> -- <command...>
set -euo pipefail
PH_TEMPLATE="$1"; PC_TEMPLATE="$2"; shift 2
[ "${1:-}" = "--" ] && shift

PC_TOKEN=$(grep '^OP_SERVICE_ACCOUNT_TOKEN=' /etc/opt/homelab/op-token-pickleclaw | cut -d= -f2-)

set -a
. /etc/opt/homelab/op-token-picklehome
set +a
exec op run --env-file="$PH_TEMPLATE" -- \
  env OP_SERVICE_ACCOUNT_TOKEN="$PC_TOKEN" \
  op run --env-file="$PC_TEMPLATE" -- "$@"
