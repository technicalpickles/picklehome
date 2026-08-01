# Nikke Roster Scanner on picklelab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the nikke roster dashboard off the `pickled-coi` OrbStack VM and onto picklelab as a standard homelab service, reachable at `https://nikke.tail2023b7.ts.net` with a 6-hourly blablalink sync on a systemd timer.

**Architecture:** One image built from the `nikke-roster-scanner` repo, backing two Compose services (`serve` long-lived, `sync` invoked by a timer). Source is cloned to `/opt/nikke-roster-scanner` on the host and built there, same as `brineworks-server`. The container binds host loopback only; `tailscaled` terminates HTTPS via a Tailscale Service. Persistent data lives at `/srv/data/nikke/` so the nightly restic job picks it up.

**Tech Stack:** Docker Compose, systemd (one long-lived unit, one timer), Python 3.13 + uv, FastAPI + uvicorn, Playwright (chromium), SQLite, Tailscale Services.

See `docs/plans/2026-07-31-nikke-roster-scanner-design.md` for the design rationale (why picklelab over the VM, why Tailscale Services over a sidecar node, why the incus approach was abandoned).

## Global Constraints

- **Two repos.** The `Dockerfile` and `.dockerignore` land in `nikke-roster-scanner` (private, `git@github.com:technicalpickles/nikke-roster-scanner.git`). Everything else lands in `picklehome`. Commit them separately.
- **Container uid is `1000:1000`**, set via `user:` in `compose.yaml` and a matching `useradd -u 1000` in the Dockerfile, per the container user model in `homelab/services/README.md`. `deploy.sh` chowns `/srv/data/nikke` after `mkdir -p` and before `docker compose up`.
- **`NIKKE_PORT=8770`**, published to `127.0.0.1` only. Never bind `0.0.0.0`; the Tailscale Service is the only external path in.
- **Tailscale Service is `svc:nikke`**, giving `https://nikke.tail2023b7.ts.net`. Tailnet suffix verified live on 2026-07-31 via `dscacheutil -q host -a name joshs-macbook-air.tail2023b7.ts.net`.
- **`--db /data/roster.db` must be passed explicitly** to both `serve` and `sync`. The CLI's `--db` defaults to a working-directory-relative `roster.db` with no environment-variable override, so omitting it writes to a container-local file that vanishes on the next `run --rm`.
- **`NIKKE_SESSION_PATH=/data/.blablalink-session.json`** is set in the container environment. The CLI's `--session-path` defaults to `$NIKKE_SESSION_PATH`, then `~/.blablalink-session.json`.
- **`config/blablalink_character_assets.json`, `config/dex_overrides.yaml`, and `data/dex/characters.json` are all tracked in git** (verified with `git ls-files --error-unmatch`), so they ship inside the image. Only `roster.db` and `.blablalink-session.json` need the volume.
- **Playwright browsers install to `/ms-playwright`**, not the build user's home, via `PLAYWRIGHT_BROWSERS_PATH`. Installing as root into a root-owned home would leave them unreadable to uid 1000 at runtime.
- **picklelab is amd64.** The VM this is moving off was arm64. Nothing in the plan pins an architecture, but don't copy arm64 wheels or base-image tags from the old coi profile.
- **No secrets, and therefore no `.env.vars`.** nikke has no API keys or passwords; the blablalink session is a file on the volume, not an environment variable. An empty-but-present `.env.vars` was the original design, and it does not work: `scripts/service-env` builds its key list with `wanted=$(grep -v '^#' "$VARS_FILE" | ...)`, and a comment-only file makes both greps match nothing, so the command substitution exits 1 and takes the `set -euo pipefail` recipe down with it. Verified on 2026-08-01: comment-only input exits 1 with no output, a real `.env.vars` exits 0. So `deploy-nikke` skips the filtered-env step entirely. When nikke first needs a secret, add `.env.vars` **and** the scp block back together.
- **Sandbox:** anything that SSHes to picklelab, runs `op`, or runs `just dotenv` must run with the Claude Code sandbox disabled. `ssh picklelab` was unreachable from the Mac during planning on 2026-07-31 (exit 124, timeout); confirm connectivity before starting `first-deploy`.
- **Never commit secrets.** `.env` files stay gitignored; only `.env.template` references land in git.

## Interfaces shared across tasks

- Compose project directory on the host: `/opt/homelab/homelab/services/nikke/`.
- App source clone on the host: `/opt/nikke-roster-scanner` (cloned and fast-forwarded by `deploy.sh`).
- Image tag: `nikke:local`. Built by the `serve` service only; `sync` reuses it with `pull_policy: never`.
- Compose service names: `serve` and `sync`.
- Data directory: `/srv/data/nikke/`, mounted at `/data`, containing `roster.db` and `.blablalink-session.json`.
- `.env.build` (written by `deploy.sh`, gitignored) carries `NIKKE_GIT_SHA` and `NIKKE_PORT`. Loaded by both the systemd units (`EnvironmentFile=`) and the containers (`env_file:`). The unit path is what makes compose's strict `${NIKKE_PORT:?}` interpolation succeed under systemd's otherwise-empty environment.
- Mac-side checkout for login: `~/github.com/technicalpickles/nikke-roster-scanner`.
- Health check target: `GET /` on `127.0.0.1:8770`. The app has no `/health` endpoint (`src/nikke_scanner/web/app.py` defines `index` only), so a 200 on `/` is the liveness signal.

---

### dockerfile

Repo: **nikke-roster-scanner**

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

