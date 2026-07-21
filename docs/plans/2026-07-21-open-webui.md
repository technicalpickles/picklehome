# Open WebUI on picklelab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy [Open WebUI](https://openwebui.com/) as a homelab service on picklelab, reachable at `https://openwebui.<tailnet>.ts.net` via Tailscale Services, with login auth (single admin from 1Password) and Ollama Cloud as the only model provider.

**Architecture:** Standard picklehome homelab-service shape (modeled on `taskchampion-sync` and `openclaw`): pinned upstream Docker image wrapped in a one-line custom Dockerfile (non-root fix, see Global Constraints), container bound to `127.0.0.1:8090`, host `tailscaled` terminates HTTPS via `tailscale serve --service=svc:openwebui`, systemd oneshot unit builds and owns the compose lifecycle, data in `/srv/data/open-webui` (auto-picked-up by the nightly restic backup), secrets flow 1Password → `.env.template` → `just dotenv` → `scripts/service-env` filtered `.env` scp'd to the host.

**Tech Stack:** Docker Compose, systemd, Tailscale Services, 1Password CLI, Open WebUI `ghcr.io/open-webui/open-webui:v0.10.2` (wrapped in a one-line custom Dockerfile), Ollama Cloud (`https://ollama.com`, bearer API key).

## Global Constraints

