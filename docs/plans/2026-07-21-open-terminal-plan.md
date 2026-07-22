# Open Terminal for Open WebUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add [Open Terminal](https://docs.openwebui.com/features/open-terminal/) to the existing `open-webui` homelab service on picklelab, giving the chat AI a sandboxed shell/file/package environment it drives via tool calls, reachable at `http://open-terminal:8000` only from inside the `open-webui` Compose project.

**Architecture:** Bundle `open-terminal` as a second container inside `homelab/services/open-webui/` (same multi-container-per-service-dir shape as `woodpecker`), sharing the default Compose network with `open-webui` — no host port, no Tailscale Service. `open-webui` gets `TERMINAL_SERVER_CONNECTIONS` (a `ConfigVar`, first-boot-only, same caveat as the existing `OLLAMA_API_CONFIGS`) pointing at it.

**Tech Stack:** Docker Compose, systemd (existing `open-webui.service`, unchanged), 1Password CLI, `ghcr.io/open-webui/open-terminal:0.11.34` (pinned).

See `docs/plans/2026-07-21-open-terminal-design.md` for the full design rationale (why bundled, why no docker socket, why no egress restriction, why excluded from backup).

## Global Constraints

- Image pinned to `ghcr.io/open-webui/open-terminal:0.11.34` (latest release as of 2026-07-21). Bump deliberately, not via `:latest`.
- **No Docker socket mount.** The upstream image supports mounting `/var/run/docker.sock` for docker-in-docker workflows; we deliberately do not, since that would be a straightforward escape to picklelab's host Docker daemon. If docker-in-docker is ever needed, follow `woodpecker`'s Option D (rootless `dockerd` as a dedicated non-privileged user, `docs/plans/2026-06-18-woodpecker-ci-design.md` Section 4) — not a plain host-socket bind.
- **No egress restriction.** `OPEN_TERMINAL_ALLOWED_DOMAINS` stays unset. Full internet access via the Docker bridge + picklelab's normal default route; the container is not a Tailscale node and has no sidecar, so it cannot reach the tailnet or other services' containers regardless.
- **No package pre-seeding.** `OPEN_TERMINAL_PACKAGES`/`_PIP_PACKAGES`/`_NPM_PACKAGES` stay unset.
- Container uid: expected `1000:1000`. The image's Dockerfile runs `useradd -m -s /bin/bash user` with no explicit `--uid` on a Debian base, which defaults to `1000` (`login.defs` `UID_MIN`) — same expectation already confirmed for `woodpecker-server`'s equivalent image on this exact host (no userns-remap, 1:1 uid mapping; see `homelab/services/woodpecker/deploy.sh`). Verified live during the `first-deploy` task below via `docker top`; correct `deploy.sh` and this plan's assumption if it's ever wrong on a future image bump.
- That `user` account has **passwordless sudo to root inside its own container** (how it installs packages on demand) — the isolation boundary is the container, not that account. Don't be misled by "runs as non-root" into thinking it's equivalent to every other service's uid convention.
- `/srv/data/open-terminal` (the container's `/home/user`) is **excluded from the nightly restic backup**, same treatment as the existing `/srv/data/dev-home` exclude in `homelab/services/backup/backup.sh` — disposable AI scratch space, not source-of-truth data.
- Secrets flow: 1Password (`picklehome` vault) → `.env.template` → `just dotenv` → `scripts/service-env` filtered `.env` scp'd to the host — same flow as every other service, reusing the existing `open-webui` deploy/scp machinery (no new `.env.vars` file, just a new line in the existing one).
- No pytest coverage: this is compose/shell/infra, verified by `docker compose config`, `bash -n`, and live health checks (repo tests only cover Python modules).
- Sandbox: `op` commands, `just dotenv`, and anything that SSHes to picklelab must run with the Claude Code sandbox disabled (1Password socket and raw SSH are both blocked in-sandbox). `ghcr.io` is also not in the sandbox's network allowlist, so any local `docker pull`/`docker run` against the image must run with the sandbox disabled too, or be deferred to the live host (this plan defers all image-pulling to picklelab).
- Never commit secrets. `.env` files stay gitignored; only `.env.template` references land in git.

## Interfaces shared across tasks

- Repo-internal naming: `open-terminal` for the container/service name and the `.env` var prefix (`OPEN_TERMINAL_*`) — matches the upstream project's slug (`open-webui/open-terminal`), same convention as `open-webui`'s own naming decision.
- Master `.env` var: `OPEN_TERMINAL_API_KEY` (kept identical to the upstream container's own env var name, `OPEN_TERMINAL_API_KEY` — no repo-side rename needed since there's no `WEBUI_*`-style upstream name to translate, unlike `open-webui`).
- 1Password item: `Open Terminal` in the `picklehome` vault, single field `api_key`.
- Compose service name: `open-terminal`. Internal URL from `open-webui`: `http://open-terminal:8000`.
- Health endpoint: `GET /health` on the container's internal port 8000 (unauthenticated, per upstream docs' `curl http://open-terminal:8000/health` example — not host-published, so checked via `docker compose exec`, not a bare `curl` from the host).