**Interfaces:**
- Produces: an image exposing the `nikke-scan` console script on `PATH`, running as uid 1000, with chromium available at `/ms-playwright`. Consumed by `compose-scaffold`.

- [ ] **Step 1: Write the `Dockerfile`**

```dockerfile
FROM python:3.13-slim

ARG GIT_SHA=unknown
ENV NIKKE_GIT_SHA=${GIT_SHA}

# uv, matching the repo's uv_build backend and uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /uvx /bin/

WORKDIR /app

# Dependency layer first so source edits don't invalidate the (slow) chromium install.
# README.md is required too: pyproject.toml's readme = "README.md" makes uv's
# build backend read it during `uv sync`. --no-install-project defers installing
# nikke-scanner itself (which needs src/) so this layer only changes when
# pyproject.toml/uv.lock/README.md change, not on every source edit.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

# Chromium plus its system libraries. PLAYWRIGHT_BROWSERS_PATH keeps the download
# out of root's home so uid 1000 can actually read it at runtime; a+rx makes that
# explicit rather than relying on umask. This sits before src/ is copied so
# source edits don't invalidate the (slow) chromium download. --no-sync: src/
# isn't present yet, and `uv run` re-syncing would try (and fail) to install
# the project itself; the deps-only venv from the previous layer already has
# the playwright package needed to run this CLI.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN uv run --no-sync playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

# Tracked runtime data: the asset manifest, dex overrides, and the dex cache.
# Only data/dex/ is tracked (see .gitignore); data/ also holds several GB of
# untracked local screen recordings that must never land in the image, so we
# copy the dex subdirectory explicitly rather than the whole data/ tree.
COPY src/ ./src/
COPY config/ ./config/
COPY data/dex/ ./data/dex/

# Now install the project itself; deps are already synced above, so this is fast.
RUN uv sync --locked --no-dev

RUN useradd -m -u 1000 -s /bin/bash nikke && chown -R 1000:1000 /app
USER 1000:1000

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8770
```

- [ ] **Step 2: Write `.dockerignore`**

Keep `config/` and `data/dex/` in; they are tracked and the app reads them at runtime.

```
.git
.venv
.venv-coi
.pytest_cache
__pycache__/
*.pyc
out/
scratch/
tests/
docs/
roster.db
.blablalink-session.json
.nikke-serve.log
.superpowers/
.claude/
.worktrees/
```

- [ ] **Step 3: Build it locally to verify**

Run from the Mac checkout, sandbox disabled (needs the network for the chromium download):

```bash
cd ~/github.com/technicalpickles/nikke-roster-scanner
docker build -t nikke:verify .
```

Expected: build succeeds. It will take several minutes on the chromium layer.

- [ ] **Step 4: Verify the entrypoint and chromium are reachable as uid 1000**

```bash
docker run --rm nikke:verify nikke-scan --help
docker run --rm nikke:verify sh -c 'ls /ms-playwright && id'
```

Expected: `nikke-scan --help` prints the subcommand list including `serve` and `blablalink`. The `ls` shows a `chromium-*` directory, and `id` reports `uid=1000`.

- [ ] **Step 5: Clean up the verify image**

```bash
docker rmi nikke:verify
```

- [ ] **Step 6: Commit**

```bash
cd ~/github.com/technicalpickles/nikke-roster-scanner
git add Dockerfile .dockerignore
git commit -m "feat: containerize for picklelab deployment

Single image backing both serve and the scheduled blablalink sync.
Chromium lands in /ms-playwright so uid 1000 can read it; config/ and
data/dex/ are tracked and ship in the image, so only roster.db and the
session file need a volume."
git push
```

---

### compose-scaffold

Repo: **picklehome**

**Files:**
- Create: `homelab/services/nikke/compose.yaml`
- Create: `homelab/services/nikke/compose.picklelab.yaml`

Deliberately **no** `.env.vars` — see Global Constraints for why an empty one breaks `deploy-nikke`.

**Interfaces:**
- Consumes: the `nikke:local` image from `dockerfile`.
- Produces: Compose services `serve` and `sync`, the `/srv/data/nikke:/data` mount, and the `127.0.0.1:8770` binding. Consumed by `systemd-units`, `deploy-script`, `justfile-recipes`, `first-deploy`.

- [ ] **Step 1: Write `compose.yaml`**

```yaml
services:
  serve:
    image: nikke:local
    restart: unless-stopped
    # uid must match /srv/data/nikke ownership; deploy.sh chowns to 1000:1000.
    # See homelab/services/README.md "Container user model".
    user: "1000:1000"
    environment:
      # The CLI's --session-path defaults to $NIKKE_SESSION_PATH.
      NIKKE_SESSION_PATH: /data/.blablalink-session.json
    # --db has no env-var equivalent and defaults to a cwd-relative roster.db,
    # so it must be passed explicitly or writes land in the container and vanish.
    command: >
      nikke-scan serve
      --host 0.0.0.0
      --port ${NIKKE_PORT:?set by deploy.sh}
      --db /data/roster.db

  sync:
    image: nikke:local
    user: "1000:1000"
    # Only `serve` carries a build stanza. Without this, `compose run sync` on a
    # host that has never built the image tries to pull nikke:local from a
    # registry that doesn't exist.
    pull_policy: never
    environment:
      NIKKE_SESSION_PATH: /data/.blablalink-session.json
    command: >
      nikke-scan blablalink sync
      --headless
      --db /data/roster.db
```

`serve` binds `0.0.0.0` inside the container, which is the container's own interfaces. Restricting exposure happens in the `ports:` line below, which publishes to host loopback only.

