#!/usr/bin/env bash
# Deploy OpenClaw on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/openclaw"
DATA_DIR=/srv/data/openclaw
WORKSPACE_REPO_URL="git@github.com:technicalpickles/openclaw-workspace.git"
# Image default (node user) — see homelab/services/README.md "Container user model".
CONTAINER_UID=1000
CONTAINER_GID=1000

COMPOSE="docker compose -f compose.yaml -f compose.picklelab.yaml"
RUN_CLI="$COMPOSE run --rm --no-deps --entrypoint node openclaw dist/index.js"

cd "$REPO_DIR"
echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Creating data directories on the volume"
# config:    writable root config (openclaw.json), created by `onboard`, plus memory/sessions/credentials
# workspace: agent's identity/memory repo (openclaw-workspace), cloned below
# auth:      OpenClaw's own auth-profile store
# bin:       drop-in CLIs, bind-mounted read-only to /opt/tools in-container
# ssh:       the workspace deploy key, written below
sudo mkdir -p "$DATA_DIR/config" "$DATA_DIR/workspace" "$DATA_DIR/auth" "$DATA_DIR/bin" "$DATA_DIR/ssh"

echo "==> Fixing data directory ownership"
# Do this now, right after mkdir, not at the end: it makes $DATA_DIR owned by uid
# $CONTAINER_UID, which is also the deploy user's own uid on picklelab (both 1000)
# -- the host<->container volume-sharing invariant this service relies on. That
# lets the deploy-key write and workspace clone below run unprivileged (no sudo),
# same trick brineworks-agent uses: `tee`/git-as-root aren't in the narrow sudoers
# allowlist and would prompt for a password over non-interactive ssh.
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$DATA_DIR"

echo "==> Installing the workspace-repo deploy key (if provided)"
# The workspace (github.com/technicalpickles/openclaw-workspace) is cloned host-side,
# once, using a scoped write deploy key. It arrives base64-encoded in the filtered
# .env (single line, so service-env's line-based filter keeps it whole) and must land
# 0600: ssh refuses a private key with looser permissions. Same pattern as
# brineworks-agent's WORKSPACE_DEPLOY_KEY_B64, different var name (each service's
# deploy key is scoped to a different repo, so they can't share one .env key name).
ENV_FILE="$SERVICE_DIR/.env"
DEPLOY_KEY_FILE="$DATA_DIR/ssh/workspace_deploy_key"
KEY_B64=""
if [ -f "$ENV_FILE" ]; then
    KEY_B64=$(grep -m1 '^OPENCLAW_WORKSPACE_DEPLOY_KEY_B64=' "$ENV_FILE" | cut -d= -f2- || true)
fi
if [ -n "$KEY_B64" ]; then
    ( umask 077; echo "$KEY_B64" | base64 -d > "$DEPLOY_KEY_FILE" )
    echo "    Wrote $DEPLOY_KEY_FILE (0600, uid $CONTAINER_UID)"
else
    echo "    WARNING: OPENCLAW_WORKSPACE_DEPLOY_KEY_B64 not in $ENV_FILE."
    echo "    Can't clone openclaw-workspace, so the agent starts with an empty"
    echo "    workspace instead of its migrated memory/identity. Add the var to"
    echo "    .env.vars + .env.template (see README), re-run 'just dotenv', redeploy."
fi

echo "==> Cloning the workspace repo (if not already present)"
if [ -f "$DEPLOY_KEY_FILE" ] && [ ! -d "$DATA_DIR/workspace/.git" ]; then
    # Migration from pickleclaw: this is meant to continue the existing workspace
    # repo's history, not auto-init a fresh one — see docs/plans/2026-06-30-openclaw-deploy.md
    # "Migration from pickleclaw" > "What carries over".
    GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY_FILE -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
        git clone "$WORKSPACE_REPO_URL" "$DATA_DIR/workspace"
    echo "    Cloned $WORKSPACE_REPO_URL"