---

### onepassword-item

**Files:**
- Modify: `.env.template` (append after the existing Open WebUI block)

**Interfaces:**
- Produces: 1Password item `Open Terminal` and `OPEN_TERMINAL_API_KEY` in the master `.env`, consumed by `compose-scaffold` and the existing `deploy-open-webui` just recipe (via `scripts/service-env`).

- [ ] **Step 1: Create the 1Password item** (sandbox disabled)

```bash
op item create --category Login --vault picklehome --title "Open Terminal" \
  "api_key[password]=$(openssl rand -base64 32)"
```

- [ ] **Step 2: Verify the field label has no stray whitespace** (sandbox disabled)

```bash
op item get "Open Terminal" --vault picklehome --format json | jq '[.fields[] | {label, id}]'
```

Expected: one field with label exactly `api_key` (no leading/trailing space — a stray space silently drops the field from `.env` with no error).

- [ ] **Step 3: Append the block to `.env.template`**

```bash
# Open Terminal (1Password item: Open Terminal, picklehome vault). Sandboxed
# compute environment the Open WebUI chat AI drives via tool calls (shell,
# files, package installs). See homelab/services/open-webui/README.md
# "Open Terminal" section.
OPEN_TERMINAL_API_KEY={{ op://picklehome/Open Terminal/api_key }}
```

- [ ] **Step 4: Regenerate `.env` and verify** (sandbox disabled)

Run: `just dotenv && grep -c '^OPEN_TERMINAL_API_KEY=' .env`
Expected: `1`

- [ ] **Step 5: Commit**

```bash
git add .env.template
git commit -m "feat(open-webui): add 1Password-backed env var for Open Terminal"
```

---

### compose-scaffold

**Files:**
- Modify: `homelab/services/open-webui/compose.yaml`
- Modify: `homelab/services/open-webui/compose.picklelab.yaml`
- Modify: `homelab/services/open-webui/.env.vars`

**Interfaces:**
- Consumes: `OPEN_TERMINAL_API_KEY` from `onepassword-item`.
- Produces: `open-terminal` Compose service (image `ghcr.io/open-webui/open-terminal:0.11.34`, internal port 8000, volume `/home/user`), `open-webui`'s new `TERMINAL_SERVER_CONNECTIONS` env var. Consumed by `deploy-script-and-backup`, `justfile-status-update`, `first-deploy`.

- [ ] **Step 1: Modify `compose.yaml`** — add `depends_on` + `TERMINAL_SERVER_CONNECTIONS` to `open-webui`, and the new `open-terminal` service

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
    depends_on:
      - open-terminal
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
      # --- Open Terminal: sandboxed compute the chat AI drives via tool calls ---
      # ConfigVar: seeds the DB on first boot only, same caveat as OLLAMA_API_CONFIGS
      # above. URL is the Compose service name -- both containers share this
      # project's default network. See docs/plans/2026-07-21-open-terminal-design.md.
      TERMINAL_SERVER_CONNECTIONS: '[{"id": "open-terminal", "url": "http://open-terminal:8000", "key": "${OPEN_TERMINAL_API_KEY:?required}", "name": "Open Terminal", "auth_type": "bearer", "config": {"access_grants": []}}]'
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

  open-terminal:
    # Pinned like open-webui's own image; bump deliberately (see Global Constraints).
    image: ghcr.io/open-webui/open-terminal:0.11.34
    restart: unless-stopped
    environment:
      OPEN_TERMINAL_API_KEY: ${OPEN_TERMINAL_API_KEY:?required}
    # No `ports:` -- nothing outside this Compose project needs to reach it.
    # No docker.sock mount -- see Global Constraints.
    volumes:
      - open-terminal-data:/home/user