- [ ] **Step 2: Write `compose.picklelab.yaml`**

```yaml
services:
  serve:
    build:
      # deploy.sh clones/fast-forwards this checkout before the build runs.
      context: /opt/nikke-roster-scanner
      dockerfile: Dockerfile
      args:
        GIT_SHA: ${NIKKE_GIT_SHA:-unknown}
    env_file:
      - .env.build
    ports:
      # Loopback only. tailscale serve proxies from nikke.<tailnet>.ts.net.
      - "127.0.0.1:${NIKKE_PORT:?set by deploy.sh}:${NIKKE_PORT:?set by deploy.sh}"
    volumes:
      - /srv/data/nikke:/data

  sync:
    env_file:
      - .env.build
    volumes:
      - /srv/data/nikke:/data
```

- [ ] **Step 3: Verify the compose files parse**

`NIKKE_PORT` is normally supplied by `.env.build`, which doesn't exist yet, so provide it inline:

```bash
cd ~/github.com/technicalpickles/picklehome/homelab/services/nikke
NIKKE_PORT=8770 docker compose -f compose.yaml config >/dev/null && echo "base OK"
```

Expected: `base OK`. Do not run `config` against `compose.picklelab.yaml` locally; its build context `/opt/nikke-roster-scanner` only exists on picklelab.

- [ ] **Step 4: Commit**

```bash
cd ~/github.com/technicalpickles/picklehome
git add homelab/services/nikke/compose.yaml homelab/services/nikke/compose.picklelab.yaml
git commit -m "feat(nikke): compose scaffold for the roster dashboard"
```

---

### systemd-units

Repo: **picklehome**

**Files:**
- Create: `homelab/services/nikke/nikke.service`
- Create: `homelab/services/nikke/nikke-sync.service`
- Create: `homelab/services/nikke/nikke-sync.timer`

**Interfaces:**
- Consumes: the Compose services from `compose-scaffold`, `.env.build` from `deploy-script`.
- Produces: `nikke.service` (long-lived), `nikke-sync.service` + `nikke-sync.timer` (scheduled). Linked into `/etc/systemd/system/` by `deploy-script`.

- [ ] **Step 1: Write `nikke.service`**

Note `up -d --build serve`, naming the service explicitly. A bare `up -d` would also start `sync`, which would run a full blablalink sync on every deploy and every boot.

```ini
[Unit]
Description=Nikke roster dashboard (FastAPI + SQLite)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/homelab/homelab/services/nikke
# .env.build is written by deploy.sh and carries NIKKE_GIT_SHA and NIKKE_PORT
# into the docker compose process env, so compose's strict ${NIKKE_PORT:?...}
# interpolation succeeds when systemd starts this with an empty user env.
EnvironmentFile=-/opt/homelab/homelab/services/nikke/.env.build
ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml up -d --build serve
ExecStop=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml down

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write `nikke-sync.service`**

```ini
[Unit]
Description=Nikke blablalink roster sync
After=network-online.target docker.service nikke.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
# A warm sync took ~16s on the old setup; 15 minutes is slack for a cold
# container start plus a slow blablalink, not an expected duration.
TimeoutStartSec=900
WorkingDirectory=/opt/homelab/homelab/services/nikke
EnvironmentFile=-/opt/homelab/homelab/services/nikke/.env.build
ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml run --rm sync
```

- [ ] **Step 3: Write `nikke-sync.timer`**

```ini
[Unit]
Description=Run the nikke blablalink sync every 6 hours

[Timer]
OnCalendar=*-*-* 00/6:00:00
# picklelab reboots; without this a missed window is silently skipped.
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: Verify the units are syntactically valid**

```bash
cd ~/github.com/technicalpickles/picklehome/homelab/services/nikke
systemd-analyze verify ./nikke.service ./nikke-sync.service ./nikke-sync.timer 2>&1 | head
```

Expected: no output, or only warnings about units not being installed. If `systemd-analyze` is unavailable on the Mac, defer this check to `first-deploy` and run it on picklelab.

- [ ] **Step 5: Commit**

```bash
cd ~/github.com/technicalpickles/picklehome
git add homelab/services/nikke/nikke.service homelab/services/nikke/nikke-sync.service homelab/services/nikke/nikke-sync.timer
git commit -m "feat(nikke): systemd units for serve and the 6-hourly sync"
```

---

### deploy-script

Repo: **picklehome**

**Files:**
- Create: `homelab/services/nikke/deploy.sh` (mode 755)
- Modify: `.gitignore` (add the `.env.build` exclusion if not already covered)

**Interfaces:**
- Consumes: compose files from `compose-scaffold`, units from `systemd-units`.
- Produces: `/opt/nikke-roster-scanner` clone, `/srv/data/nikke` owned by 1000:1000, `.env.build`, the registered `svc:nikke` Tailscale Service, and enabled/started units. Consumed by `justfile-recipes` and `first-deploy`.

- [ ] **Step 1: Write `deploy.sh`**

