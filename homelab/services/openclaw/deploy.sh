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
# config:      writable root config (openclaw.json), created by `onboard`, plus memory/sessions/credentials
# workspace:   agent's identity/memory repo (openclaw-workspace), cloned below
# auth:        OpenClaw's own auth-profile store
# bin:         drop-in CLIs, bind-mounted read-only to /opt/tools in-container
# ssh:         the workspace + pickleclaw deploy keys, written below
# gog-keyring: gog-mcp's OAuth token file keyring, bind-mounted into that service --
#              under $DATA_DIR (not a named volume) so it's covered by backup.sh
sudo mkdir -p "$DATA_DIR/config" "$DATA_DIR/workspace" "$DATA_DIR/auth" "$DATA_DIR/bin" "$DATA_DIR/ssh" "$DATA_DIR/gog-keyring"

echo "==> Fixing data directory ownership"
# Do this now, right after mkdir, not at the end: it makes $DATA_DIR owned by uid
# $CONTAINER_UID, which is also the deploy user's own uid on picklelab (both 1000)
# -- the host<->container volume-sharing invariant this service relies on. That
# lets the deploy-key write and workspace clone below run unprivileged (no sudo),
# same trick brineworks-agent uses: `tee`/git-as-root aren't in the narrow sudoers
# allowlist and would prompt for a password over non-interactive ssh.
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$DATA_DIR"

echo "==> Installing goplaces gateway-side visibility stub (idempotent)"
# Bundled goplaces skill's bin-presence gate is evaluated gateway-host-only (a
# Linux/Docker node's binary isn't visible to it -- see docs/setup-notes.md's
# "goplaces node" section in the pickleclaw repo). This stub satisfies that gate
# without ever holding the real binary or a real API key on the gateway itself;
# the real goplaces + real GOOGLE_PLACES_API_KEY live only in the goplaces-node
# container. Re-written on every deploy so it self-heals from drift, same as the
# declarative config-set step below.
cat > "$DATA_DIR/bin/goplaces" << 'STUB'
#!/usr/bin/env bash
echo "goplaces is node-only on this gateway -- retry via: exec host=node node=goplaces-node goplaces $*" >&2
exit 1
STUB
chmod +x "$DATA_DIR/bin/goplaces"

echo "==> Installing the workspace-repo deploy key (if provided)"
# The workspace (github.com/technicalpickles/openclaw-workspace) is cloned host-side,
# once, using a scoped write deploy key. It arrives base64-encoded in the filtered
# .env (single line, so service-env's line-based filter keeps it whole) and must land
# 0600: ssh refuses a private key with looser permissions. Same pattern as
# brineworks-agent's WORKSPACE_DEPLOY_KEY_B64, different var name (each service's
# deploy key is scoped to a different repo, so they can't share one .env key name).
ENV_FILE="$SERVICE_DIR/.env"

# Load .env HERE, not further down. docker compose auto-loads it for interpolation
# inside compose files, but this script's own shell logic needs it exported too --
# and some of that logic runs well before the "Pulling image" step. This used to be
# sourced at the compose step, ~37 lines *after* the workspace-git-auth block below
# tests `-n "${OPENCLAW_WORKSPACE_GITHUB_TOKEN:-}"`. That test therefore read an
# unset var on every single deploy, silently skipped writing the askpass helper and
# setting core.askPass, and printed "token not in .env" while the token sat right
# there in the file. Net effect: the in-container workspace-git-sync cron could not
# authenticate to GitHub ("could not read Username for 'https://github.com'"), so it
# failed 99 runs straight and the agent's memory went ~13 days with no backup, with
# nothing surfacing it. Found 2026-07-14. Keep this above the first consumer.
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# OPENCLAW_IMAGE (pinned image tag, not a secret) lives in the private pickleclaw
# repo (openclaw-config/openclaw.env), scp'd here by `just deploy-openclaw` the same
# way openclaw.tools.json5/openclaw.mcp.json5 are -- single source of truth shared
# with the dev VM, instead of an independently-set-by-hand picklelab-only pin.
IMAGE_ENV_FILE="$SERVICE_DIR/openclaw.image.env"
if [ -f "$IMAGE_ENV_FILE" ]; then
    set -a
    source "$IMAGE_ENV_FILE"
    set +a
else
    echo "ERROR: $IMAGE_ENV_FILE missing. Symlink it from the private pickleclaw repo"
    echo "       first -- see homelab/services/openclaw/README.md."
    exit 1
fi

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
    echo "    Workspace already cloned, leaving it alone (ongoing sync: workspace-git-sync cron job below)"
