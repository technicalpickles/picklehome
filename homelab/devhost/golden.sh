#!/usr/bin/env bash
# Build (or refresh) the golden OrbStack machine that dev hosts are cloned from.
# Runs on the Mac. Idempotent: creates picklelab-golden only if it is absent,
# re-runs golden-inside.sh in it (every step there is skip-if-done), and always
# leaves it stopped so `orb clone` can copy it.
#
# Every orb call that takes a machine names it. A bare `orb stop` stops all of
# OrbStack, including woodpecker-agent and openclaw.
#
# GOLDEN_NAME overrides the machine name (tests). OPENCLAW_IMAGE_ENV_FILE
# overrides where the pinned image comes from (tests).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

NAME="${GOLDEN_NAME-picklelab-golden}"

# Only a golden may be touched here. This is the guard that keeps a typo (or a
# GOLDEN_NAME=picklelab) from installing things into a real machine.
if [[ ! "$NAME" =~ ^picklelab-golden(-[a-z0-9]+)*$ ]]; then
    echo "ERROR: refusing to use machine name '$NAME': must be picklelab-golden (or picklelab-golden-<suffix>)." >&2
    exit 1
fi

# The pinned image is pickleclaw's, symlinked in (gitignored) the same way the
# other openclaw include files are. deploy.sh sources the same file.
IMAGE_ENV_FILE="${OPENCLAW_IMAGE_ENV_FILE:-$REPO_ROOT/homelab/services/openclaw/openclaw.image.env}"
if [ ! -f "$IMAGE_ENV_FILE" ]; then
    echo "ERROR: $IMAGE_ENV_FILE missing. Symlink openclaw.image.env from the private" >&2
    echo "       pickleclaw repo first (see homelab/services/openclaw/README.md)." >&2
    exit 1
fi
OPENCLAW_IMAGE="$(set +u; unset OPENCLAW_IMAGE; . "$IMAGE_ENV_FILE" >/dev/null; printf '%s' "${OPENCLAW_IMAGE:-}")"
if [ -z "$OPENCLAW_IMAGE" ]; then
    echo "ERROR: $IMAGE_ENV_FILE does not set OPENCLAW_IMAGE." >&2
    exit 1
fi

# `orb list -q` prints one machine name per line.
if orb list -q | grep -Fxq -- "$NAME"; then
    echo "==> $NAME exists, reusing it"
else
    echo "==> Creating $NAME from ubuntu:noble"
    # Flags go after the positional args so clones inherit them: dev hosts are
    # isolated, network-isolated, ssh-agent-forwarded, and have no mounts.
    orb create ubuntu:noble "$NAME" --isolated --isolate-network --forward-ssh-agent
fi

# Stop on every exit path so a failed provisioning run never leaves it running.
trap 'echo "==> Stopping $NAME"; orb stop "$NAME"' EXIT

echo "==> Provisioning $NAME (OPENCLAW_IMAGE=$OPENCLAW_IMAGE)"
# The script is passed as an argument, not on stdin: apt, curl and docker would
# otherwise read the rest of a `bash -s` script off the same stdin.
orb -m "$NAME" env "OPENCLAW_IMAGE=$OPENCLAW_IMAGE" bash -c "$(cat "$HERE/golden-inside.sh")"