```bash
#!/usr/bin/env bash
# Deploy the nikke roster dashboard on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/nikke"
DATA_DIR=/srv/data/nikke
NIKKE_REPO=/opt/nikke-roster-scanner
CONTAINER_UID=1000
CONTAINER_GID=1000

# Override by exporting NIKKE_PORT before running. Must match the port the
# Tailscale Service proxies to; both are set from this one value.
export NIKKE_PORT="${NIKKE_PORT:-8770}"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Updating nikke-roster-scanner source"
if [ -d "$NIKKE_REPO/.git" ]; then
    git -C "$NIKKE_REPO" pull --ff-only
else
    echo "    Cloning nikke-roster-scanner to $NIKKE_REPO"
    sudo mkdir -p "$NIKKE_REPO"
    sudo chown "$(id -u):$(id -g)" "$NIKKE_REPO"
    git clone git@github.com:technicalpickles/nikke-roster-scanner.git "$NIKKE_REPO"
fi
NIKKE_SHA=$(git -C "$NIKKE_REPO" rev-parse --short HEAD)
echo "    nikke-roster-scanner at $NIKKE_SHA"

echo "==> Writing build metadata"
{
    echo "NIKKE_GIT_SHA=$NIKKE_SHA"
    echo "NIKKE_PORT=$NIKKE_PORT"
} > "$SERVICE_DIR/.env.build"

echo "==> Creating data directory"
# roster.db and .blablalink-session.json live here. Chown before compose up so
# the container's uid 1000 can write; see homelab/services/README.md.
sudo mkdir -p "$DATA_DIR"
sudo chown -R "$CONTAINER_UID:$CONTAINER_GID" "$DATA_DIR"

echo "==> Configuring Tailscale serve for nikke"
# Registers nikke.<tailnet>.ts.net, proxied to localhost:$NIKKE_PORT.
# Idempotent: re-running updates the config in tailscaled's state.
# Requires HTTPS to be enabled in the Tailscale admin console.
sudo tailscale serve --service=svc:nikke --https=443 "http://127.0.0.1:$NIKKE_PORT"

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/nikke.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/nikke-sync.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/nikke-sync.timer" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable nikke.service
sudo systemctl restart nikke.service
sudo systemctl enable --now nikke-sync.timer

echo "==> Status"
systemctl status nikke.service --no-pager
systemctl list-timers nikke-sync.timer --no-pager

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
NIKKE_URL="https://nikke.${TAILNET}"

echo ""
echo "==> Checking local endpoint"
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sf "http://127.0.0.1:$NIKKE_PORT/" > /dev/null 2>&1; then
        echo "    Local check passed"
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "    WARNING: local check failed after 10 attempts"
        echo "    Check container logs:"
        echo "      cd $SERVICE_DIR && docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for serve to start (attempt $i/10)..."
    sleep 3
done

echo ""
echo "==> Checking Tailscale endpoint"
if curl -sf "${NIKKE_URL}/" > /dev/null 2>&1; then
    echo "    Tailscale check passed"
    echo ""
    echo "Done! Nikke roster available at ${NIKKE_URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${NIKKE_URL}"
    echo ""
    echo "    If this is the first deploy, you need to approve the service:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Find 'nikke' and approve the pending host"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect approval):"
    echo "       sudo tailscale serve --service=svc:nikke --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:nikke --https=443 http://127.0.0.1:\$NIKKE_PORT"
    echo "    4. Verify: curl ${NIKKE_URL}/"
fi
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x ~/github.com/technicalpickles/picklehome/homelab/services/nikke/deploy.sh
```

- [ ] **Step 3: Syntax-check it**

```bash
bash -n ~/github.com/technicalpickles/picklehome/homelab/services/nikke/deploy.sh && echo "syntax OK"
```

Expected: `syntax OK`.

- [ ] **Step 4: Confirm `.env.build` is gitignored**

```bash
cd ~/github.com/technicalpickles/picklehome
git check-ignore -v homelab/services/nikke/.env.build || echo "NOT IGNORED -- add it"
```

If it reports NOT IGNORED, append `.env.build` to `.gitignore` and re-run until it is ignored. It carries no secrets today, but it is deploy-time host state and shouldn't be committed.

- [ ] **Step 5: Commit**

```bash
cd ~/github.com/technicalpickles/picklehome
git add homelab/services/nikke/deploy.sh .gitignore
git commit -m "feat(nikke): deploy script with tailscale service registration"
```

---

### justfile-recipes

Repo: **picklehome**

**Files:**
- Modify: `Justfile` (append after the existing `deploy-open-webui` block)

**Interfaces:**
- Consumes: `deploy.sh` from `deploy-script`, the Compose service names from `compose-scaffold`.
- Produces: `just deploy-nikke`, `just nikke-logs`, `just nikke-logs-follow`, `just nikke-sync-now`, `just nikke-login`. Consumed by `first-deploy`, `data-migration`, `sync-verification`.

- [ ] **Step 1: Add the deploy and log recipes**

Matches the `deploy-brineworks-server` shape exactly, including the dirty-tree and branch guards.

```just
# Deploy the nikke roster dashboard to picklelab (idempotent: first setup or update)
deploy-nikke host="picklelab":
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
    # No .env scp: nikke has no secrets, so there is no .env.vars to filter.
    # scripts/service-env exits 1 on an empty/comment-only vars file, which
    # would kill this recipe. See the plan's Global Constraints. Add the
    # service-env + scp block back if nikke ever gains a secret.
    ssh {{host}} "cd /opt/homelab && homelab/services/nikke/deploy.sh"

# Tail nikke container logs from picklelab
nikke-logs host="picklelab" lines="50":
    ssh {{host}} "cd /opt/homelab/homelab/services/nikke && docker compose -f compose.yaml -f compose.picklelab.yaml logs --tail={{lines}}"

# Follow nikke container logs live from picklelab
nikke-logs-follow host="picklelab":
    ssh -t {{host}} "cd /opt/homelab/homelab/services/nikke && docker compose -f compose.yaml -f compose.picklelab.yaml logs -f"

# Run a blablalink sync right now instead of waiting for the timer
nikke-sync-now host="picklelab":
    ssh -t {{host}} "sudo systemctl start nikke-sync.service && journalctl -u nikke-sync.service -n 40 --no-pager"
```

