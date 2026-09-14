#!/usr/bin/env bash
# Deploy github-actions-runner on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/github-actions-runner"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Writing filtered op-run template"
"$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" > "$SERVICE_DIR/.env.op.template"

echo "==> Pulling runner image"
cd "$SERVICE_DIR"
# compose.yaml's environment: entries use ${VAR:?required}, so compose refuses to even
# parse the file unless every var is set in the process environment - regardless of
# whether the command being run (pull) actually consumes them. The image is pulled
# pre-built (no Dockerfile/build ARGs here), so placeholder values just satisfy
# compose's interpolation check for this unwrapped, unprivileged step; only the
# systemd unit's `op run`-wrapped ExecStart needs the real values. Derive placeholder
# assignments from .env.vars so adding/removing a var propagates automatically.
declare -a env_overrides
# `|| [[ -n "$line" ]]` also processes a final line with no trailing newline
# (.env.vars files aren't guaranteed to end in one) -- a plain `while read` would
# otherwise silently drop it, which would fail this build-placeholder loop's whole
# purpose for exactly the var most likely to be the last one in the file.
while IFS= read -r line || [[ -n "$line" ]]; do
  # Skip comments and blank lines
  [[ "$line" =~ ^#|^[[:space:]]*$ ]] && continue
  env_overrides+=("${line}=build-placeholder")
done < "$SERVICE_DIR/.env.vars"

env "${env_overrides[@]}" docker compose -f compose.yaml pull

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/github-actions-runner.service" /etc/systemd/system/

echo "==> Reloading systemd and (re)starting service"
sudo systemctl daemon-reload
sudo systemctl enable github-actions-runner.service
sudo systemctl restart github-actions-runner.service

echo "==> Status"
systemctl status github-actions-runner.service --no-pager
