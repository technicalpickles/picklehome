#!/usr/bin/env bash
# Root-privileged wrapper for deploy.sh's one-off `openclaw <cli-args>` calls
# (onboard / config set / config patch / doctor --fix). Those need the SAME
# real secrets the long-running gateway gets, which means resolving them via
# op-run-dual.sh -- which sources /etc/opt/homelab/op-token-{picklehome,
# pickleclaw}, both 0600 root:root by design (see homelab/services/README.md).
# deploy.sh itself runs as the unprivileged deploy user, so it can't read
# those directly; this script is the sudo boundary instead.
#
# Deliberately narrow: everything except the trailing openclaw CLI args is
# hardcoded (service dir, templates, compose files, image/entrypoint), so the
# passwordless sudoers grant for this exact script path can't be used to run
# an arbitrary command as root -- only the openclaw CLI, against this
# service's fixed compose project. See homelab/config/sudoers-deploy-ops.
set -euo pipefail
SERVICE_DIR="/opt/homelab/homelab/services/openclaw"
cd "$SERVICE_DIR"

# OPENCLAW_IMAGE (pinned image tag, not a secret -- see deploy.sh's own comment
# on IMAGE_ENV_FILE) is exported into deploy.sh's shell, but sudo's env_reset
# strips it before it reaches this script. Source it independently rather than
# relying on the caller's environment surviving the privilege boundary.
if [ -f "$SERVICE_DIR/openclaw.image.env" ]; then
    set -a
    . "$SERVICE_DIR/openclaw.image.env"
    set +a
fi

exec "$SERVICE_DIR/op-run-dual.sh" \
    "$SERVICE_DIR/.env.op.picklehome.template" "$SERVICE_DIR/.env.op.pickleclaw.template" -- \
    docker compose -f compose.yaml -f compose.picklelab.yaml run --rm --no-deps --entrypoint node openclaw dist/index.js "$@"