elif [ -d "$DATA_DIR/workspace/.git" ]; then
    echo "    Workspace already cloned, leaving it alone (ongoing sync is a manual git pull/push in-place)"
else
    echo "    Skipping clone (no deploy key)"
fi

cd "$SERVICE_DIR"

# docker compose auto-loads .env for interpolation inside compose files, but this
# script's own shell logic below (OPENCLAW_ALLOWED_CHAT_IDS) needs it exported too.
set -a
source "$SERVICE_DIR/.env"
set +a

echo "==> Pulling image"
$COMPOSE pull

echo "==> Onboarding (first deploy only)"
# OPENCLAW_SKIP_ONBOARDING does NOT mean "boot from a mounted file instead" — even with
# it set, setup still runs `config set` against an *existing* config. Onboard must
# actually run once to create the writable root config, auth store, and gateway token.
# Gated on the root config file so redeploys don't re-onboard an already-live service.
if [ ! -f "$DATA_DIR/config/openclaw.json" ]; then
    # --non-interactive requires --accept-risk (the "agents are powerful, full
    # system access is risky" prompt) -- deploy.sh runs over non-interactive ssh,
    # so there's no TTY to answer it and it would otherwise hang forever.
    # --skip-health: this onboard runs as a one-off `docker compose run` before the
    # real gateway is up (`compose up -d` happens below), so the built-in "wait for
    # an already-running gateway" health check has nothing to reach and errors out
    # (non-interactive mode won't fall back to starting one without --install-daemon,
    # which we don't want here -- systemd owns the long-lived container).
    # Verified against the same CLI version in a throwaway --dev profile.
    $RUN_CLI onboard --mode local --no-install-daemon --non-interactive --accept-risk \
        --gateway-auth token --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN \
        --skip-ui --suppress-gateway-token-output --skip-health

    echo "==> Setting $include-owned + first-boot-only keys (onboard only, see below)"
    # Bundled into the one-time onboarding step, NOT the self-healing config-set below:
    # - channels.telegram.enabled: once the Telegram bot cutover (README) flips this
    #   to true, a redeploy re-running this key would silently take the live bot
    #   back offline.
    # - tools/mcp $include pointers: setting an object value at a path that's
    #   ALREADY $include-owned errors with "Config write would flatten $include-owned
    #   config" (confirmed live on the second real deploy) -- the design doc's known
    #   gotcha ("$include is now exercised hands-on" section) bites the moment you
    #   retrofit an $include onto an already-configured section, which is exactly
    #   what re-running this every deploy would do after the first one sets it. The
    #   pointer only needs setting once; content changes flow through the include
    #   file itself (redeployed via scp), not through re-running config set.
    $RUN_CLI config set --batch-json '[
        {"path":"channels.telegram.enabled","value":false},
        {"path":"tools","value":{"$include":"./includes/tools.json5"}},
        {"path":"mcp","value":{"$include":"./includes/mcp.json5"}}
    ]'
else
    echo "    Root config already exists, skipping onboard"
fi