- [ ] **Step 2: Add the login recipe**

Login needs a real browser, and picklelab is headless, so this runs on the Mac against the local checkout and uploads the resulting session. `--no-headless` forces a visible window; a throwaway `--db` keeps this from touching the Mac's own `roster.db`.

```just
# Refresh the blablalink session on the Mac (needs a browser) and upload it to picklelab.
# Run this when the dashboard's staleness banner reports auth_expired.
nikke-login host="picklelab" repo="~/github.com/technicalpickles/nikke-roster-scanner":
    #!/usr/bin/env bash
    set -euo pipefail
    REPO=$(eval echo {{repo}})
    SESSION="$REPO/.blablalink-session.json"
    echo "==> Opening a browser to log in to blablalink"
    echo "    Log in when the window appears; the session is cached on success."
    # The cd MUST stay scoped to this subshell. `just nikke-sync-now` at the end
    # of this recipe resolves its Justfile from cwd, and there is no Justfile in
    # the nikke checkout -- `just` isn't even on PATH there, since mise
    # provisions it per-project in picklehome. A bare `cd "$REPO"` makes this
    # recipe fail its own final verification step on every run.
    # trap, not a plain rm: set -e would otherwise skip cleanup on a failed login.
    trap 'rm -f /tmp/nikke-login-throwaway.db' EXIT
    ( cd "$REPO" && uv run nikke-scan blablalink sync \
        --no-headless \
        --session-path "$SESSION" \
        --db /tmp/nikke-login-throwaway.db )
    if [ ! -f "$SESSION" ]; then
        echo "ERROR: no session file at $SESSION -- login did not complete."
        exit 1
    fi
    echo "==> Uploading the session to {{host}}"
    scp "$SESSION" {{host}}:/tmp/.blablalink-session.json
    ssh {{host}} "sudo install -o 1000 -g 1000 -m 600 /tmp/.blablalink-session.json /srv/data/nikke/.blablalink-session.json && rm -f /tmp/.blablalink-session.json"
    echo "==> Verifying with a real sync"
    just nikke-sync-now {{host}}
```

- [ ] **Step 3: Verify just parses the new recipes**

```bash
cd ~/github.com/technicalpickles/picklehome
just --list 2>&1 | grep -E "nikke" | head
```

Expected: `deploy-nikke`, `nikke-logs`, `nikke-logs-follow`, `nikke-login`, `nikke-sync-now` all listed.

- [ ] **Step 4: Commit**

```bash
cd ~/github.com/technicalpickles/picklehome
git add Justfile
git commit -m "feat(nikke): just recipes for deploy, logs, sync, and login"
```

---

### first-deploy

Repo: **picklehome** (executed against picklelab)

**Files:** none changed. This task runs the deploy and fixes anything it surfaces.

**Interfaces:**
- Consumes: everything from `dockerfile` through `justfile-recipes`.
- Produces: a running `nikke.service` with an empty database, an approved `svc:nikke`. Consumed by `data-migration`.

Run every step with the sandbox disabled; they all SSH to picklelab.

- [ ] **Step 1: Confirm picklelab is reachable**

```bash
ssh -o ConnectTimeout=10 picklelab "hostname && docker --version && tailscale status --json | jq -r .CurrentTailnet.MagicDNSSuffix"
```

Expected: the hostname, a Docker version, and `tail2023b7.ts.net`. If this times out, stop and resolve connectivity before continuing; it timed out during planning on 2026-07-31.

- [ ] **Step 2: Merge the branch to main and deploy**

`deploy-nikke` refuses to run off main.

```bash
cd ~/github.com/technicalpickles/picklehome
git checkout main && git merge --no-ff nikke-on-picklelab
just dotenv
just deploy-nikke
```

Expected: the clone succeeds, the image builds (slow on the chromium layer), the local check passes, and the Tailscale check either passes or prints the approval instructions.

- [ ] **Step 3: Approve the Tailscale Service if prompted**

Only needed on the first deploy. tailscaled does not notice approval on its own, so the re-advertise is mandatory, not decorative.

1. Open `https://login.tailscale.com/admin/services`
2. Approve the pending `nikke` host
3. Re-advertise:

```bash
ssh picklelab "sudo tailscale serve --service=svc:nikke --https=443 off && sleep 2 && sudo tailscale serve --service=svc:nikke --https=443 http://127.0.0.1:8770"
```

- [ ] **Step 4: Verify the dashboard loads over the tailnet**

```bash
curl -sf -o /dev/null -w "HTTP %{http_code}\n" https://nikke.tail2023b7.ts.net/
```

Expected: `HTTP 200`. The page will show an empty roster; that's correct at this stage.

- [ ] **Step 5: Verify the container's uid and the volume are right**

```bash
ssh picklelab "docker inspect --format '{{.Config.User}}' \$(docker ps -qf name=nikke-serve) && ls -lan /srv/data/nikke"
```

Expected: `1000:1000`, and `/srv/data/nikke` owned by uid 1000. A `roster.db` should exist, created empty by serve.

- [ ] **Step 6: Verify the timer is armed and did not fire a sync yet**

```bash
ssh picklelab "systemctl list-timers nikke-sync.timer --no-pager && systemctl is-active nikke.service"
```

Expected: the timer lists a next elapse time, and `nikke.service` is `active`.

---

### data-migration

Repo: none. This moves live data from the VM to picklelab.