volumes:
  data:
  open-terminal-data:
```

- [ ] **Step 2: Modify `compose.picklelab.yaml`** — bind-mount the new volume, matching the existing `open-webui` pattern of renaming the now-orphaned base named volume

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

  open-terminal:
    volumes:
      - /srv/data/open-terminal:/home/user

volumes:
  data:
    name: open-webui_data_unused
  open-terminal-data:
    name: open-terminal_data_unused
```

- [ ] **Step 3: Add the var to `.env.vars`**

```
OPEN_WEBUI_HOST
OPEN_WEBUI_ADMIN_EMAIL
OPEN_WEBUI_ADMIN_PASSWORD
OPEN_WEBUI_SECRET_KEY
OLLAMA_API_KEY
OPEN_TERMINAL_API_KEY
```

- [ ] **Step 4: Validate compose interpolation locally**

```bash
cd homelab/services/open-webui
OLLAMA_API_KEY=x OPEN_WEBUI_ADMIN_EMAIL=x OPEN_WEBUI_ADMIN_PASSWORD=x \
OPEN_WEBUI_SECRET_KEY=x OPEN_WEBUI_HOST=x OPEN_TERMINAL_API_KEY=x \
docker compose -f compose.yaml -f compose.picklelab.yaml config
cd -
```

Expected: rendered config showing both services; `open-webui.depends_on: {open-terminal: {condition: service_started, ...}}`; `TERMINAL_SERVER_CONNECTIONS` rendered as a JSON string with `"key": "x"`; `open-terminal.image: ghcr.io/open-webui/open-terminal:0.11.34`; `open-terminal.volumes` bind-mounting `/srv/data/open-terminal`; no `docker.sock` anywhere; no warnings about unset vars.

- [ ] **Step 5: Commit**

```bash
git add homelab/services/open-webui/compose.yaml homelab/services/open-webui/compose.picklelab.yaml homelab/services/open-webui/.env.vars
git commit -m "feat(open-webui): add Open Terminal container"
```

---

### deploy-script-and-backup

**Files:**
- Modify: `homelab/services/open-webui/deploy.sh`
- Modify: `homelab/services/backup/backup.sh`

**Interfaces:**
- Consumes: `compose-scaffold`'s new `open-terminal` service.
- Produces: `/srv/data/open-terminal` created and chowned on deploy; a passing health check gates deploy success; the directory is excluded from the nightly restic snapshot.

- [ ] **Step 1: Add the Open Terminal data directory and uid handling to `deploy.sh`** — insert right after the existing `open-webui` data-directory block

```bash
echo "==> Creating Open Terminal data directory"
sudo mkdir -p "$OPEN_TERMINAL_DATA_DIR"
# The image's `user` account is uid 1000 (Debian `useradd -m` default, no
# explicit --uid; same expectation already confirmed for woodpecker-server's
# equivalent image on this host -- no userns-remap, 1:1 uid mapping). Verify
# with `docker top open-webui-open-terminal-1 -o uid` after first deploy; if
# it's ever different on a future image bump, update CONTAINER_UID here and
# re-chown (see homelab/services/CLAUDE.md "When changing a service's uid").
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$OPEN_TERMINAL_DATA_DIR"
```

- [ ] **Step 2: Add the new `DATA_DIR` variable** near the top of `deploy.sh`, alongside the existing `DATA_DIR`

```bash
DATA_DIR=/srv/data/open-webui
OPEN_TERMINAL_DATA_DIR=/srv/data/open-terminal
```

- [ ] **Step 3: Add an Open Terminal health check to `deploy.sh`** — insert after the existing "Checking local health endpoint" block for `open-webui`, before the "Checking Tailscale endpoint" section

```bash
echo ""
echo "==> Checking Open Terminal health"
COMPOSE="docker compose -f $SERVICE_DIR/compose.yaml -f $SERVICE_DIR/compose.picklelab.yaml"
for i in $(seq 1 12); do
    if $COMPOSE exec -T open-terminal curl -fsS http://localhost:8000/health -o /dev/null 2>&1; then
        echo "    Open Terminal health check passed"
        break
    fi
    if [ "$i" -eq 12 ]; then
        echo "    WARNING: Open Terminal health check failed after 12 attempts"
        echo "    Logs: $COMPOSE logs open-terminal"
        exit 1
    fi
    echo "    Waiting for Open Terminal to start (attempt $i/12)..."
    sleep 5
done
```

