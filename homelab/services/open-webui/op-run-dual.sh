#!/usr/bin/env bash
# Chains op run against two 1Password vaults for services needing both tokens.
# op run supports exactly one OP_SERVICE_ACCOUNT_TOKEN at a time -- there is no
# file-path override (see this task's revision note for how that was confirmed
# false; re-check `op run --help` yourself before trusting this note on a future
# op version). No secret value is written to disk anywhere in this script, and
# the second token never appears as a command-line argument to any process
# either: it's read directly by a sourced EnvironmentFile-style file in the
# inner `bash -c` process (same technique the outer op run uses for the first
# token), never captured into a shell variable and passed via `env VAR=value`
# the way the first token is. That `env VAR=value` shape would otherwise put
# the raw token in that process's argv, readable via `ps aux` /
# /proc/<pid>/cmdline by any local user for the entire lifetime of the wrapped
# command (which can be a long-running container, e.g. `up -d --build`
# blocking until the container starts).
# Usage: op-run-dual.sh <picklehome-template> <pickleclaw-template> -- <command...>
set -euo pipefail
PH_TEMPLATE="$1"; PC_TEMPLATE="$2"; shift 2
[ "${1:-}" = "--" ] && shift

set -a
. /etc/opt/homelab/op-token-picklehome
set +a
exec op run --env-file="$PH_TEMPLATE" -- \
  bash -c 'set -a; . /etc/opt/homelab/op-token-pickleclaw; set +a; exec op run --env-file="$1" -- "${@:2}"' _ "$PC_TEMPLATE" "$@"
