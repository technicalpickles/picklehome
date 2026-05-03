# TaskChampion Sync — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Self-host a TaskChampion sync server on picklelab and configure the Mac's Taskwarrior to use it.

**Architecture:** Docker Compose service following the homelab pattern (loopback bind, Tailscale Services for TLS, /srv/data bind mount, systemd unit). Encryption secret stays Mac-side via fnox; server only sees opaque blobs.

**Tech Stack:** `ghcr.io/gothenburgbitfactory/taskchampion-sync-server` (Rust/actix-web), Docker Compose, systemd, Tailscale Services, fnox (keychain), Taskwarrior 3.x.

**Reference design:** [`2026-05-03-taskchampion-sync.md`](./2026-05-03-taskchampion-sync.md).

---

## Notes on plan shape

This is a service-deployment task, not a code feature. There are no unit tests — verification is operational (deploy, status check, real sync). Each step has a concrete verification command. Steps use stable kebab-case slugs; renumbering won't affect downstream references.

Commits land in chunks rather than per-step; commit boundaries are marked explicitly.

---

## op-item

**One-time secret setup. No code changes; no commit.**

Create the `TaskChampion Sync` item in the `picklehome` 1Password vault with three fields:

```
host             = taskchampion.tail2023b7.ts.net
client_id        = <output of `uuidgen`>
encryption_secret = <output of `openssl rand -base64 32`>
```

**Verify:**
```sh
op item get "TaskChampion Sync" --vault picklehome --format json | jq '[.fields[] | select(.label != null) | .label]'
```
Expected output includes `"host"`, `"client_id"`, `"encryption_secret"`.

---

## env-template

**Add the .env.template references and regenerate `.env`.**

**Files:**
- Modify: `.env.template` (add two lines)

**Step 1.** Open `.env.template` and add (alphabetically near other Tailscale-fronted services like `BASEROW_HOST`/`VIKUNJA_HOST`):

```
# TASKCHAMPION_SYNC_HOST: Tailscale Services hostname — taskchampion.<tailnet>.ts.net
TASKCHAMPION_SYNC_HOST={{ op://picklehome/TaskChampion Sync/host }}

# TASKCHAMPION_SYNC_SERVER_CLIENT_ID: server allowlist + client identifier (UUID)
TASKCHAMPION_SYNC_SERVER_CLIENT_ID={{ op://picklehome/TaskChampion Sync/client_id }}
```

Note: `encryption_secret` is intentionally NOT added — it never reaches picklelab.

**Step 2.** Regenerate `.env`:

```sh
just dotenv
```

**Verify:**
```sh
grep TASKCHAMPION /Users/technicalpickles/github.com/technicalpickles/picklehome/.env
```
Expected: two non-empty lines, the client_id is a UUID, the host ends in `.ts.net`.

**Commit boundary** — commit env-template alone, before service files:

```sh
git add .env.template
git commit -m "feat(taskchampion): add env template entries"
```

---

## service-files

**Create the service directory with compose, .env.vars, systemd unit, and service README.**

**Files:**
- Create: `homelab/services/taskchampion-sync/.env.vars`
- Create: `homelab/services/taskchampion-sync/compose.yaml`
- Create: `homelab/services/taskchampion-sync/compose.picklelab.yaml`
- Create: `homelab/services/taskchampion-sync/taskchampion-sync.service`
- Create: `homelab/services/taskchampion-sync/README.md`

**Step 1 — `.env.vars`:**

```
TASKCHAMPION_SYNC_SERVER_CLIENT_ID
```

(One line. The host and encryption secret are not needed by the server.)

**Step 2 — `compose.yaml`:**

```yaml
services:
  taskchampion-sync:
    image: ghcr.io/gothenburgbitfactory/taskchampion-sync-server:latest
    restart: unless-stopped
    environment:
      CLIENT_ID: ${TASKCHAMPION_SYNC_SERVER_CLIENT_ID:?required}
      LISTEN: 0.0.0.0:${TASKCHAMPION_SYNC_PORT:?set by deploy.sh}
      DATA_DIR: /var/lib/taskchampion
    ports:
      - "127.0.0.1:${TASKCHAMPION_SYNC_PORT:?set by deploy.sh}:${TASKCHAMPION_SYNC_PORT:?set by deploy.sh}"
    volumes:
      - data:/var/lib/taskchampion

volumes:
  data:
```

**Step 3 — `compose.picklelab.yaml`:**

```yaml
services:
  taskchampion-sync:
    volumes:
      - /srv/data/taskchampion-sync:/var/lib/taskchampion

volumes:
  data:
    name: taskchampion-sync_data_unused
```

The named-volume override is the cleanest way to make `compose.picklelab.yaml` add a bind mount without breaking the base compose's named-volume declaration. Both volumes appear, but the bind mount wins because it comes second in the merged config.