- Image pinned to `ghcr.io/open-webui/open-webui:v0.10.2` (latest release as of 2026-07-21). Bump deliberately, not via `:latest`.
- Container runs non-root as `1000:1000` per the "Container user model" invariant in `homelab/services/README.md`. **Verified against the pinned tag, not just assumed:** the official Dockerfile's own comment says "Override at your own risk — non-root configurations are untested", and that's accurate — running the stock `v0.10.2` image as any non-root UID fails ~19 writes to `/app/backend/open_webui/static` on every boot with `Permission denied` (that dir ships `root:root`, `0755`/`0644`, no group write; the backend rewrites its bundled favicons/manifest/loader there at startup). Tracked upstream at [open-webui/open-webui#26662](https://github.com/open-webui/open-webui/issues/26662); fix PR [#26664](https://github.com/open-webui/open-webui/pull/26664) is open, not merged, as of this tag. Cosmetic (the UI still loads from the pre-existing files) but noisy and blocks custom static overrides — worked around with a one-line custom Dockerfile that chowns that dir at build time (see `service-scaffold`), not by running the stock image as non-root or giving up and running as root. Drop the wrapper Dockerfile once the fix ships and the pin is bumped past it.
- `HOME=/app/backend/data` (all model/embedding caches already point there) and `WEBUI_SECRET_KEY` is always set (avoids a separate root-owned `/app/backend/.webui_secret_key` write path in `start.sh`).
- Loopback port `8090` (host) → `8080` (container). 8000/9080/18789 are taken by other services.
- Auth decision (confirmed with Josh): single admin bootstrapped headlessly via `WEBUI_ADMIN_EMAIL`/`WEBUI_ADMIN_PASSWORD`, `ENABLE_SIGNUP=false`.
- Config-management decision (confirmed with Josh): env vars seed first boot, then the admin UI owns config (`ENABLE_PERSISTENT_CONFIG` stays default `true`). Consequence: after first boot, changing a `ConfigVar` (e.g. the Ollama key) in `.env` has no effect; change it in Admin Settings → Connections instead.
- Ollama Cloud connection: `OLLAMA_BASE_URLS=https://ollama.com` + `OLLAMA_API_CONFIGS={"0": {"key": "<OLLAMA_API_KEY>"}}`. Verified in Open WebUI source: the per-connection `key` is sent as `Authorization: Bearer` on `/api/tags`, `/api/chat`, etc. Reuses the existing `OLLAMA_API_KEY` already in `.env.template` (same key openclaw uses for Ollama Cloud).
- `ENABLE_OPENAI_API=false`: Ollama Cloud is the only provider.
- No pytest coverage: this is compose/shell/infra, verified by `docker compose config`, `bash -n`, and live health checks (repo tests only cover Python modules).
- Sandbox: `op` commands, `just dotenv`, and anything that SSHes to picklelab must run with the Claude Code sandbox disabled (1Password socket and raw SSH are both blocked in-sandbox).
- Never commit secrets. `.env` files stay gitignored; only `.env.template` references land in git.

## Interfaces shared across tasks

- Repo-internal naming: `open-webui` everywhere (directory, systemd unit, compose service name, `.env.vars`, just recipes, data dir) — matches the upstream project's GitHub org/repo/image slug (`open-webui/open-webui`). Tailscale-facing naming is shorter: `openwebui` (no hyphen) for both the Tailscale Service name (`svc:openwebui`) and the hostname (`openwebui.<tailnet>.ts.net`) — matches the upstream project's own domain, `openwebui.com`, and follows the same directory-vs-hostname split as `taskchampion-sync` (dir) → `taskchampion` (hostname).
- Master `.env` var names (namespaced per repo convention, mapped to Open WebUI's `WEBUI_*` names inside compose): `OPEN_WEBUI_HOST`, `OPEN_WEBUI_ADMIN_EMAIL`, `OPEN_WEBUI_ADMIN_PASSWORD`, `OPEN_WEBUI_SECRET_KEY`, plus existing `OLLAMA_API_KEY`.
- 1Password item: `Open WebUI` in the `picklehome` vault, fields `host`, `admin_email`, `admin_password`, `secret_key`.
- Health endpoint: `GET /health` (unauthenticated, returns `{"status":true}`).

---

### onepassword-item

**Files:**
- Modify: `.env.template` (append after the OpenClaw block at the end)

**Interfaces:**
- Produces: 1Password item `Open WebUI` and the four `OPEN_WEBUI_*` vars in the master `.env`, consumed by `service-scaffold` and the deploy recipe.

- [ ] **Step 1: Confirm the tailnet suffix** (sandbox disabled)

Run: `tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix'`
Expected: `tail2023b7.ts.net` (use whatever it actually prints in the next step)

- [ ] **Step 2: Create the 1Password item** (sandbox disabled)

```bash
op item create --category Login --vault picklehome --title "Open WebUI" \
  "host[text]=openwebui.tail2023b7.ts.net" \
  "admin_email[text]=joshua.nichols@gmail.com" \
  "admin_password[password]=$(openssl rand -base64 24)" \
  "secret_key[password]=$(openssl rand -base64 32)"
```

Verify field labels have no stray whitespace (a leading space silently drops the field from `.env`):

```bash
op item get "Open WebUI" --vault picklehome --format json | jq '[.fields[] | {label, id}]'
```

Expected: labels exactly `host`, `admin_email`, `admin_password`, `secret_key`.

- [ ] **Step 3: Append the block to `.env.template`**

```bash
# Open WebUI (1Password item: Open WebUI, picklehome vault). Chat UI on picklelab
# backed by Ollama Cloud; reuses OLLAMA_API_KEY above. Single admin bootstrapped
# headlessly, signup disabled. See homelab/services/open-webui/README.md.
OPEN_WEBUI_HOST={{ op://picklehome/Open WebUI/host }}
OPEN_WEBUI_ADMIN_EMAIL={{ op://picklehome/Open WebUI/admin_email }}
OPEN_WEBUI_ADMIN_PASSWORD={{ op://picklehome/Open WebUI/admin_password }}
OPEN_WEBUI_SECRET_KEY={{ op://picklehome/Open WebUI/secret_key }}
```

- [ ] **Step 4: Regenerate `.env` and verify** (sandbox disabled)

Run: `just dotenv && grep -c '^OPEN_WEBUI_' .env`
Expected: `4`

- [ ] **Step 5: Commit**

```bash
git add .env.template
git commit -m "feat(open-webui): add 1Password-backed env vars for Open WebUI"
```

---

### service-scaffold

**Files:**
- Create: `homelab/services/open-webui/compose.yaml`
- Create: `homelab/services/open-webui/compose.picklelab.yaml`
- Create: `homelab/services/open-webui/Dockerfile`
- Create: `homelab/services/open-webui/open-webui.service`
- Create: `homelab/services/open-webui/.env.vars`
- Create: `homelab/services/open-webui/README.md`

**Interfaces:**
- Consumes: `OPEN_WEBUI_*` + `OLLAMA_API_KEY` env vars from `onepassword-item`.
- Produces: compose stack named `open-webui` (base image `open-webui:local`, built from `Dockerfile` via `compose.picklelab.yaml`'s `build:` stanza, same layering as `second-brain-agent`/`brineworks-agent`), container port `127.0.0.1:8090`, data at `/app/backend/data` (bind `/srv/data/open-webui` in prod), systemd unit `open-webui.service`. Consumed by `deploy-script` and `justfile-recipes`.

- [ ] **Step 1: Write `compose.yaml`**

```yaml
services:
  open-webui:
    image: open-webui:local
    restart: unless-stopped
    # Run as 1000 per the container user model (homelab/services/README.md).
    # The stock image ships root and is only tested that way -- Dockerfile
    # (this dir) wraps it with a build-time chown so non-root works cleanly.
    # See Global Constraints for why a bare `user:` override on the stock
    # image was rejected (upstream open-webui/open-webui#26662).
    user: "1000:1000"
    environment:
      # --- Ollama Cloud, the only model provider ---
      ENABLE_OLLAMA_API: "true"
      OLLAMA_BASE_URLS: "https://ollama.com"
      # Per-connection config keyed by index in OLLAMA_BASE_URLS; "key" is sent
      # as Authorization: Bearer. ConfigVar: seeds the DB on first boot only.
      OLLAMA_API_CONFIGS: '{"0": {"key": "${OLLAMA_API_KEY:?required}"}}'
      ENABLE_OPENAI_API: "false"
      # --- Auth: single admin, no signup ---
      WEBUI_ADMIN_EMAIL: ${OPEN_WEBUI_ADMIN_EMAIL:?required}
      WEBUI_ADMIN_PASSWORD: ${OPEN_WEBUI_ADMIN_PASSWORD:?required}
      ENABLE_SIGNUP: "false"
      # Pinned so JWT sessions survive container recreation; also avoids the
      # image's fallback write to root-owned /app/backend/.webui_secret_key.
      WEBUI_SECRET_KEY: ${OPEN_WEBUI_SECRET_KEY:?required}
      WEBUI_URL: "https://${OPEN_WEBUI_HOST:?required}"
      # --- Non-root housekeeping ---
      HOME: /app/backend/data
      # --- Telemetry off ---
      DO_NOT_TRACK: "true"
      SCARF_NO_ANALYTICS: "true"
      ANONYMIZED_TELEMETRY: "false"
    ports:
      - "127.0.0.1:8090:8080"
    volumes:
      - data:/app/backend/data
volumes:
  data:
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
# Wraps the pinned upstream image to fix a confirmed non-root permission bug:
# open-webui/open-webui#26662 (fix PR #26664 open, not merged, as of v0.10.2).
# The stock image ships /app/backend/open_webui/static owned root:root,
# 0755/0644 (no group write), and rewrites its own bundled static assets
# (favicons, site.webmanifest, loader.js, user.png) into that dir on every
# boot. Any UID other than 0 fails those writes with ~19 "Permission denied"
# errors per boot -- the UI still loads from the pre-existing files, but it's
# alarming log noise and blocks custom static/branding overrides. Chown once
# at build time instead of fighting it at runtime, or giving up and running
# as root (which the repo's container-user-model convention in
# homelab/services/README.md rules out for anything writing to /srv/data).
#
# Drop this file and switch compose.yaml back to pulling
# ghcr.io/open-webui/open-webui directly once the upstream fix ships and the
# pin is bumped past it.
FROM ghcr.io/open-webui/open-webui:v0.10.2
USER root
RUN chown -R 1000:1000 /app/backend/open_webui/static
USER 1000:1000
```

- [ ] **Step 3: Write `compose.picklelab.yaml`**

```yaml
services:
  open-webui:
    build:
      # Build context is the whole picklehome repo (Dockerfile lives inside
      # it); deploy.sh ensures /opt/homelab is fast-forwarded before this
      # runs. Same layering as second-brain-agent/brineworks-agent.
      context: /opt/homelab
      dockerfile: homelab/services/open-webui/Dockerfile
    volumes:
      - /srv/data/open-webui:/app/backend/data
volumes:
  data:
    name: open-webui_data_unused
```

- [ ] **Step 4: Write `open-webui.service`**

```ini
[Unit]
Description=Open WebUI
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/homelab/homelab/services/open-webui
ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml up -d --build
ExecStop=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml down

[Install]
WantedBy=multi-user.target
```

(`--build`, not `--pull always`: the image is built locally from `Dockerfile`, same as `second-brain-agent.service`/`brineworks-agent.service`. No `EnvironmentFile=.env.build` either: the port is hardcoded in compose like openclaw's, and the secrets `.env` sits beside the compose files so compose auto-loads it.)

- [ ] **Step 5: Write `.env.vars`**

```
OPEN_WEBUI_HOST
OPEN_WEBUI_ADMIN_EMAIL
OPEN_WEBUI_ADMIN_PASSWORD
OPEN_WEBUI_SECRET_KEY
OLLAMA_API_KEY
```

- [ ] **Step 6: Write `README.md`**

```markdown
# open-webui

[Open WebUI](https://openwebui.com/) chat interface, backed by Ollama Cloud
(`https://ollama.com`, bearer `OLLAMA_API_KEY`, same key openclaw uses). No local
models, no GPU use on picklelab.

## Access

`https://openwebui.<tailnet>.ts.net` (Tailscale Services, `svc:openwebui`,
loopback port 8090). Login: single admin account, credentials in the
`Open WebUI` item in the `picklehome` vault. Signup is disabled.

## Deploy

    just dotenv
    just deploy-open-webui

First deploy needs the one-time Tailscale Service definition + approval; the
deploy script prints the exact steps if the tailnet health check fails.

## Config management (read before touching .env values)

Env vars marked as ConfigVars (the Ollama connection, signup toggle, etc.) seed
Open WebUI's database on FIRST BOOT ONLY. After that the admin UI owns them and
the env value is ignored. To rotate the Ollama Cloud key or change connections:
Admin Settings -> Connections in the UI. `WEBUI_SECRET_KEY`,
`WEBUI_ADMIN_EMAIL`/`WEBUI_ADMIN_PASSWORD` are read from env at startup (the
admin pair only acts on a fresh, user-less database).

## Upgrades

Bump the pinned tag in the `FROM` line of `Dockerfile` (not `compose.yaml` --
the image is built locally, see "Non-root fix" below), commit,
`just deploy-open-webui`. Data (SQLite `webui.db`, uploads, embedding-model
cache) lives in `/srv/data/open-webui`, backed up nightly by the restic
`/srv/data` job.

## Non-root fix (custom Dockerfile)

The official image ships as root and its own Dockerfile says non-root is
untested. Confirmed on the pinned tag: running it as any non-root UID fails
~19 writes to `/app/backend/open_webui/static` on every boot (root:root,
0755/0644, no group write) -- cosmetic, but noisy and blocks static/branding
overrides. Tracked upstream: [open-webui/open-webui#26662](https://github.com/open-webui/open-webui/issues/26662),
fix PR [#26664](https://github.com/open-webui/open-webui/pull/26664) still
open. `Dockerfile` here wraps the pinned image and chowns that dir at build
time instead. `compose.yaml` points at `open-webui:local`; `compose.picklelab.yaml`
adds the `build:` stanza that produces it (same layering as
`second-brain-agent`/`brineworks-agent`), and `open-webui.service` runs
`docker compose up -d --build`, not `--pull always`.

Once the upstream fix ships and the pin is bumped past it: delete
`Dockerfile`, point `compose.yaml` back at `ghcr.io/open-webui/open-webui:<tag>`
directly, drop the `build:` stanza from `compose.picklelab.yaml`, and switch
`open-webui.service` back to `--pull always`.
```

- [ ] **Step 7: Validate compose interpolation locally**

```bash
cd homelab/services/open-webui
OLLAMA_API_KEY=x OPEN_WEBUI_ADMIN_EMAIL=x OPEN_WEBUI_ADMIN_PASSWORD=x \
OPEN_WEBUI_SECRET_KEY=x OPEN_WEBUI_HOST=x \
docker compose -f compose.yaml -f compose.picklelab.yaml config
cd -
```

Expected: rendered config, `OLLAMA_API_CONFIGS: '{"0": {"key": "x"}}'`, bind mount `/srv/data/open-webui`, `build.context: /opt/homelab` and `build.dockerfile: homelab/services/open-webui/Dockerfile`, no warnings about unset vars. (This renders the build config without needing `/opt/homelab` to exist locally -- `docker compose config` doesn't resolve the build context. The first real build happens on picklelab via `just deploy-open-webui`; don't skip the syntax read-through here in the meantime.)

- [ ] **Step 8: Commit**

```bash
git add homelab/services/open-webui/
git commit -m "feat(open-webui): add compose stack, systemd unit, and service docs"
```

---

### deploy-script

**Files:**
- Create: `homelab/services/open-webui/deploy.sh` (mode 755)

**Interfaces:**
- Consumes: the scaffold files, `/opt/homelab` checkout on picklelab, passwordless-sudo allowlist (mkdir/chown/tailscale/systemctl, same as every other service).
- Produces: idempotent on-host deploy entrypoint invoked by `just deploy-open-webui`.

- [ ] **Step 1: Write `deploy.sh`** (modeled on `taskchampion-sync/deploy.sh` + openclaw's chown/first-deploy messaging)

```bash
#!/usr/bin/env bash
# Deploy Open WebUI on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/open-webui"
DATA_DIR=/srv/data/open-webui
# Loopback port tailscaled proxies to; the container listens on 8080 internally.
PORT=8090
# See homelab/services/README.md "Container user model".
CONTAINER_UID=1000
CONTAINER_GID=1000

cd "$REPO_DIR"
echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Creating data directory"
sudo mkdir -p "$DATA_DIR"
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$DATA_DIR"

echo "==> Configuring Tailscale serve for openwebui"
sudo tailscale serve --service=svc:openwebui --https=443 "http://127.0.0.1:$PORT"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/open-webui.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable open-webui.service
sudo systemctl restart open-webui.service

echo "==> Status"
systemctl status open-webui.service --no-pager || true

echo ""
echo "==> Checking local health endpoint"
# 12 attempts x 5s: first boot runs DB migrations and downloads the default
# embedding model before /health responds.
for i in $(seq 1 12); do
    if curl -fsS "http://127.0.0.1:$PORT/health" -o /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 12 ]; then
        echo "    WARNING: local health check failed after 12 attempts"
        echo "    Logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for Open WebUI to start (attempt $i/12)..."
    sleep 5
done

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
URL="https://openwebui.${TAILNET}"

echo ""
echo "==> Checking Tailscale endpoint"
if curl -fsS "${URL}/health" -o /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! Open WebUI is reachable at ${URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${URL}"
    echo ""
    echo "    If this is the first deploy, the Service likely doesn't exist yet:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Click 'Define Service': Name 'openwebui', Ports '443'"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect a newly-defined service):"
    echo "       sudo tailscale serve --service=svc:openwebui --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:openwebui --https=443 http://127.0.0.1:$PORT"
    echo "    4. Find 'openwebui' at https://login.tailscale.com/admin/services and approve the pending host"
    echo "    5. Verify: curl ${URL}/health"
fi
```

- [ ] **Step 2: Syntax-check and set the executable bit**

Run: `bash -n homelab/services/open-webui/deploy.sh && chmod +x homelab/services/open-webui/deploy.sh`
Expected: no output, exit 0; `git status` shows the file as new with mode 100755 after `git add`.

- [ ] **Step 3: Commit**

```bash
git add homelab/services/open-webui/deploy.sh
git commit -m "feat(open-webui): add idempotent deploy script"
```

---

### justfile-recipes

**Files:**
- Modify: root `Justfile` (append a new section after the openclaw recipes, around line 626)

**Interfaces:**
- Consumes: `deploy.sh`, `.env.vars`, `scripts/service-env`, `OPEN_WEBUI_HOST` from `.env` (just has `set dotenv-load`).
- Produces: `just deploy-open-webui`, `just open-webui-status`, `just open-webui-logs`, `just open-webui-logs-follow`.

- [ ] **Step 1: Append the recipes** (deploy body copied verbatim from `deploy-taskchampion`, names/paths swapped)

```just
# Deploy Open WebUI to picklelab (idempotent: first setup or update)
deploy-open-webui host="picklelab":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -n "$(git status --porcelain)" ]; then
        echo "ERROR: uncommitted changes. Commit or stash first."
        exit 1
    fi
    BRANCH=$(git branch --show-current)
    if [ "$BRANCH" != "main" ]; then
        echo "ERROR: not on main (on $BRANCH). Switch to main first."
        exit 1
    fi
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Pushing to origin/main..."
        git push
    fi
    echo "Deploying commit $(git rev-parse --short HEAD) to {{host}}"
    echo "==> Pulling on {{host}}"
    ssh {{host}} "cd /opt/homelab && git pull"
    echo "==> Copying .env to {{host}}"
    mkdir -p tmp
    scripts/service-env homelab/services/open-webui/.env.vars > tmp/open-webui.env
    scp tmp/open-webui.env {{host}}:/opt/homelab/homelab/services/open-webui/.env
    rm tmp/open-webui.env
    ssh {{host}} "cd /opt/homelab && homelab/services/open-webui/deploy.sh"

# Status check for Open WebUI (systemd + loopback HTTP + tailscale routing)
open-webui-status host="picklelab":
    #!/usr/bin/env bash
    set -uo pipefail
    echo "==> systemd unit on {{host}}"
    ssh {{host}} "sudo systemctl status open-webui.service --no-pager" || true
    echo ""
    echo "==> loopback HTTP on {{host}}"
    ssh {{host}} "curl -fsS http://127.0.0.1:8090/health -w '\nHTTP %{http_code}  %{time_total}s\n'" || echo "loopback FAILED"
    echo ""
    echo "==> tailscale routing (from this machine)"
    if [ -z "${OPEN_WEBUI_HOST:-}" ]; then
        echo "OPEN_WEBUI_HOST not set (run 'just dotenv' first)"
    else
        curl -fsS "https://$OPEN_WEBUI_HOST/health" -w "\nHTTP %{http_code}  %{time_total}s\n" || echo "tailscale routing FAILED"
    fi

# Tail Open WebUI container logs
open-webui-logs host="picklelab" lines="50":
    ssh {{host}} "cd /opt/homelab/homelab/services/open-webui && docker compose -f compose.yaml -f compose.picklelab.yaml logs --tail={{lines}}"

# Follow Open WebUI container logs
open-webui-logs-follow host="picklelab":
    ssh -t {{host}} "cd /opt/homelab/homelab/services/open-webui && docker compose -f compose.yaml -f compose.picklelab.yaml logs -f"
```

- [ ] **Step 2: Verify no recipe was silently dropped**

Run: `just --list | grep open-webui`
Expected: all four recipes listed (`deploy-open-webui`, `open-webui-logs`, `open-webui-logs-follow`, `open-webui-status`).

- [ ] **Step 3: Commit**

```bash
git add Justfile
git commit -m "feat(open-webui): add deploy/status/logs just recipes"
```

---

### docs-registry

**Files:**
- Modify: `homelab/services/README.md` (registry entry before "## Planned services"; uid row in the "Current uid assignments" table around line 65)
- Modify: `CLAUDE.md` (row in the "Homelab Services" table)

- [ ] **Step 1: Add the registry entry to `homelab/services/README.md`** (after the openclaw entry, before `## Planned services`, matching the taskchampion-sync entry format)

```markdown
---

### open-webui

Open WebUI chat interface backed by Ollama Cloud. No local models; picklelab only hosts the UI and its database, inference happens at ollama.com.

| | |
|---|---|
| **Purpose** | Web chat UI over Ollama Cloud models, single admin login |
| **Compose** | `/opt/homelab/homelab/services/open-webui/` |
| **Data** | `/srv/data/open-webui/` (SQLite `webui.db`, uploads, embedding cache) |
| **Access** | `https://openwebui.<tailnet>.ts.net` (Tailscale Services `svc:openwebui`, port 8090 internally) |
| **Env vars** | `OPEN_WEBUI_HOST`, `OPEN_WEBUI_ADMIN_EMAIL`, `OPEN_WEBUI_ADMIN_PASSWORD`, `OPEN_WEBUI_SECRET_KEY`, `OLLAMA_API_KEY` |
| **Backup** | Yes, nightly (SQLite picked up by `/srv/data` restic job) |
| **Restart** | `restart: unless-stopped` |

Commands: `just deploy-open-webui`, `just open-webui-status`, `just open-webui-logs`, `just open-webui-logs-follow`

See [open-webui/README.md](open-webui/README.md) for config-management gotchas (ConfigVar seeding) and upgrade steps.
```

- [ ] **Step 2: Add the uid row** to the "Current uid assignments" table in the same file:

```markdown
| open-webui | 1000:1000 | `compose.yaml` `user: "1000:1000"` + custom `Dockerfile` chowning `/app/backend/open_webui/static` at build time (stock image untested non-root, see service README "Non-root fix") |
```

- [ ] **Step 3: Add the CLAUDE.md row** to the Homelab Services table (after the openclaw row):

```markdown
| open-webui | `homelab/services/open-webui/` | Open WebUI chat interface backed by Ollama Cloud | `just deploy-open-webui`, `just open-webui-status` |
```

- [ ] **Step 4: Commit**

```bash
git add homelab/services/README.md CLAUDE.md
git commit -m "docs(open-webui): register service in homelab registry and CLAUDE.md"
```

---

### first-deploy

Everything here runs with the sandbox disabled (SSH + browser).

- [ ] **Step 1: Deploy**

Run: `just deploy-open-webui`
Expected: recipe pushes main if needed, pulls on picklelab, scps the filtered `.env`, deploy.sh passes the LOCAL health check. First deploy builds the image on-host from `Dockerfile` (`docker compose up -d --build`) rather than pulling a pre-built one, so it's slower than other services' first deploy -- that's expected, not a hang. The TAILSCALE check will WARN on first deploy; that's also expected.

- [ ] **Step 2: One-time Tailscale Service definition + approval** (manual, in browser)

Follow the printed steps: define service `openwebui` (port 443) at https://login.tailscale.com/admin/services, approve the pending picklelab host, then re-advertise on picklelab:

```bash
ssh picklelab "sudo tailscale serve --service=svc:openwebui --https=443 off && sleep 2 && sudo tailscale serve --service=svc:openwebui --https=443 http://127.0.0.1:8090"
```

- [ ] **Step 3: Verify end-to-end**

Run: `just open-webui-status`
Expected: systemd `active`, loopback `HTTP 200`, tailscale `HTTP 200`.

Then in a browser at `https://openwebui.<tailnet>.ts.net`:
1. Log in with the admin credentials from the `Open WebUI` 1Password item (no signup link should be usable).
2. Model picker lists Ollama Cloud models (e.g. `glm-5.2`, `gpt-oss:120b`; whatever `https://ollama.com/api/tags` returns for the key).
3. Send a chat message and get a streamed response.

If the model list is empty: Admin Settings → Connections → verify the `https://ollama.com` Ollama connection shows the key and "verify connection" succeeds (remember: after first boot the DB owns this config, not the env var).

- [ ] **Step 4: Capture followups in taskwarrior** (if any surfaced during deploy)

```bash
task add project:picklehome.homelab.open-webui "<followup>"
```

---

### backup-readability

The nightly restic job backs up all of `/srv/data`, but runs as the `backup` user; files created by uid 1000 with restrictive modes would be skipped (restic exit 3). Same-day verification beats finding out a month later.

- [ ] **Step 1: After some use (admin login + one chat), check readability** (sandbox disabled)

```bash
# Note: `sudo -u backup ...` alone hits "a password is required" -- the
# NOPASSWD sudoers rule on picklelab is `(ALL) NOPASSWD: /usr/bin/sudo -u
# backup *`, which only matches when sudo itself is the command being run
# (i.e. double sudo), not a single `sudo -u backup`. Confirmed 2026-07-21.
ssh picklelab "cd / && sudo -n sudo -u backup test -r /srv/data/open-webui/webui.db && echo 'webui.db readable' || echo 'NOT readable'"
ssh picklelab "cd / && sudo -n sudo -u backup find /srv/data/open-webui -not -readable 2>&1"
```

Expected: `webui.db readable` and no unreadable paths.

- [ ] **Step 2: If anything is unreadable**, add a setfacl grant to `homelab/services/backup/deploy.sh` next to the existing grants (around line 48), commit, and `just deploy-backup`:

```bash
setfacl -R -m u:backup:rX /srv/data/open-webui
```

- [ ] **Step 3: Confirm the next nightly run** (or trigger one)

Run: `just backup-now && just backup-status`
Expected: the snapshot for `/srv/data` completes and includes `open-webui`'s data. **Do not
expect the overall run to exit clean** -- as of 2026-07-21, `backup.service` already exits
non-zero every night from unrelated, pre-existing unreadable files in `openclaw`,
`second-brain-agent`, `taskchampion-sync`, and `woodpecker` (tracked: taskwarrior task
a949871a, `picklehome.homelab.backup`). Check `journalctl -u backup.service` for `permission
denied` lines specifically mentioning `open-webui` paths -- there should be none. If there
are, that's a real new gap (unlike the tracked pre-existing one) and needs a `setfacl` grant
per Step 2.