**Files:** none changed.

**Interfaces:**
- Consumes: the running service from `first-deploy`.
- Produces: the real 13MB `roster.db` and a valid `.blablalink-session.json` at `/srv/data/nikke/`. Consumed by `sync-verification`.

Sandbox disabled throughout.

- [ ] **Step 1: Record the source character count**

This is the number the migration has to preserve.

```bash
orb -m pickled-coi bash -lc 'cd ~/projects/nikke-roster-scanner && sqlite3 roster.db "select count(*) from characters;"'
```

Write the number down. It was 184 on the last recorded sync.

- [ ] **Step 2: Take a consistent copy**

`.backup` rather than `cp`, so the copy is valid even if something is mid-write.

```bash
orb -m pickled-coi bash -lc 'cd ~/projects/nikke-roster-scanner && sqlite3 roster.db ".backup /tmp/roster-migrate.db" && ls -la /tmp/roster-migrate.db'
```

- [ ] **Step 3: Pull both files to the Mac**

The VM's home is visible from the Mac through OrbStack, but `/tmp` inside the VM is not, so copy through `orb`.

```bash
mkdir -p /tmp/nikke-migrate
orb -m pickled-coi bash -lc 'cat /tmp/roster-migrate.db' > /tmp/nikke-migrate/roster.db
orb -m pickled-coi bash -lc 'cat ~/projects/nikke-roster-scanner/.blablalink-session.json' > /tmp/nikke-migrate/.blablalink-session.json
ls -la /tmp/nikke-migrate
```

Expected: `roster.db` around 13MB, the session JSON around 25KB.

- [ ] **Step 4: Stop serve AND the sync timer so nothing is writing during the swap**

Stopping only `nikke.service` is not enough: `nikke-sync.service` declares
`After=nikke.service`, not `Requires=`, so it fires independently on its own
6-hour schedule and isn't held back by serve being down. If `nikke-sync.timer`
stays armed and fires between this step and Step 6, `docker compose run --rm
sync` opens `/srv/data/nikke/roster.db` while Step 5's `sudo install`
truncates and rewrites that same inode out from under it, landing sync's
buffered writes at stale offsets inside the freshly-restored 13MB database.
Stop the timer too, and don't "simplify" this back down to just the service.

```bash
ssh picklelab "sudo systemctl stop nikke-sync.timer nikke.service"
```

- [ ] **Step 5: Upload both files with correct ownership**

`scp -p` preserves the source file's mode instead of landing at the remote
umask (typically 0644, world-readable) on this rootless-docker `ci` host. The
`install` calls are chained with `&&` because the second `install` (session
file, mode 600) must not run against a half-copied database, but `rm` is
split onto its own `;` so the temp copies in `/tmp` are cleaned up even if an
`install` fails partway through -- leaving live auth material sitting
world-readable in `/tmp` is worse than a confusing leftover file.

```bash
scp -p /tmp/nikke-migrate/roster.db picklelab:/tmp/roster-migrate.db
scp -p /tmp/nikke-migrate/.blablalink-session.json picklelab:/tmp/.blablalink-session.json
ssh picklelab "sudo install -o 1000 -g 1000 -m 644 /tmp/roster-migrate.db /srv/data/nikke/roster.db && \
  sudo install -o 1000 -g 1000 -m 600 /tmp/.blablalink-session.json /srv/data/nikke/.blablalink-session.json; \
  rm -f /tmp/roster-migrate.db /tmp/.blablalink-session.json; \
  ls -lan /srv/data/nikke"
```

- [ ] **Step 6: Start serve and the sync timer, then verify the count survived**

Start `nikke.service` before `nikke-sync.timer` so serve is never briefly up
without the safety of a re-armed sync guard racing it -- and so a sync firing
immediately on re-arm reads the already-restored database, not a half-started
serve's.

```bash
ssh picklelab "sudo systemctl start nikke.service"
sleep 10
ssh picklelab "sudo sqlite3 /srv/data/nikke/roster.db 'select count(*) from characters;'"
ssh picklelab "sudo systemctl start nikke-sync.timer"
```

Expected: the same number recorded in Step 1. If it differs, stop and investigate before touching the VM copy.

- [ ] **Step 7: Confirm the dashboard shows the real roster**

```bash
curl -sf https://nikke.tail2023b7.ts.net/ | grep -c -i "character\|nikke" | head -1
```

Expected: a non-zero match count, and the page visibly shows characters when opened in a browser.

- [ ] **Step 8: Clean up the Mac's temp copies**

Leave the VM copy in place until `sync-verification` passes; it is the rollback.

```bash
rm -rf /tmp/nikke-migrate
```

---

### sync-verification

Repo: none. This exercises the scheduled path end to end.

**Files:** none changed.

**Interfaces:**
- Consumes: the migrated data from `data-migration`.
- Produces: a confirmed-working sync path and staleness banner. Gates `retire-coi-machinery`.

- [ ] **Step 1: Run a sync on demand**

```bash
cd ~/github.com/technicalpickles/picklehome
just nikke-sync-now
```

Expected: the unit runs to completion and the journal shows a successful sync. This is the first real test that chromium works in the image and that the migrated session is valid.

- [ ] **Step 2: Confirm the attempt was recorded**

```bash
ssh picklelab "sudo sqlite3 /srv/data/nikke/roster.db 'select started_at, status, error_category, character_count from sync_attempts order by started_at desc limit 3;'"
```

Expected: the newest row has `status=success` and `error_category=none`.

- [ ] **Step 3: Confirm serve was unaffected**