echo "==> Applying declarative config (model chain, channel policy, hardening)"
# Re-run on every deploy so config drift self-heals from these plain scalar/array
# values. Excludes channels.telegram.enabled and the tools/mcp $include pointers
# on purpose — see the onboarding step above.
# OPENCLAW_ALLOWED_CHAT_IDS is comma-separated (README/.env.template); turn it into
# a proper JSON array of strings rather than one string containing commas.
ALLOW_FROM_JSON=$(echo "${OPENCLAW_ALLOWED_CHAT_IDS:?required}" | tr ',' '\n' | jq -R . | jq -sc .)
# gateway.bind=lan is non-loopback, which `openclaw security audit` flags twice if
# left at defaults: Control UI needs an explicit origin allowlist (else it falls
# back to trusting the Host header), and auth needs a rate limit (else brute-force
# attempts on the gateway token aren't mitigated). Found live via the first real
# `just openclaw-status` run, not anticipated in the original design doc.
$RUN_CLI config set --batch-json '[
    {"path":"gateway.bind","value":"lan"},
    {"path":"gateway.controlUi.allowedOrigins","value":["https://'"${OPENCLAW_HOST:?required}"'"]},
    {"path":"gateway.auth.rateLimit","value":{"maxAttempts":10,"windowMs":60000,"lockoutMs":300000}},
    {"path":"channels.telegram.dmPolicy","value":"allowlist"},
    {"path":"channels.telegram.allowFrom","value":'"$ALLOW_FROM_JSON"'},
    {"path":"agents.defaults.model.primary","value":"ollama-cloud/glm-5.2"},
    {"path":"agents.defaults.model.fallbacks","value":["ollama-cloud/glm-4.7"]},
    {"path":"agents.defaults.heartbeat.model","value":"ollama-cloud/gpt-oss:20b"},
    {"path":"agents.defaults.heartbeat.isolatedSession","value":true},
    {"path":"agents.defaults.heartbeat.lightContext","value":true},
    {"path":"agents.defaults.models","value":{
        "ollama-cloud/glm-5.2":{},
        "ollama-cloud/glm-4.7":{},
        "ollama-cloud/gpt-oss:20b":{}
    }}
]'

echo "==> Doctor (catches config-schema migrations after an image bump)"
$RUN_CLI doctor || echo "    WARNING: doctor reported an issue — check output above"

echo "==> Configuring Tailscale serve for openclaw"
sudo tailscale serve --service=svc:openclaw --https=443 http://127.0.0.1:18789

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/openclaw.service" /etc/systemd/system/

echo "==> Reloading systemd and starting service"
# Bring the container up THROUGH systemd (systemctl restart runs the unit's
# ExecStart = compose up -d), not with a direct `compose up -d` call -- otherwise
# the container runs fine but systemd never learns about it and shows the unit as
# inactive/dead despite a healthy container (RemainAfterExit only tracks state
# systemd itself started). Same pattern as every other service's deploy.sh
# (taskchampion-sync, woodpecker, second-brain-agent, brineworks-agent).
sudo systemctl daemon-reload
sudo systemctl enable openclaw.service
sudo systemctl restart openclaw.service

echo "==> Status"
systemctl status openclaw.service --no-pager || true

echo ""
echo "==> Checking local health endpoint"
for i in 1 2 3 4 5; do
    if curl -fsS http://127.0.0.1:18789/healthz -o /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 5 ]; then
        echo "    WARNING: local health check failed after 5 attempts"
        echo "    Logs: $COMPOSE logs"
        exit 1
    fi
    echo "    Waiting for the gateway to start (attempt $i/5)..."
    sleep 3
done

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
OPENCLAW_URL="https://openclaw.${TAILNET}"

echo ""
echo "==> Checking Tailscale endpoint"
if curl -fsS "${OPENCLAW_URL}/healthz" -o /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! OpenClaw is reachable at ${OPENCLAW_URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${OPENCLAW_URL}"
    echo ""
    echo "    If this is the first deploy, the Service likely doesn't exist yet --"
    echo "    tailscale serve has nothing to attach a pending-host-approval to"
    echo "    until it's defined (same gotcha taskchampion-sync hit):"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Click 'Define Service': Name 'openclaw', Ports '443'"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect a newly-defined service):"
    echo "       sudo tailscale serve --service=svc:openclaw --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:openclaw --https=443 http://127.0.0.1:18789"
    echo "    4. Find 'openclaw' at https://login.tailscale.com/admin/services and approve the pending host"
    echo "    5. Verify: curl ${OPENCLAW_URL}/healthz"
fi
echo "Telegram channel is disabled until the cutover — see README 'Telegram bot cutover'."
echo "Run 'just openclaw-status' for the full self-test (systemd + tailscale + security audit)."