**Step 4 — `taskchampion-sync.service`:**

```
[Unit]
Description=TaskChampion sync server
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/homelab/homelab/services/taskchampion-sync
EnvironmentFile=/opt/homelab/homelab/services/taskchampion-sync/.env.build
ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml up -d --pull always
ExecStop=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml down

[Install]
WantedBy=multi-user.target
```

The `EnvironmentFile=` exists so systemd has `TASKCHAMPION_SYNC_PORT` set when restarting after `daemon-reload` (compose's strict `${...:?...}` interpolation otherwise fails on systemd's empty-env restart). `.env.build` is generated by `deploy.sh`; same pattern as brineworks-server.

**Step 5 — `README.md`:**

Match the shape of `homelab/services/brineworks-server/README.md`. Sections:

- Description (1 paragraph): self-host TaskChampion sync; Mac is the only client today.
- Prerequisites: Tailscale HTTPS enabled, `tag:server` on picklelab, `taskchampion` Service registered in admin.
- 1Password item shape (link to design doc).
- First-time setup (`just dotenv`, `just deploy-taskchampion`, fnox + .taskrc on Mac).
- Deploy updates.
- Status / logs.
- Networking section: container binds 127.0.0.1:9080, default port via `TASKCHAMPION_SYNC_PORT`, behind tailscale serve.
- Cross-link to design doc.

**Verify:**
```sh
ls homelab/services/taskchampion-sync/
```
Expected: `.env.vars`, `compose.yaml`, `compose.picklelab.yaml`, `taskchampion-sync.service`, `README.md`.

---

## deploy-script

**Create `deploy.sh` modeled on brineworks-server's (port handling + health check loop).**

**Files:**
- Create: `homelab/services/taskchampion-sync/deploy.sh` (executable)

**Content:**

```bash
#!/usr/bin/env bash
# Deploy TaskChampion sync server on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/taskchampion-sync"
DATA_DIR=/srv/data/taskchampion-sync

# Default server port — override by exporting TASKCHAMPION_SYNC_PORT before running.
# Compose files read this via ${TASKCHAMPION_SYNC_PORT:?...} so it must be exported.
export TASKCHAMPION_SYNC_PORT="${TASKCHAMPION_SYNC_PORT:-9080}"

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Writing build metadata"
# Loaded by systemd unit (EnvironmentFile=) and present in compose env.
echo "TASKCHAMPION_SYNC_PORT=$TASKCHAMPION_SYNC_PORT" > "$SERVICE_DIR/.env.build"

echo "==> Creating data directory"
sudo mkdir -p "$DATA_DIR"
# The upstream entrypoint chowns DATA_DIR to user 'taskchampion' (uid varies by image build);
# entrypoint runs as root inside the container, so host-side perms only need to be writable
# by docker. Default 755 is fine.

echo "==> Configuring Tailscale serve for taskchampion"
sudo tailscale serve --service=svc:taskchampion --https=443 "http://127.0.0.1:$TASKCHAMPION_SYNC_PORT"

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/taskchampion-sync.service" /etc/systemd/system/

echo "==> Reloading systemd and restarting service"
sudo systemctl daemon-reload
sudo systemctl enable taskchampion-sync.service
sudo systemctl restart taskchampion-sync.service

echo "==> Status"
systemctl status taskchampion-sync.service --no-pager

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
TC_URL="https://taskchampion.${TAILNET}"

echo ""
echo "==> Checking local health endpoint"
for i in 1 2 3 4 5; do
    if curl -sf "http://127.0.0.1:$TASKCHAMPION_SYNC_PORT/" > /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 5 ]; then
        echo "    WARNING: local health check failed after 5 attempts"
        echo "    Check container logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for server to start (attempt $i/5)..."
    sleep 3
done

echo ""
echo "==> Checking Tailscale endpoint"
if curl -sf "${TC_URL}/" > /dev/null 2>&1; then
    echo "    Tailscale health check passed"
    echo ""
    echo "Done! TaskChampion available at ${TC_URL}"
else
    echo "    WARNING: Tailscale endpoint not responding at ${TC_URL}"
    echo ""
    echo "    If this is the first deploy, you need to approve the service:"
    echo "    1. Open https://login.tailscale.com/admin/services"
    echo "    2. Find 'taskchampion' and approve the pending host"
    echo "    3. Re-advertise (tailscaled doesn't auto-detect approval):"
    echo "       sudo tailscale serve --service=svc:taskchampion --https=443 off"
    echo "       sleep 2"
    echo "       sudo tailscale serve --service=svc:taskchampion --https=443 http://127.0.0.1:\$TASKCHAMPION_SYNC_PORT"
    echo "    4. Verify: curl ${TC_URL}/"
fi
```

