#!/usr/bin/env bash
# Root-privileged wrapper for deploy.sh's Gmail keyring check. The keyring dir is
# root-owned mode 700, so the unprivileged deploy user can't stat the file itself.
# Takes no arguments on purpose: the sudoers grant (homelab/config/sudoers-deploy-ops)
# pins this exact path, so it can only ever answer "does this one file exist".
#
# Exit codes are distinct so deploy.sh can tell "missing" from "sudo itself failed"
# (sudo -n exits 1 when it wants a password, which used to read as "file missing"):
#   0 present, 3 missing. Anything else means the check did not run.
set -euo pipefail
KEYRING_FILE=/srv/data/brineworks-server/keyring/cryptfile.cfg
if [ -f "$KEYRING_FILE" ]; then
    exit 0
fi
exit 3
