#!/usr/bin/env bash
# Root-privileged wrapper for deploy.sh's restic-init check: reads a single
# named var (RESTIC_REPOSITORY, RESTIC_PASSWORD) out of the picklehome vault
# into the caller's shell, for the host-side `restic snapshots`/`restic init`
# probe that runs before backup.service (and its own op-run ExecStart) ever
# starts.
#
# Needs root for the same reason openclaw's copy of this script does:
# resolving anything from the vault means authenticating `op run` against
# /etc/opt/homelab/op-token-picklehome, which is 0600 root:root by design
# (see homelab/services/README.md). deploy.sh runs as the unprivileged
# deploy user, so it can't read that file itself.
#
# Deliberately narrow: only ever prints ONE named var from backup's own
# vault-filtered template (.env.op.template, itself filtered to just the
# vars backup declares in .env.vars) -- not an arbitrary command, not the
# raw token, not other services' secrets. See
# homelab/config/sudoers-deploy-ops.
set -euo pipefail
SERVICE_DIR="/opt/homelab/homelab/services/backup"

set -a
. /etc/opt/homelab/op-token-picklehome
set +a
# --no-masking: the caller captures this into a shell variable, never prints
# it to a terminal.
exec op run --no-masking --env-file="$SERVICE_DIR/.env.op.template" -- printenv "$1"