The sync container writes the same SQLite file serve is reading.

```bash
curl -sf -o /dev/null -w "HTTP %{http_code}\n" https://nikke.tail2023b7.ts.net/
```

Expected: `HTTP 200`.

- [ ] **Step 4: Exercise the auth-expired path**

Corrupt the session deliberately, confirm the failure is categorized rather than silent, then restore it.

```bash
ssh picklelab "sudo cp /srv/data/nikke/.blablalink-session.json /srv/data/nikke/.session.bak && echo '{}' | sudo tee /srv/data/nikke/.blablalink-session.json >/dev/null && sudo chown 1000:1000 /srv/data/nikke/.blablalink-session.json"
just nikke-sync-now || true
ssh picklelab "sudo sqlite3 /srv/data/nikke/roster.db 'select status, error_category from sync_attempts order by started_at desc limit 1;'"
```

Expected: `failure|auth_expired`. If it records `other` instead, the detection string in `src/nikke_scanner/blablalink/sync.py` doesn't match what the container produces; fix that in the app repo before moving on.

- [ ] **Step 5: Confirm the dashboard shows the staleness banner**

Open `https://nikke.tail2023b7.ts.net/` in a browser. Expected: a banner reporting the expired session.

- [ ] **Step 6: Restore the session and confirm recovery**

```bash
ssh picklelab "sudo mv /srv/data/nikke/.session.bak /srv/data/nikke/.blablalink-session.json && sudo chown 1000:1000 /srv/data/nikke/.blablalink-session.json && sudo chmod 600 /srv/data/nikke/.blablalink-session.json"
just nikke-sync-now
```

Expected: a fresh `success` row, and the banner is gone on reload.

- [ ] **Step 7: Verify a reboot survives**

```bash
ssh picklelab "sudo reboot" || true
sleep 90
curl -sf -o /dev/null -w "HTTP %{http_code}\n" https://nikke.tail2023b7.ts.net/
ssh picklelab "systemctl is-active nikke.service && systemctl list-timers nikke-sync.timer --no-pager"
```

Expected: `HTTP 200`, `active`, and the timer re-armed.

- [ ] **Step 8: Confirm the backup covers it**

```bash
ssh picklelab "sudo systemctl start backup.service && sudo restic snapshots --tag \$(hostname) --last 1 2>/dev/null | tail -5"
```

Expected: a snapshot completes. `/srv/data/nikke` needs no registration; `backup.sh` snapshots all of `/srv/data`. If `restic` needs env from the backup unit, read the count out of `journalctl -u backup.service` instead.

---

### retire-coi-machinery

Repos: **nikke-roster-scanner** and **pickled-coi**

**Files:**
- Delete: `nikke-serve`, `nikke-sync`, `lib/nikke-container.sh`, `systemd/nikke-sync.service`, `systemd/nikke-sync.timer` (nikke-roster-scanner)
- Modify: `README.md` (pickled-coi), `docs/findings.md` (pickled-coi)

**Interfaces:**
- Consumes: a verified-working deployment from `sync-verification`.
- Produces: no dangling references to the coi-hosted serve path.

Do not start this until `sync-verification` passes. These deletions are the rollback path.

- [ ] **Step 1: Delete the coi serve/sync machinery**

`coi-run` stays; interactive development in coi still happens.

```bash
cd ~/github.com/technicalpickles/nikke-roster-scanner
git rm nikke-serve nikke-sync lib/nikke-container.sh
git rm -r --ignore-unmatch systemd
git commit -m "chore: retire the coi-hosted serve/sync path

Deployment moved to picklelab (see picklehome
docs/plans/2026-07-31-nikke-roster-scanner-design.md). All of this existed
to work around coi container lifecycle, which no longer applies. coi-run
stays for interactive dev sessions."
git push
```

- [ ] **Step 2: Update pickled-coi's README**

Replace the `nikke-serve`/`nikke-sync` workflow description (currently around lines 29 to 58) with a pointer. Keep the `coi build --profile nikke` instructions; the profile is still used for development.

```markdown
For running nikke-roster-scanner (Playwright-based) inside coi for development,
build its image too:

```sh
coi build --profile nikke     # coi-nikke, built on coi-pickles (uv + Playwright)
```

The roster dashboard is **not** served from here any more. It runs on picklelab
as a homelab service at `https://nikke.tail2023b7.ts.net`; see picklehome's
`docs/plans/2026-07-31-nikke-roster-scanner-design.md`. This profile is for
interactive `coi shell` development on the repo only.
```

- [ ] **Step 3: Add the incus findings entry to pickled-coi**

Append to `docs/findings.md`. These cost real time to establish and are not otherwise written down.

```markdown
## incus can't run a locally built OCI image without a registry (2026-07-31)

Found while designing a deployment for nikke-roster-scanner, before the whole
thing moved to picklelab instead. Three facts, all verified live on
`pickled-coi` (incus 7.2):

- **`incus image import` only speaks incus's own format.** Handing it an
  `oci-archive` produced by `skopeo copy docker://... oci-archive:...` fails
  with `Error: Metadata tarball is missing metadata.yaml`.
- **OCI remotes are https-only.** `incus remote add localoci file:///tmp/ocidir
  --protocol oci` and the bare-path equivalent both fail with `Error: Only
  https URLs are supported for oci and simplestreams`. So running a locally
  built OCI image means standing up a registry, full stop.