else
    echo "    Skipping clone (no deploy key)"
fi

echo "==> Installing the pickleclaw deploy key (if provided)"
# Read-only SSH deploy key for github.com/technicalpickles/pickleclaw -- used only to
# clone/pull gog-mcp's source (nodes/gog-mcp/), which lives in that private repo, not
# this one (unlike goplaces-node, which is open source and checked in here directly).
# See docs/superpowers/specs/2026-08-26-gog-mcp-picklelab-rollout-design.md in the
# pickleclaw repo.
PICKLECLAW_DEPLOY_KEY_FILE="$DATA_DIR/ssh/pickleclaw_deploy_key"
PICKLECLAW_KEY_B64=""
if [ -f "$ENV_FILE" ]; then
    PICKLECLAW_KEY_B64=$(grep -m1 '^OPENCLAW_PICKLECLAW_DEPLOY_KEY_B64=' "$ENV_FILE" | cut -d= -f2- || true)
fi
if [ -n "$PICKLECLAW_KEY_B64" ]; then
    ( umask 077; echo "$PICKLECLAW_KEY_B64" | base64 -d > "$PICKLECLAW_DEPLOY_KEY_FILE" )
    echo "    Wrote $PICKLECLAW_DEPLOY_KEY_FILE (0600)"
else
    echo "    WARNING: OPENCLAW_PICKLECLAW_DEPLOY_KEY_B64 not in $ENV_FILE."
    echo "    Can't clone/update pickleclaw, so gog-mcp won't build. Add the var to"
    echo "    .env.vars + .env.template (see README), re-run 'just dotenv', redeploy."
fi

echo "==> Cloning/updating pickleclaw (gog-mcp's build context)"
# Tracks main HEAD, not pinned to a commit -- every deploy rebuilds gog-mcp from
# whatever's on pickleclaw@main at deploy time, same as the workspace repo's ongoing
# sync above. See the design doc's "Deploy mechanics" section for why (no separate
# picklelab-specific pin/bump step to maintain).
PICKLECLAW_DIR=/opt/pickleclaw
if [ -f "$PICKLECLAW_DEPLOY_KEY_FILE" ]; then
    PICKLECLAW_GIT_SSH="ssh -i $PICKLECLAW_DEPLOY_KEY_FILE -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    if [ ! -d "$PICKLECLAW_DIR/.git" ]; then
        sudo mkdir -p "$PICKLECLAW_DIR"
        sudo chown "$(id -u):$(id -g)" "$PICKLECLAW_DIR"
        GIT_SSH_COMMAND="$PICKLECLAW_GIT_SSH" \
            git clone git@github.com:technicalpickles/pickleclaw.git "$PICKLECLAW_DIR"
        echo "    Cloned pickleclaw to $PICKLECLAW_DIR"
    else
        if GIT_SSH_COMMAND="$PICKLECLAW_GIT_SSH" git -C "$PICKLECLAW_DIR" pull --ff-only; then
            echo "    Updated pickleclaw at $PICKLECLAW_DIR to $(git -C "$PICKLECLAW_DIR" rev-parse --short HEAD)"
        else
            echo "    WARNING: pickleclaw pull failed (non-fast-forward, network issue, or dirty tree)."
            echo "    Continuing with the existing checkout at $(git -C "$PICKLECLAW_DIR" rev-parse --short HEAD) -- gog-mcp's build context may be stale."
        fi
    fi
else
    echo "    Skipping (no deploy key)"
fi

echo "==> Shipping workspace-git-sync.sh (idempotent)"
# Lands in the same $DATA_DIR/bin dir the goplaces stub uses above -- already
# bind-mounted read-only to /opt/tools in-container, no new mount needed.
if [ -f "$SERVICE_DIR/workspace-git-sync.sh" ]; then
    cp "$SERVICE_DIR/workspace-git-sync.sh" "$DATA_DIR/bin/workspace-git-sync.sh"
    chmod +x "$DATA_DIR/bin/workspace-git-sync.sh"
    echo "    Installed $DATA_DIR/bin/workspace-git-sync.sh (appears at /opt/tools/workspace-git-sync.sh in-container)"
else
    echo "    WARNING: $SERVICE_DIR/workspace-git-sync.sh missing -- symlink it from pickleclaw first (see README)."
fi

