#!/usr/bin/env bash
# Must run as root: the op token file is 0600 root:root. The template it reads
# is written by `just deploy-notify`.
set -euo pipefail

set -a
. /etc/opt/homelab/op-token-picklehome
set +a

exec op run --env-file=/opt/homelab/homelab/services/notify/.env.op.template -- \
    python3 /opt/homelab/homelab/scripts/notify_telegram.py "$@"
