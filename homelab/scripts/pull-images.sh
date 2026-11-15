#!/usr/bin/env bash
# Pulls a service's published images, retrying until CI has pushed them.
#
#   pull-images.sh            (run from the service dir, with IMAGE_SHA and
#                              COMPOSE_FILE set, as compose-pull@.service does)
#
# Runs as root under compose-pull@.service so ghcr.io auth comes from the root
# docker config's credential helper (see setup-ghcr-pull-auth.sh). A deploy can
# start before `publish-images` finishes for the same commit, so a missing tag is
# expected for a few minutes. Gives up after PULL_ATTEMPTS * PULL_INTERVAL seconds
# (default 40 * 15s, about 10 minutes) with a message that says which tag is missing.
set -euo pipefail

: "${IMAGE_SHA:?IMAGE_SHA required (from .env.image)}"
attempts=${PULL_ATTEMPTS:-40}
interval=${PULL_INTERVAL:-15}

for i in $(seq 1 "$attempts"); do
    if docker compose pull --quiet; then
        echo "images for ${IMAGE_SHA:0:7} pulled"
        exit 0
    fi
    if [ "$i" -eq "$attempts" ]; then
        echo "ERROR: images for ${IMAGE_SHA:0:7} not pullable after $attempts attempts. CI may still be building or have failed: check the publish-images run for that commit. If it finished, check the pull credential (setup-ghcr-pull-auth.sh)." >&2
        exit 1
    fi
    echo "waiting for images for ${IMAGE_SHA:0:7} (attempt $i/$attempts)..." >&2
    sleep "$interval"
done