echo "==> Wiring workspace git auth for in-container sync (HTTPS + PAT)"
# See docs/plans/2026-07-04-workspace-git-sync-picklelab-rollout.md for why HTTPS+PAT
# instead of reusing the SSH deploy key above: node:24-bookworm-slim ships no ssh
# client, so SSH-based git auth is unreachable *inside* the container, which is
# where the workspace-git-sync cron job (registered near the end of this script,
# once the gateway is actually up) runs.
if [ -d "$DATA_DIR/workspace/.git" ] && [ -n "${OPENCLAW_WORKSPACE_GITHUB_TOKEN:-}" ]; then
    CURRENT_ORIGIN=$(git -C "$DATA_DIR/workspace" remote get-url origin)
    if [[ "$CURRENT_ORIGIN" == git@github.com:* ]]; then
        git -C "$DATA_DIR/workspace" remote set-url origin "https://github.com/technicalpickles/openclaw-workspace.git"
        echo "    Switched workspace origin remote to HTTPS"
    else
        echo "    Workspace origin already HTTPS, leaving it alone"
    fi
    # GIT_ASKPASS helper: git invokes this once for the username prompt, once for
    # the password prompt. Any non-empty username works with a PAT; the token
    # itself is the password. core.askPass is set to the *in-container* path
    # (/opt/tools/...) since only the in-container cron job ever needs it -- this
    # script itself doesn't fetch/pull from the host side.
    cat > "$DATA_DIR/bin/workspace-git-askpass.sh" << 'ASKPASS'
#!/usr/bin/env bash
case "$1" in
    Username*) echo "x-access-token" ;;
    Password*) echo "$OPENCLAW_WORKSPACE_GITHUB_TOKEN" ;;
esac
ASKPASS
    chmod +x "$DATA_DIR/bin/workspace-git-askpass.sh"
    git -C "$DATA_DIR/workspace" config core.askPass "/opt/tools/workspace-git-askpass.sh"
    # Commit identity, repo-local. Without it `git commit` dies with "Author identity
    # unknown" (exit 128) -- the container has no global git config and can't
    # auto-detect one ("got 'node@<container-id>.(none)'"), so the sync cron could
    # commit exactly nothing. This sat hidden behind the askpass bug above: the fetch
    # failed first, so the commit step was never reached. Both had to be fixed to get
    # a single successful sync. Mirrors the dev VM's convention (pickleclaw agent
    # <pickleclaw@localhost>), with the host name swapped so the two writers are
    # distinguishable in the log. Found 2026-07-15.
    git -C "$DATA_DIR/workspace" config user.name "picklelab agent"
    git -C "$DATA_DIR/workspace" config user.email "picklelab@localhost"
    echo "    Wrote workspace-git-askpass.sh, set core.askPass + commit identity"
elif [ -d "$DATA_DIR/workspace/.git" ]; then
    echo "    WARNING: OPENCLAW_WORKSPACE_GITHUB_TOKEN not in $ENV_FILE."
    echo "    Skipping git auth wiring -- the workspace-git-sync cron job would fail to"
    echo "    push/pull. Add the var to .env.vars + .env.template (see README), re-run"
    echo "    'just dotenv', redeploy."
else
    echo "    Skipping (workspace not cloned yet)"
fi

cd "$SERVICE_DIR"

# .env is already sourced (exported) up near ENV_FILE -- see the note there for why it
# has to happen before the workspace-git-auth block, not here.

echo "==> Pulling image"
$COMPOSE pull

# goplaces-node is the only service in this stack built from source rather than
# pulled -- 'pull' above skips build-only services, and 'up -d' won't rebuild an
# existing image on its own even if the Dockerfile changed, so it needs this
# explicit rebuild step to pick up Dockerfile/entrypoint edits.
echo "==> Building goplaces-node"
$COMPOSE build goplaces-node

if [ -d "$PICKLECLAW_DIR/nodes/gog-mcp" ]; then
    echo "==> Building gog-mcp"
    $COMPOSE build gog-mcp
else
    echo "==> Skipping gog-mcp build (no $PICKLECLAW_DIR/nodes/gog-mcp)"
fi

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
    # - mcp $include pointer: setting an object value at a path that's ALREADY
    #   $include-owned errors with "Config write would flatten $include-owned config"
    #   (confirmed live on the second real deploy) -- the design doc's known gotcha
    #   ("$include is now exercised hands-on" section) bites the moment you retrofit
    #   an $include onto an already-configured section, which is exactly what
    #   re-running this every deploy would do after the first one sets it. The
    #   pointer only needs setting once; content changes flow through the include
    #   file itself (redeployed via scp), not through re-running config set.
    #
    #   tools does NOT get the same $include treatment -- tried, hit a harder wall:
    #   once a path is $include-owned, ANY later write under it (even a different
    #   literal at tools.exec, which is meant to deliberately diverge from the dev
    #   VM's value) tries to rewrite the include file and fails hard, EBUSY, against
    #   a real read-only bind mount (confirmed live 2026-09-01, pickleclaw repo's
    #   docs/setup-notes.md "Dev VM wired to consume the real tools.json5/mcp.json5").
    #   tools.json5's shared fields are applied via `config patch` below instead --
    #   see that step's comment.
    $RUN_CLI config set --batch-json '[
        {"path":"channels.telegram.enabled","value":false},
        {"path":"mcp","value":{"$include":"./includes/mcp.json5"}}
    ]'