(Not host-published, so this uses `docker compose exec` rather than a bare `curl` against a loopback port -- consistent with the design decision not to publish a host port for it.)

- [ ] **Step 4: Syntax-check `deploy.sh`**

Run: `bash -n homelab/services/open-webui/deploy.sh`
Expected: no output, exit 0.

- [ ] **Step 5: Add the backup exclude to `backup.sh`**

```bash
# Exclude /srv/data/dev-home: that's the dev container's home directory,
# unrelated to homelab services. Has its own backup concerns.
#
# Exclude /srv/data/open-terminal: Open Terminal's scratch home directory for
# the chat AI's sandboxed shell sessions. Disposable AI-experiment data, not
# source of truth -- anything worth keeping gets moved to a real vault/repo/
# service during the session. See docs/plans/2026-07-21-open-terminal-design.md.
echo "==> Running restic backup"
restic backup "$DATA_DIR" --tag "$BACKUP_TAG" --verbose \
    --exclude "$DATA_DIR/dev-home" \
    --exclude "$DATA_DIR/open-terminal"
```

- [ ] **Step 6: Syntax-check `backup.sh`**

Run: `bash -n homelab/services/backup/backup.sh`
Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
git add homelab/services/open-webui/deploy.sh homelab/services/backup/backup.sh
git commit -m "feat(open-webui): deploy Open Terminal data dir and health check; exclude it from backup"
```

---

### justfile-status-update

**Files:**
- Modify: root `Justfile` (the `open-webui-status` recipe)

**Interfaces:**
- Consumes: the `open-terminal` service from `compose-scaffold`.
- Produces: `just open-webui-status` also reports Open Terminal's health (existing `just open-webui-logs`/`open-webui-logs-follow` already cover it for free, since `docker compose ... logs` includes every service in the project).

- [ ] **Step 1: Extend the `open-webui-status` recipe** — add a block after the existing "tailscale routing" check

```just
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
    echo ""
    echo "==> Open Terminal (internal container, no host port)"
    ssh {{host}} "cd /opt/homelab/homelab/services/open-webui && docker compose -f compose.yaml -f compose.picklelab.yaml exec -T open-terminal curl -fsS http://localhost:8000/health -w '\nHTTP %{http_code}  %{time_total}s\n'" || echo "Open Terminal health check FAILED"
```

- [ ] **Step 2: Verify the recipe still parses**

Run: `just --list | grep open-webui-status`
Expected: `open-webui-status` listed (unchanged name, confirms the Justfile still parses after the edit).

- [ ] **Step 3: Commit**

```bash
git add Justfile
git commit -m "feat(open-webui): report Open Terminal health in open-webui-status"
```

---

### first-deploy

Everything here runs with the sandbox disabled (SSH + browser).

- [ ] **Step 1: Deploy**

Run: `just deploy-open-webui`
Expected: recipe pushes main if needed, pulls on picklelab, scps the filtered `.env` (now including `OPEN_TERMINAL_API_KEY`), `deploy.sh` creates `/srv/data/open-terminal`, both the `open-webui` and `open-terminal` health checks pass.

- [ ] **Step 2: Confirm the Open Terminal container's actual uid**

Run: `ssh picklelab "docker top open-webui-open-terminal-1 -o uid"`
Expected: `1000`. If it's a different value: update `CONTAINER_UID`/`CONTAINER_GID` usage for the `OPEN_TERMINAL_DATA_DIR` chown line in `deploy.sh` to the real value (introduce a separate `OPEN_TERMINAL_UID` var if it differs from `open-webui`'s own `1000`), re-run `sudo chown -R <uid>:<gid> /srv/data/open-terminal` on the host, and re-deploy. Note the actual value — the `docs-registry` task below needs it.

- [ ] **Step 3: Verify the connection in the Admin UI**

In a browser at `https://openwebui.<tailnet>.ts.net`: log in as admin, go to Settings → Integrations, scroll to the **Open Terminal** section (not "Tools"/"External Tools"). Expected: a connection named "Open Terminal" with a green "Connected" indicator, seeded automatically (no manual entry needed) — confirms the `TERMINAL_SERVER_CONNECTIONS` `ConfigVar` seeded correctly on first boot.

- [ ] **Step 4: Smoke-test the AI actually using it**