**Make executable:**
```sh
chmod +x homelab/services/taskchampion-sync/deploy.sh
```

**Verify:**
```sh
test -x homelab/services/taskchampion-sync/deploy.sh && bash -n homelab/services/taskchampion-sync/deploy.sh
```
Expected: no output (syntax OK, executable bit set).

---

## justfile-recipes

**Add deploy + status + logs recipes to root Justfile.**

**Files:**
- Modify: `Justfile` (add 4 recipes near the existing `deploy-vikunja` block)

**Content to add:**

```just
# Deploy TaskChampion sync server to picklelab (idempotent: first setup or update)
deploy-taskchampion host="picklelab":
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
        git push origin main
    fi
    SERVICE_DIR=homelab/services/taskchampion-sync
    scripts/service-env "$SERVICE_DIR"
    scp "$SERVICE_DIR/.env" {{host}}:/srv/containers/taskchampion-sync/.env
    rm "$SERVICE_DIR/.env"
    ssh {{host}} "cd /opt/homelab && git pull --ff-only && bash $SERVICE_DIR/deploy.sh"

# Status check for TaskChampion sync server (systemd + loopback + tailscale)
taskchampion-status host="picklelab":
    #!/usr/bin/env bash
    set -uo pipefail
    echo "==> systemd unit on {{host}}"
    ssh {{host}} "sudo systemctl status taskchampion-sync.service --no-pager" || true
    echo ""
    echo "==> loopback HTTP on {{host}}"
    ssh {{host}} "curl -fsS http://127.0.0.1:9080/ -w '\nHTTP %{http_code}  %{time_total}s\n'" || echo "loopback FAILED"
    echo ""
    echo "==> tailscale routing (from this machine)"
    if [ -z "${TASKCHAMPION_SYNC_SERVER_URL:-}" ]; then
        echo "TASKCHAMPION_SYNC_SERVER_URL not set in shell env (fnox not loaded?)"
    else
        curl -fsS "$TASKCHAMPION_SYNC_SERVER_URL" -w "\nHTTP %{http_code}  %{time_total}s\n" || echo "tailscale routing FAILED"
    fi

# Tail TaskChampion sync server logs
taskchampion-logs host="picklelab" lines="50":
    ssh {{host}} "sudo journalctl -u taskchampion-sync.service --no-pager -n {{lines}}"

# Follow TaskChampion sync server logs live
taskchampion-logs-follow host="picklelab":
    ssh {{host}} "sudo journalctl -u taskchampion-sync.service -f"
```

**Cross-check the deploy recipe** against `deploy-vikunja` and `deploy-brineworks-server` — the actual scp + ssh commands should match whichever pattern they use; replicate exactly to avoid drift.

**Verify:**
```sh
just --list 2>&1 | grep taskchampion
```
Expected: 4 recipes listed (`deploy-taskchampion`, `taskchampion-status`, `taskchampion-logs`, `taskchampion-logs-follow`).

---

## services-registry

**Add a row to the service registry in `homelab/services/README.md`.**

**Files:**
- Modify: `homelab/services/README.md` (add `### taskchampion-sync` block alphabetically — between `obsidian-sync` and `vikunja` if ordered alphabetically, or wherever new services have been appended)

**Content to add:**

```markdown
### taskchampion-sync

Self-hosted Taskwarrior sync server. Replicates the Mac's `~/.task` to picklelab; encryption secret stays client-side.

| | |
|---|---|
| **Purpose** | Off-laptop replica of Taskwarrior data; future multi-device sync |
| **Compose** | `/srv/containers/taskchampion-sync/` |
| **Data** | `/srv/data/taskchampion-sync/` (SQLite, encrypted blobs) |
| **Access** | `https://taskchampion.<tailnet>.ts.net` (Tailscale Services, port 9080 internally) |
| **Env vars** | `TASKCHAMPION_SYNC_HOST`, `TASKCHAMPION_SYNC_SERVER_CLIENT_ID` |
| **Backup** | Yes, nightly (SQLite picked up by `/srv/data` restic job) |
| **Restart** | `restart: unless-stopped` |

Commands: `just deploy-taskchampion`, `just taskchampion-status`, `just taskchampion-logs`, `just taskchampion-logs-follow`

See [taskchampion-sync/README.md](taskchampion-sync/README.md) for full setup.

