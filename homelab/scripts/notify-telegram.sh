#!/usr/bin/env bash
# Pipe text in, get it on Josh's phone: some-check | notify-telegram.sh
# Callers pass only stdin. This wrapper owns the secret plumbing: it loads the
# op service-account token (0600 root:root, so callers must be root) and runs
# the notifier under `op run` with the notify service's filtered template.
# Run `just deploy-notify` first, which writes that template.
set -euo pipefail

set -a
. /etc/opt/homelab/op-token-picklehome
set +a

exec op run --env-file=/opt/homelab/homelab/services/notify/.env.op.template -- \
    python3 /opt/homelab/homelab/scripts/notify_telegram.py "$@"
