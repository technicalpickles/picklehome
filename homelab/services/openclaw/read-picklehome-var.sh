#!/usr/bin/env bash
# Root-privileged wrapper for deploy.sh's resolve_picklehome_var(): reads a
# single named var out of the picklehome vault into the caller's shell (via
# command substitution), for host-side logic that runs before any container
# exists (deploy-key files, workspace git auth, config-set JSON payloads).
#
# Needs root for the same reason run-doctor-cli.sh does: resolving anything
# from the vault means authenticating `op run` against
# /etc/opt/homelab/op-token-picklehome, which is 0600 root:root by design
# (see homelab/services/README.md). deploy.sh runs as the unprivileged
# deploy user, so it can't read that file itself.
#
# Deliberately narrow: only ever prints ONE named var from openclaw's own
# vault-filtered template (.env.op.picklehome.template, itself filtered to
# just the vars openclaw declares in .env.vars) -- not an arbitrary command,
# not the raw token, not other services' secrets. See
# homelab/config/sudoers-deploy-ops.
set -euo pipefail
SERVICE_DIR="/opt/homelab/homelab/services/openclaw"

set -a
. /etc/opt/homelab/op-token-picklehome
set +a
# --no-masking: see resolve_picklehome_var's own comment in deploy.sh -- the
# caller captures this into a shell variable, never prints it to a terminal.
exec op run --no-masking --env-file="$SERVICE_DIR/.env.op.picklehome.template" -- printenv "$1"