---
```

**Commit boundary** — commit service-files + deploy-script + justfile-recipes + services-registry as one logical "add taskchampion-sync service" commit:

```sh
git add homelab/services/taskchampion-sync/ homelab/services/README.md Justfile
git commit -m "feat(taskchampion): add sync server service"
```

(Two commits total at this point: `env-template` and `taskchampion-sync service`.)

---

## tailscale-prereqs

**One-time admin-console setup. Manual; no code, no commit.**

Open https://login.tailscale.com/admin/services. Click "Define Service":
- Name: `taskchampion`
- Ports: `443`

If `tag:server` and HTTPS-cert support are already in place from Vikunja, skip those steps. Otherwise follow the prereq list in `homelab/services/vikunja/README.md`.

**Verify:** the Service appears in the list at https://login.tailscale.com/admin/services. (No host approved yet — that comes after first deploy.)

---

## first-deploy

**Run the deploy. No commit (operational).**

```sh
just deploy-taskchampion
```

Expected output (in order):
- `==> Deploying commit <sha>`
- `==> Writing build metadata`
- `==> Creating data directory`
- `==> Configuring Tailscale serve for taskchampion`
- `==> Linking systemd unit`
- `systemctl status` showing `Active: active`
- `Local health check passed` (within ~15s)
- Either `Tailscale health check passed` OR a "approve the pending host" message

If the Tailscale check fails on first run, follow the on-screen instructions: approve the host in admin, then re-advertise.

**Verify (after host approval if needed):**
```sh
curl -fsS https://taskchampion.tail2023b7.ts.net/
```
Expected: `TaskChampion sync server vX.Y.Z`

---

## mac-fnox

**Set the three secrets in fnox keychain. No commit.**

Read each value out of 1Password and set via fnox:

```fish
fnox set TASKCHAMPION_SYNC_SERVER_URL (op read "op://picklehome/TaskChampion Sync/host" | xargs -I{} echo "https://{}")
fnox set TASKCHAMPION_SYNC_SERVER_CLIENT_ID (op read "op://picklehome/TaskChampion Sync/client_id")
fnox set TASKCHAMPION_SYNC_ENCRYPTION_SECRET (op read "op://picklehome/TaskChampion Sync/encryption_secret")
```

(The first command prepends `https://` because the 1Password field stores the bare hostname.)

**Verify** in a NEW shell (so `fnox activate` re-runs):

```fish
echo $TASKCHAMPION_SYNC_SERVER_URL
echo $TASKCHAMPION_SYNC_SERVER_CLIENT_ID
test -n "$TASKCHAMPION_SYNC_ENCRYPTION_SECRET" && echo "encryption secret loaded" || echo "MISSING"
```

Expected: URL is `https://taskchampion.tail2023b7.ts.net`, client_id is a UUID, secret is loaded.

---

## taskrc

**Add three lines to `~/.taskrc`. No commit (file is on Mac, not in repo).**

Append to `~/.taskrc`:

```
sync.server.url=$TASKCHAMPION_SYNC_SERVER_URL
sync.server.client_id=$TASKCHAMPION_SYNC_SERVER_CLIENT_ID
sync.encryption_secret=$TASKCHAMPION_SYNC_ENCRYPTION_SECRET
```

**Verify:**
```sh
task _show | grep ^sync\.
```

Expected: three lines printed with the resolved values (URL, UUID, base64 secret).

---

## first-sync

**Push existing tasks to the server. No commit.**

```sh
task sync
```

Expected: a message like `Sync successful` or version-count output. First sync may take a few seconds.

**Verify on server side:**
```sh
just taskchampion-logs lines=20
```
Expected: log lines showing recent POST requests to `/v1/client/...` paths.

**Verify data exists in storage:**
```sh
ssh picklelab "sudo ls -la /srv/data/taskchampion-sync/"
```
Expected: a SQLite database file and possibly WAL/SHM siblings.

---

## roundtrip-test

**Prove read-back works by destroying the local replica. No commit.**

```sh
task add "sync-test sentinel" +synctest
task sync

# Snapshot current local data, then nuke it
TASK_BACKUP=~/.task.preserved-$(date +%s)
mv ~/.task "$TASK_BACKUP"
mkdir ~/.task
task sync                                    # rebuilds from server
task +synctest list                          # should show sentinel

# Cleanup sentinel + restore (or trust the rebuild)
task /sync-test/ delete && task sync
```

**Verify:**
- `task +synctest list` shows the sentinel after the local nuke.
- `task list` post-restore shows the same task count as before the test.

If the count matches, the system is end-to-end functional.

**If it works, optionally remove the backup:**
```sh
rm -rf ~/.task.preserved-*
```

(Keep it around for a day if you want extra paranoia.)

---

## Done

State after completion:
- Two commits on main (`feat(taskchampion): add env template entries`, `feat(taskchampion): add sync server service`)
- Service running on picklelab, reachable at `https://taskchampion.tail2023b7.ts.net`
- Mac's `~/.task` syncing to it
- Backups capturing the SQLite under `/srv/data/taskchampion-sync/`
- Service registered in `homelab/services/README.md`

No follow-up needed unless adding a second device.