- **But the incus image format is trivially hand-assemblable.** An exported
  image is two tarballs: a metadata tarball holding a 104-byte `metadata.yaml`
  plus an umoci-generated `config.json` (its `"hostname": "umoci-default"` is
  what gives away that incus shells out to umoci), and a flat rootfs tarball.
  Exporting an OCI-derived image and re-importing the raw tarballs under a new
  alias produced a working `CONTAINER (APP)`. So a local
  skopeo + umoci + tar converter is a viable registry-free path if this ever
  comes up again.

`skopeo` was apt-installed on the VM during this investigation and left in
place. `umoci` is also available in noble's universe repo. Neither is used by
anything here today.
```

- [ ] **Step 4: Commit the pickled-coi changes**

```bash
cd ~/github.com/technicalpickles/pickled-coi
git add README.md docs/findings.md
git commit -m "docs: point nikke deployment at picklelab, record incus OCI limits"
```

---

### docs-registry

Repo: **picklehome**

**Files:**
- Create: `homelab/services/nikke/README.md`
- Modify: `homelab/services/README.md` (service registry)

**Interfaces:**
- Consumes: the deployed service.
- Produces: per-service documentation matching the other services.

- [ ] **Step 1: Write the service README**

```markdown
# Nikke

Roster dashboard for NIKKE, backed by a SQLite store synced from blablalink.com.
Reachable at `https://nikke.tail2023b7.ts.net`.

## Shape

One image (`nikke:local`, built from `/opt/nikke-roster-scanner`) backing two
Compose services:

| Service | Lifetime | What |
|---------|----------|------|
| `serve` | long-lived, `restart: unless-stopped` | FastAPI dashboard on `127.0.0.1:8770` |
| `sync`  | `run --rm` from a timer | `nikke-scan blablalink sync --headless`, every 6h |

TLS is a Tailscale Service (`svc:nikke`) terminating on the host and proxying to
the loopback binding. No reverse proxy container.

## Data

`/srv/data/nikke/` (uid 1000), holding `roster.db` and `.blablalink-session.json`.
Covered by the nightly restic backup with no registration, since `backup.sh`
snapshots all of `/srv/data`.

## When the roster goes stale

The dashboard shows a staleness banner when the last successful sync is old, or
when the most recent attempt failed with `auth_expired`. Blablalink sessions
expire and re-login needs a real browser, which picklelab doesn't have, so:

```sh
just nikke-login
```

That opens a browser on your Mac, uploads the refreshed session, and runs a
sync to confirm it took.

## Operating

```sh
just deploy-nikke        # full deploy (pull, build, restart, health check)
just nikke-logs          # recent container logs
just nikke-logs-follow   # live logs
just nikke-sync-now      # run a sync instead of waiting for the timer
```

Sync history lives in the `sync_attempts` table:

```sh
ssh picklelab "sudo sqlite3 /srv/data/nikke/roster.db \
  'select started_at, status, error_category, character_count from sync_attempts order by started_at desc limit 10;'"
```

## Gotchas

- **`--db /data/roster.db` is passed explicitly** in both Compose commands. The
  CLI defaults to a cwd-relative `roster.db` with no env-var override, so
  dropping the flag silently writes into the container.
- **`nikke.service` runs `up -d --build serve`**, naming the service. A bare
  `up -d` would also start `sync`, firing a full blablalink sync on every deploy
  and every boot.
- **Chromium lives at `/ms-playwright`**, not in the build user's home, so uid
  1000 can read it. Changing the Dockerfile's `USER` without keeping
  `PLAYWRIGHT_BROWSERS_PATH` breaks sync but not serve, so it fails 6 hours
  later rather than at deploy.
- **First deploy needs the Tailscale Service approved** at
  `login.tailscale.com/admin/services`, and then re-advertised by hand.
  `deploy.sh` prints the exact commands when its tailnet check fails.
```

- [ ] **Step 2: Add nikke to the service registry**

In `homelab/services/README.md`, add a row to the uid assignments table:

```markdown
| nikke | 1000:1000 | `compose.yaml` `user: "1000:1000"`; Dockerfile `useradd -u 1000`; `deploy.sh` chowns `/srv/data/nikke` |
```

Also add nikke to the per-service registry section, matching the format used by the neighbouring entries.

- [ ] **Step 3: Commit**

```bash
cd ~/github.com/technicalpickles/picklehome
git add homelab/services/nikke/README.md homelab/services/README.md
git commit -m "docs(nikke): service README and registry entry"
```

---

## Self-review notes

Checked against `docs/plans/2026-07-31-nikke-roster-scanner-design.md`:

- Every file in the design's service-directory table has a task that creates it.
- The design's four gotchas (Tailscale approval and re-advertise, HTTPS enabled
  in the tailnet, `.dockerignore`, explicit `--db`) each appear in a task step
  and in the service README.
- The design's "open risks" are addressed: Playwright is verified in `dockerfile`
  Step 4 rather than assumed, sync duration informs `TimeoutStartSec=900`, and
  the uid-1000 assumption is verified live in `first-deploy` Step 5.
- Names are consistent across tasks: `nikke:local`, `serve`, `sync`,
  `NIKKE_PORT`, `NIKKE_GIT_SHA`, `NIKKE_SESSION_PATH`, `/opt/nikke-roster-scanner`,
  `/srv/data/nikke`, `svc:nikke`.

One deviation from the design worth noting: the design said "use the official
Playwright base image rather than hand-installing system libraries." This plan
uses `python:3.13-slim` plus `playwright install --with-deps chromium` instead,
which does the same apt work but keeps the chromium version tied to the
`playwright` pin in `uv.lock` rather than to a separately-versioned base image
tag. Same outcome, one fewer version to keep in sync.
