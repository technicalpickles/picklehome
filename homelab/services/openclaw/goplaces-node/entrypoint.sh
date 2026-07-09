#!/usr/bin/env bash
set -euo pipefail
exec openclaw node run \
  --host "$OPENCLAW_NODE_HOST" \
  --port "$OPENCLAW_NODE_PORT" \
  --display-name "$OPENCLAW_NODE_DISPLAY_NAME"