In a chat, click the terminal button (cloud icon) in the input area, select "Open Terminal" under System, then ask: "What operating system and Linux distribution are you running on? Also show me `id` output." Expected: the AI runs commands via the terminal tool (not a guess from training data) and reports back real output (e.g. Debian, `uid=1000(user) ...`).

- [ ] **Step 5: Capture followups in taskwarrior** (if any surfaced during deploy)

```bash
task add project:picklehome.homelab.open-webui "<followup>"
```

---

### docs-registry

**Files:**
- Modify: `homelab/services/open-webui/README.md`
- Modify: `homelab/services/README.md`

**Interfaces:**
- Consumes: the confirmed uid from `first-deploy` Step 2.

- [ ] **Step 1: Add an "Open Terminal" section to `homelab/services/open-webui/README.md`** — insert after the existing "Config management" section, before "Upgrades"

```markdown
## Open Terminal

[Open Terminal](https://docs.openwebui.com/features/open-terminal/) gives the
chat AI a sandboxed shell/file/package environment it drives via tool calls
— a second container (`open-terminal`, pinned
`ghcr.io/open-webui/open-terminal:0.11.34`) in this same Compose project,
reachable from `open-webui` at `http://open-terminal:8000` (no host port, no
Tailscale Service — nothing outside this Compose project needs to reach it).

The connection is pre-seeded via `TERMINAL_SERVER_CONNECTIONS` (a
`ConfigVar` — same first-boot-only caveat as the Ollama connection above).
To use it in a chat: click the terminal button (cloud icon) in the input
area and select "Open Terminal" under System.

Its data lives in `/srv/data/open-terminal` (the container's `/home/user`)
and is deliberately **excluded from the nightly restic backup** — it's
disposable AI scratch space, not source-of-truth data. The image's `user`
account has passwordless sudo *inside its own container* (that's how it
installs packages on demand); the isolation boundary is the container, not
that account — no Docker socket is mounted, so it cannot reach picklelab's
host Docker daemon.

Full rationale: `docs/plans/2026-07-21-open-terminal-design.md`.
```

- [ ] **Step 2: Update the `open-webui` registry entry in `homelab/services/README.md`** — replace the existing entry's `Data` and `Env vars` rows and add a sentence to the intro

```markdown
Open WebUI chat interface backed by Ollama Cloud, plus [Open Terminal](https://docs.openwebui.com/features/open-terminal/) for sandboxed AI shell access. No local models; picklelab only hosts the UI/terminal containers and the UI's database, inference happens at ollama.com.

| | |
|---|---|
| **Purpose** | Web chat UI over Ollama Cloud models, single admin login, plus a sandboxed terminal the AI can drive |
| **Compose** | `/opt/homelab/homelab/services/open-webui/` |
| **Data** | `/srv/data/open-webui/` (SQLite `webui.db`, uploads, embedding cache); `/srv/data/open-terminal/` (Open Terminal's scratch home dir, **excluded from backup**) |
| **Access** | `https://openwebui.<tailnet>.ts.net` (Tailscale Services `svc:openwebui`, port 8090 internally); Open Terminal is internal-only (`http://open-terminal:8000` inside the Compose network, no host port) |
| **Env vars** | `OPEN_WEBUI_HOST`, `OPEN_WEBUI_ADMIN_EMAIL`, `OPEN_WEBUI_ADMIN_PASSWORD`, `OPEN_WEBUI_SECRET_KEY`, `OLLAMA_API_KEY`, `OPEN_TERMINAL_API_KEY` |
| **Backup** | Yes for `open-webui` (SQLite picked up by `/srv/data` restic job); no for `open-terminal` (excluded, disposable scratch space) |
| **Restart** | `restart: unless-stopped` (both containers) |
```

- [ ] **Step 3: Add the uid row to the "Current uid assignments" table** in `homelab/services/README.md`, using the value confirmed in `first-deploy` Step 2

```markdown
| open-terminal | 1000:1000 | Image default (`useradd -m` on Debian base, no explicit uid); confirmed via `docker top` at first deploy, see `homelab/services/open-webui/deploy.sh` |
```

(If `first-deploy` Step 2 found a different uid, use that value here instead of `1000:1000`.)

- [ ] **Step 4: Commit**

```bash
git add homelab/services/open-webui/README.md homelab/services/README.md
git commit -m "docs(open-webui): document Open Terminal integration"
```