else
    echo "    Root config already exists, skipping onboard"
fi

# tools.json5's shared fields (profile/alsoAllow/sessions/web), applied via `config
# patch` rather than `$include` -- see the onboarding step's comment above for why.
# Re-run every deploy (unlike the onboard-only mcp $include, this has no live link to
# the file, so it needs to be re-applied whenever includes/tools.json5 changes -- a
# redeploy already scps a fresh copy of it, so this is that same self-healing
# guarantee, just via patch instead of $include). `config patch --stdin` merges
# recursively and parses JSON5 (comments and all) natively, so this reads the real
# file directly rather than hand-copying its fields into a batch-json array.
echo "==> Syncing tools.json5's shared fields (profile/alsoAllow/sessions/web)"
{ printf '{\n  tools: '; cat openclaw.tools.json5; printf '\n}\n'; } | $RUN_CLI config patch --stdin

# memory.search: without this, it defaults to provider "openai", which has no key
# in this deploy (only OLLAMA_API_KEY/OPENROUTER_API_KEY are wired) -- vector recall
# stays paused forever ("Provider: openai (requested: openai)" in `memory status`,
# 0/N files indexed). Same OpenRouter embedding model pickleclaw validated
# (docs/setup-notes.md in that repo), but apiKey reads OPENROUTER_API_KEY directly
# since it's already a plain env var here, not the exec-secretref trick pickleclaw
# needed to dedupe against its own auth store.
# Path is top-level memory.search, not agents.defaults.memorySearch -- the latter
# was removed from the OpenClaw config schema by 2026.8.1 (confirmed via `openclaw
# config set --dry-run` against the dev VM's 2026.8.1 container 2026-09-01, which
# fails closed with "Unrecognized key: memorySearch" under agents.defaults). Since
# this whole batch runs under `set -euo pipefail`, that one bad key would abort
# every deploy on an image that new.
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
#
# tools.exec stays full/off here (picklelab) on purpose, 2026-07-12 -- lives here
# as a plain value rather than inside openclaw.tools.json5's $include, because a
# single $include can't do a partial override (OpenClaw errors "would flatten
# $include-owned config" the moment you try to set a subpath under one), and
# picklelab's exec policy is meant to deliberately diverge from the dev VM's
# rather than track it. Plan: the dev VM soaks security="allowlist", ask="on-miss"
# first (curated seed file openclaw-config/exec-allowlist-seed.json, seeding
# script scripts/seed-exec-allowlist.sh, and the argPattern-guarded openclaw CLI
# entry are all proven there), then picklelab flips to match -- but that's
# deliberately deferred pending https://github.com/openclaw/openclaw/issues/104798
# (node-routed exec precheck resolves bare command names against an empty PATH,
# so a node's own allowlist can never satisfy it under gateway allowlist mode --
# would make every goplaces search prompt for approval). Flip tracked by
# taskwarrior 189ae39b. Design: docs/superpowers/specs/2026-07-11-exec-allowlist-
# hardening-design.md (pickleclaw repo). Do not flip this line until #104798 is
# fixed and re-verified on the dev VM -- and check the dev VM's own tools.exec
# value is actually on allowlist/on-miss before assuming a soak is underway.
#
# skills.entries.goplaces.enabled: most bundled skills ship disabled by default
# (this onboard's own baseline leaves ~40 of them off). The goplaces-node stub
# and env placeholder above only satisfy the skill's own bins/env visibility
# gate -- this is a separate, independent enable flag that gates it regardless.
# Discovered live on the first goplaces-node deploy (2026-07-09/10) -- see
# docs/setup-notes.md's "goplaces node" section in the pickleclaw repo.
#
# agents.defaults.imageModel.primary: the whole chat chain (glm-5.2, glm-4.7,
# gpt-oss:20b) is text-only -- `openclaw models list --provider ollama-cloud`
# prints an input column, and among our configured models only kimi-k2.7-code
# takes text+image. imageModel is what a text-only primary delegates image input
# to, and pdfModel defaults to it, so this one line is what lets the image and
# pdf tools actually run. Without it the pdf tool still registers (that's
# alsoAllow's job -- see openclaw.tools.json5) and then errors at call time with
# "No PDF model configured". kimi-k2.7-code is already in the models map below,
# so this dodges the model-registration trap (an unregistered model here would
# silently misfire -- see CLAUDE.md in the pickleclaw repo).
# Verified end-to-end on the dev VM 2026-07-14 (2026.6.11) against both a text
# PDF over https and an image-only PDF with no text layer. Prompted by the
# 2026-07-14 session where the bot couldn't read a Canva-exported menu PDF and
# answered from a different location's menu instead.
$RUN_CLI config set --batch-json '[
    {"path":"gateway.bind","value":"lan"},
    {"path":"gateway.controlUi.allowedOrigins","value":["https://'"${OPENCLAW_HOST:?required}"'"]},
    {"path":"gateway.auth.rateLimit","value":{"maxAttempts":10,"windowMs":60000,"lockoutMs":300000}},
    {"path":"tools.exec","value":{"security":"full","ask":"off"}},
    {"path":"channels.telegram.dmPolicy","value":"allowlist"},
    {"path":"channels.telegram.allowFrom","value":'"$ALLOW_FROM_JSON"'},
    {"path":"channels.telegram.execApprovals.enabled","value":true},
    {"path":"commands.ownerAllowFrom","value":'"$ALLOW_FROM_JSON"'},
    {"path":"skills.entries.goplaces.enabled","value":true},
    {"path":"agents.defaults.model.primary","value":"ollama-cloud/glm-5.2"},
    {"path":"agents.defaults.model.fallbacks","value":["ollama-cloud/glm-4.7"]},
    {"path":"agents.defaults.heartbeat.model","value":"ollama-cloud/gpt-oss:20b"},
    {"path":"agents.defaults.heartbeat.isolatedSession","value":true},
    {"path":"agents.defaults.heartbeat.lightContext","value":true},
    {"path":"agents.defaults.imageModel.primary","value":"ollama-cloud/kimi-k2.7-code"},
    {"path":"agents.defaults.models","value":{
        "ollama-cloud/glm-5.2":{},
        "ollama-cloud/glm-4.7":{},
        "ollama-cloud/gpt-oss:20b":{},
        "ollama-cloud/kimi-k2.7-code":{}
    }},
    {"path":"memory.search","value":{
        "provider":"openai-compatible",
        "model":"qwen/qwen3-embedding-8b",
        "remote":{
            "baseUrl":"https://openrouter.ai/api/v1/",
            "apiKey":{"source":"env","provider":"default","id":"OPENROUTER_API_KEY"}
        }
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
# 10 attempts, not 5: the port accepts-then-resets for a few seconds after Docker
# reports the container Started (loading plugins, initializing Telegram polling,
# etc. -- ~4s of startup log between "starting HTTP server" and "ready" alone) --
# observed "Recv failure: Connection reset by peer" fail the tighter 5x3s loop
# twice on real deploys even though the container came up healthy moments later.
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS http://127.0.0.1:18789/healthz -o /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "    WARNING: local health check failed after 10 attempts"
        echo "    Logs: $COMPOSE logs"
        exit 1
    fi
    echo "    Waiting for the gateway to start (attempt $i/10)..."
    sleep 3
done

echo "==> Registering workspace-git-sync cron job (idempotent)"
# Needs the live gateway (docker exec into the running container), not the
# pre-start $RUN_CLI one-off used for config/doctor above -- cron registration
# talks to the running scheduler, not just the shared state dir.
if [ -d "$DATA_DIR/workspace/.git" ] && [ -n "${OPENCLAW_WORKSPACE_GITHUB_TOKEN:-}" ]; then
    if docker exec openclaw-openclaw-1 openclaw cron list --json 2>/dev/null \
        | jq -e '.jobs[]? | select(.name == "workspace-git-sync")' > /dev/null 2>&1; then
        echo "    workspace-git-sync cron job already registered, leaving it alone"
    else
        docker exec openclaw-openclaw-1 openclaw cron add workspace-git-sync --every 1h \
            --command "/opt/tools/workspace-git-sync.sh" \
            --command-cwd "/home/node/.openclaw/workspace" \
            --no-deliver
        echo "    Registered workspace-git-sync (every 1h, no-deliver)"
    fi
else
    echo "    Skipping (needs the workspace cloned + OPENCLAW_WORKSPACE_GITHUB_TOKEN wired above)"
fi

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
