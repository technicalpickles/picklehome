# Woodpecker CI on picklelab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up self-hosted Woodpecker CI on picklelab serving test-only pipelines for pirpg and brineworks, with Funnel ingress on a zero-privilege tailscale sidecar and CI step isolation via a rootless Docker daemon.

**Architecture:** Three containers (tailscale sidecar + woodpecker-server + woodpecker-agent) share one network namespace; the sidecar owns the `woodpecker.tail2023b7.ts.net` node identity and runs Funnel (userspace mode) from a checked-in `funnel.json`. The agent spawns CI step containers on a *separate rootless dockerd* running as a dedicated unprivileged `ci` user, so a compromised step cannot read the host secret superset. Deploy follows the existing homelab pattern (`just deploy-woodpecker` → `service-env` filter → scp → remote `deploy.sh` → systemd).

**Tech Stack:** Woodpecker CI, Docker Compose, Tailscale (Funnel + container-as-node), rootless Docker, systemd, 1Password, GitHub OAuth.

**Design reference:** `docs/plans/2026-06-18-woodpecker-ci-design.md`

**Conventions:**
- Tailnet suffix `tail2023b7.ts.net`. GitHub user `technicalpickles`.
- Dedicated CI user is `ci` with a **fixed uid `2000`**, so the rootless socket path `/run/user/2000/docker.sock` is deterministic and hardcodable.
- **HUMAN-RUN** = run interactively on picklelab (needs sudo password / browser / GitHub admin UI); the agent cannot do these over non-interactive ssh. **AGENT-RUN** = file edits + commits on the Mac, or non-interactive ssh.

---

## Task 1: Spike — prove userspace Funnel works (de-risk before building anything)

The design's single riskiest assumption: that Tailscale Funnel works in **userspace** mode inside a container, proxying to a sibling container over a shared netns. Prove it with a throwaway before building the real service. (HUMAN-RUN: needs the Tailscale admin console + sudo on picklelab.)

**Files:**
- Create (throwaway, do not commit): `/tmp/funnel-spike/compose.yaml` on picklelab

- [ ] **Step 1: Pre-grant tag + funnel in the tailnet ACL**

In the Tailscale admin console (https://login.tailscale.com/admin/acls), add `tag:ci` (owned by you) and grant it Funnel. Minimal additions:

```jsonc
"tagOwners": {
  "tag:ci": ["autogroup:admin"]
},
"nodeAttrs": [
  { "target": ["tag:ci"], "attr": ["funnel"] }
]
```

Save. (Funnel for the tailnet must already be enabled — it is, since HTTPS certs are in use for the `svc:` services.)

- [ ] **Step 2: Mint a throwaway tagged auth key**

Admin console → Settings → Keys → Generate auth key. Reusable, ephemeral OK, **Tags: `tag:ci`**. Copy it.

- [ ] **Step 3: Write the spike compose on picklelab**

```yaml
# /tmp/funnel-spike/compose.yaml
services:
  ts-spike:
    image: tailscale/tailscale:latest
    hostname: woodpecker-spike
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}
      - TS_USERSPACE=true
      - TS_EXTRA_ARGS=--advertise-tags=tag:ci
      - TS_SERVE_CONFIG=/config/funnel.json
    volumes:
      - ./funnel.json:/config/funnel.json:ro
  whoami:
    image: traefik/whoami:latest
    network_mode: service:ts-spike
    command: ["--port", "8000"]
    depends_on: [ts-spike]
```

```json
// /tmp/funnel-spike/funnel.json
{
  "TCP": { "443": { "HTTPS": true } },
  "Web": {
    "woodpecker-spike.tail2023b7.ts.net:443": {
      "Handlers": { "/": { "Proxy": "http://127.0.0.1:8000" } }
    }
  },
  "AllowFunnel": { "woodpecker-spike.tail2023b7.ts.net:443": true }
}
```

- [ ] **Step 4: Bring it up**

Run on picklelab: `cd /tmp/funnel-spike && TS_AUTHKEY=<key> docker compose up -d`

- [ ] **Step 5: Verify Funnel is serving and the cert provisioned**

Run: `docker compose exec ts-spike tailscale funnel status`
Expected: shows `woodpecker-spike.tail2023b7.ts.net:443` proxying to `http://127.0.0.1:8000`.

- [ ] **Step 6: Verify public reachability (the real proof)**

From a network *off* the tailnet (phone on cellular, or any external host):
Run: `curl -sS https://woodpecker-spike.tail2023b7.ts.net/`
Expected: whoami response (Hostname/IP lines). This proves userspace Funnel + shared-netns proxy + public cert all work end to end.

- [ ] **Step 7: Tear down**

Run on picklelab: `cd /tmp/funnel-spike && docker compose down && cd / && rm -rf /tmp/funnel-spike`
Then in the admin console, delete the `woodpecker-spike` machine and the throwaway auth key.

> **Gate:** if Step 6 fails, STOP and revisit Section 2 of the design (likely fixes: funnel only on ports 443/8443/10000; userspace proxy must point at `127.0.0.1:8000` which only resolves because of the shared netns). Do not proceed until this passes.

---

## Task 2: Tailnet — finalize tag:ci and mint the durable auth key

(HUMAN-RUN: Tailscale admin console + 1Password.)

**Files:** none in-repo (admin console + 1Password).

- [ ] **Step 1: Confirm the ACL additions from Task 1 Step 1 are saved**

`tag:ci` exists in `tagOwners` and has the `funnel` nodeAttr. (Already done in the spike; just confirm it's still present.)

- [ ] **Step 2: Mint the durable auth key**

Admin console → Settings → Keys → Generate auth key:
- **Reusable**: yes (survives container recreates)
- **Ephemeral**: no (node should persist; we also persist `TS_STATE_DIR`)
- **Tags**: `tag:ci`

- [ ] **Step 3: Store it in 1Password**

Create item `Woodpecker CI` in the `picklehome` vault (we add more fields in Task 4). Add field `ts_authkey` = the key.

- [ ] **Step 4: Verify the field name**

Run on the Mac: `op item get "Woodpecker CI" --vault picklehome --format json | jq '[.fields[] | {label, id}]'`
Expected: shows a `ts_authkey` field.

---

## Task 3: Host — rootless Docker daemon as the `ci` user (Option D)

This is the isolation boundary. (HUMAN-RUN: interactive sudo on picklelab.)

**Files:** host-only; documented later in Task 15.

- [ ] **Step 1: Create the dedicated `ci` user with fixed uid 2000**

Run on picklelab:
```bash
sudo useradd --uid 2000 --create-home --shell /usr/bin/bash ci
```
The `ci` user owns nothing under `/opt/homelab` or `/srv` — that is the whole point.

- [ ] **Step 2: Install rootless Docker prerequisites**

Run on picklelab:
```bash
sudo apt-get update
sudo apt-get install -y uidmap dbus-user-session docker-ce-rootless-extras slirp4netns
```

- [ ] **Step 3: Enable lingering so the ci user's daemon survives logout/reboot**

Run on picklelab: `sudo loginctl enable-linger ci`

- [ ] **Step 4: Install the rootless daemon as the ci user**

Run on picklelab:
```bash
sudo -iu ci bash -lc 'export XDG_RUNTIME_DIR=/run/user/2000; dockerd-rootless-setuptool.sh install'
sudo -iu ci bash -lc 'export XDG_RUNTIME_DIR=/run/user/2000; systemctl --user enable --now docker'
```

- [ ] **Step 5: Verify the rootless socket exists and runs a container**

Run on picklelab:
```bash
sudo -iu ci bash -lc 'export DOCKER_HOST=unix:///run/user/2000/docker.sock; docker run --rm hello-world'
```
Expected: the "Hello from Docker!" message. Confirms the rootless daemon works.

- [ ] **Step 6: Verify the isolation boundary (the critical test)**

Confirm the master env is locked down first:
```bash
ls -l /opt/homelab/.env    # expect mode -rw------- owner technicalpickles
```
Then attempt to read it from a rootless container bind-mounting the homelab dir:
```bash
sudo -iu ci bash -lc 'export DOCKER_HOST=unix:///run/user/2000/docker.sock; docker run --rm -v /opt/homelab:/host:ro alpine cat /host/.env'
```
Expected: **`cat: can't open '/host/.env': Permission denied`**. This proves a CI step on the rootless daemon cannot read the secret superset. If it instead prints the file, STOP — the isolation is not working (check that `.env` is mode 600 and that rootless userns remap is active via `docker info | grep -i rootless`).

---

## Task 4: GitHub OAuth App + complete the 1Password item

(HUMAN-RUN: GitHub developer settings + 1Password.)

**Files:** none in-repo.

- [ ] **Step 1: Create the OAuth App**

GitHub → Settings → Developer settings → **OAuth Apps** (NOT GitHub Apps) → New OAuth App:

| Field | Value |
|-------|-------|
| Application name | `Woodpecker CI` |
| Homepage URL | `https://woodpecker.tail2023b7.ts.net` |
| Authorization callback URL | `https://woodpecker.tail2023b7.ts.net/authorize` |

Register, then **Generate a new client secret**.

- [ ] **Step 2: Generate the agent secret**

Run on the Mac: `openssl rand -hex 32`

- [ ] **Step 3: Add all fields to the `Woodpecker CI` 1Password item**

Add to the existing item (`picklehome` vault):
- `github_client` = OAuth App Client ID
- `github_secret` = OAuth App Client Secret
- `agent_secret` = the `openssl rand -hex 32` output
- (`ts_authkey` already added in Task 2)

- [ ] **Step 4: Verify field names**

Run on the Mac: `op item get "Woodpecker CI" --vault picklehome --format json | jq '[.fields[] | {label, id}]'`
Expected: `github_client`, `github_secret`, `agent_secret`, `ts_authkey` all present.

---

## Task 5: Wire secrets into the master env

(AGENT-RUN: edit + commit on the Mac.)

**Files:**
- Modify: `.env.template`

- [ ] **Step 1: Add the op:// references to `.env.template`**

Append:
```bash
# Woodpecker CI
WOODPECKER_GITHUB_CLIENT={{ op://picklehome/Woodpecker CI/github_client }}
WOODPECKER_GITHUB_SECRET={{ op://picklehome/Woodpecker CI/github_secret }}
WOODPECKER_AGENT_SECRET={{ op://picklehome/Woodpecker CI/agent_secret }}
WOODPECKER_TS_AUTHKEY={{ op://picklehome/Woodpecker CI/ts_authkey }}
```

- [ ] **Step 2: Regenerate `.env`**

Run on the Mac: `just dotenv`
Expected: no errors; `.env` now contains the four `WOODPECKER_*` vars.

- [ ] **Step 3: Verify the values resolved (not left as `op://` refs)**

Run on the Mac: `grep -c '^WOODPECKER_' .env`
Expected: `4`. Spot-check none contain the literal string `op://`.

- [ ] **Step 4: Commit**

```bash
git add .env.template
git commit -m "feat(woodpecker): add CI secrets to env template"
```
(`.env` is gitignored; only the template is committed.)

---

## Task 6: Service skeleton — directory, `.env.vars`, `funnel.json`

(AGENT-RUN.)

**Files:**
- Create: `homelab/services/woodpecker/.env.vars`
- Create: `homelab/services/woodpecker/funnel.json`

- [ ] **Step 1: Create `.env.vars`**

```
WOODPECKER_GITHUB_CLIENT
WOODPECKER_GITHUB_SECRET
WOODPECKER_AGENT_SECRET
WOODPECKER_TS_AUTHKEY
```

- [ ] **Step 2: Create `funnel.json`**

```json
{
  "TCP": { "443": { "HTTPS": true } },
  "Web": {
    "woodpecker.tail2023b7.ts.net:443": {
      "Handlers": { "/": { "Proxy": "http://127.0.0.1:8000" } }
    }
  },
  "AllowFunnel": { "woodpecker.tail2023b7.ts.net:443": true }
}
```

- [ ] **Step 3: Commit**

```bash
git add homelab/services/woodpecker/.env.vars homelab/services/woodpecker/funnel.json
git commit -m "feat(woodpecker): service env vars + funnel config"
```

---

## Task 7: `compose.yaml` (base definition)

(AGENT-RUN.)

**Files:**
- Create: `homelab/services/woodpecker/compose.yaml`

- [ ] **Step 1: Write the base compose**

```yaml
services:
  ts-woodpecker:
    image: tailscale/tailscale:latest
    hostname: woodpecker                       # -> woodpecker.tail2023b7.ts.net
    environment:
      - TS_AUTHKEY=${WOODPECKER_TS_AUTHKEY}
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_USERSPACE=true                       # HTTP-only Funnel: no NET_ADMIN, no tun
      - TS_EXTRA_ARGS=--advertise-tags=tag:ci
      - TS_SERVE_CONFIG=/config/funnel.json
    volumes:
      - ./funnel.json:/config/funnel.json:ro
    restart: unless-stopped

  woodpecker-server:
    image: woodpeckerci/woodpecker-server:latest
    network_mode: service:ts-woodpecker
    depends_on: [ts-woodpecker]
    env_file:
      - .env
    environment:
      - WOODPECKER_HOST=https://woodpecker.tail2023b7.ts.net
      - WOODPECKER_GITHUB=true
      - WOODPECKER_GITHUB_CLIENT=${WOODPECKER_GITHUB_CLIENT}
      - WOODPECKER_GITHUB_SECRET=${WOODPECKER_GITHUB_SECRET}
      - WOODPECKER_AGENT_SECRET=${WOODPECKER_AGENT_SECRET}
      - WOODPECKER_REPO_OWNERS=technicalpickles
      - WOODPECKER_ADMIN=technicalpickles
      - WOODPECKER_OPEN=false
    restart: unless-stopped

  woodpecker-agent:
    image: woodpeckerci/woodpecker-agent:latest
    network_mode: service:ts-woodpecker
    depends_on: [woodpecker-server]
    user: "2000:2000"                           # the ci uid, to access the rootless socket
    env_file:
      - .env
    environment:
      - WOODPECKER_SERVER=localhost:9000
      - WOODPECKER_AGENT_SECRET=${WOODPECKER_AGENT_SECRET}
      - WOODPECKER_MAX_WORKFLOWS=2
      - DOCKER_HOST=unix:///rootless/docker.sock
    restart: unless-stopped
```

- [ ] **Step 2: Validate compose syntax locally**

Run on the Mac (needs the four vars; export dummies just to parse):
```bash
cd homelab/services/woodpecker
WOODPECKER_TS_AUTHKEY=x WOODPECKER_GITHUB_CLIENT=x WOODPECKER_GITHUB_SECRET=x WOODPECKER_AGENT_SECRET=x docker compose -f compose.yaml config -q
```
Expected: no output (valid). Errors here are syntax problems to fix now.

- [ ] **Step 3: Commit**

```bash
git add homelab/services/woodpecker/compose.yaml
git commit -m "feat(woodpecker): base compose (sidecar + server + agent)"
```

---

## Task 8: `compose.picklelab.yaml` (production overrides)

(AGENT-RUN.) Persists state to `/srv/data` and bind-mounts the rootless socket into the agent.

**Files:**
- Create: `homelab/services/woodpecker/compose.picklelab.yaml`

- [ ] **Step 1: Write the prod overrides**

```yaml
services:
  ts-woodpecker:
    volumes:
      - /srv/data/woodpecker/ts-state:/var/lib/tailscale   # persist node identity

  woodpecker-server:
    volumes:
      - /srv/data/woodpecker/server:/var/lib/woodpecker     # SQLite DB

  woodpecker-agent:
    volumes:
      # the rootless dockerd socket (owned by ci:ci) -> the path DOCKER_HOST expects
      - /run/user/2000/docker.sock:/rootless/docker.sock
```

- [ ] **Step 2: Validate the merged compose**

Run on the Mac:
```bash
cd homelab/services/woodpecker
WOODPECKER_TS_AUTHKEY=x WOODPECKER_GITHUB_CLIENT=x WOODPECKER_GITHUB_SECRET=x WOODPECKER_AGENT_SECRET=x \
  docker compose -f compose.yaml -f compose.picklelab.yaml config -q
```
Expected: no output (valid).

- [ ] **Step 3: Commit**

```bash
git add homelab/services/woodpecker/compose.picklelab.yaml
git commit -m "feat(woodpecker): picklelab overrides (data volumes + rootless socket)"
```

---

## Task 9: systemd unit

(AGENT-RUN.) Models the two-file compose pattern; depends on the ci user's rootless docker being up.

**Files:**
- Create: `homelab/services/woodpecker/woodpecker.service`

- [ ] **Step 1: Write the unit**

```ini
[Unit]
Description=Woodpecker CI (server + agent + tailscale sidecar)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/homelab/homelab/services/woodpecker
ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml up -d --pull always
ExecStop=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml down

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Commit**

```bash
git add homelab/services/woodpecker/woodpecker.service
git commit -m "feat(woodpecker): systemd unit"
```

---

## Task 10: `deploy.sh`

(AGENT-RUN to write; executed on host by the Justfile recipe.) Creates data dirs, pulls images, links + restarts the unit, checks the rootless socket exists, smoke-tests local health.

**Files:**
- Create: `homelab/services/woodpecker/deploy.sh` (executable)

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Deploy Woodpecker CI on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/woodpecker"
DATA_DIR=/srv/data/woodpecker

cd "$REPO_DIR"
echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Checking rootless docker socket for the ci user"
if [ ! -S /run/user/2000/docker.sock ]; then
    echo "ERROR: /run/user/2000/docker.sock missing. Is the ci user's rootless dockerd running?"
    echo "       sudo -iu ci bash -lc 'systemctl --user status docker'"
    exit 1
fi

echo "==> Creating data directories"
sudo mkdir -p "$DATA_DIR/ts-state" "$DATA_DIR/server"
# woodpecker-server and the tailscale sidecar run as root in-container; root-owned dirs are writable.

echo "==> Pulling images"
cd "$SERVICE_DIR"
docker compose -f compose.yaml -f compose.picklelab.yaml pull

echo "==> Linking systemd unit"
sudo ln -sf "$SERVICE_DIR/woodpecker.service" /etc/systemd/system/

echo "==> Reloading systemd and (re)starting service"
sudo systemctl daemon-reload
sudo systemctl enable woodpecker.service
sudo systemctl restart woodpecker.service

echo "==> Status"
systemctl status woodpecker.service --no-pager

echo ""
echo "==> Checking local Woodpecker health endpoint"
for i in 1 2 3 4 5; do
    if curl -sf "http://127.0.0.1:8000/healthz" > /dev/null 2>&1; then
        echo "    Local health check passed"
        break
    fi
    if [ "$i" -eq 5 ]; then
        echo "    WARNING: local health check failed after 5 attempts"
        echo "    Logs: docker compose -f compose.yaml -f compose.picklelab.yaml logs"
        exit 1
    fi
    echo "    Waiting for server to start (attempt $i/5)..."
    sleep 3
done

TAILNET=$(tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix')
echo ""
echo "Done! Woodpecker should be reachable at https://woodpecker.${TAILNET}"
echo "If the funnel hostname does not resolve yet, check: docker compose exec ts-woodpecker tailscale funnel status"
```

- [ ] **Step 2: Make it executable + commit**

```bash
chmod +x homelab/services/woodpecker/deploy.sh
git add homelab/services/woodpecker/deploy.sh
git commit -m "feat(woodpecker): deploy script"
```

---

## Task 11: Justfile recipes (`deploy-woodpecker`, logs, status)

(AGENT-RUN.) Mirrors `deploy-brineworks-server` (git-clean/main/push guard → pull → service-env → scp → remote deploy).

**Files:**
- Modify: `Justfile`

- [ ] **Step 1: Add the recipes**

Add near the other deploy recipes:
```just
deploy-woodpecker host="picklelab":
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
    scripts/service-env homelab/services/woodpecker/.env.vars > tmp/woodpecker.env
    scp tmp/woodpecker.env {{host}}:/opt/homelab/homelab/services/woodpecker/.env
    rm tmp/woodpecker.env
    ssh {{host}} "cd /opt/homelab && homelab/services/woodpecker/deploy.sh"

woodpecker-logs host="picklelab":
    ssh {{host}} "cd /opt/homelab/homelab/services/woodpecker && docker compose -f compose.yaml -f compose.picklelab.yaml logs -f --tail=100"

woodpecker-status host="picklelab":
    ssh {{host}} "systemctl status woodpecker.service --no-pager; echo; cd /opt/homelab/homelab/services/woodpecker && docker compose -f compose.yaml -f compose.picklelab.yaml ps"
```

- [ ] **Step 2: Verify the recipes parse**

Run on the Mac: `just --list | grep woodpecker`
Expected: `deploy-woodpecker`, `woodpecker-logs`, `woodpecker-status` listed.

- [ ] **Step 3: Commit**

```bash
git add Justfile
git commit -m "feat(woodpecker): just deploy/logs/status recipes"
```

---

## Task 12: First deploy + Funnel/OAuth smoke test

(Mix: `just deploy-woodpecker` is AGENT-RUN from Mac; OAuth login + Tailscale service approval are HUMAN-RUN.) Merge the branch to main first (deploy guards require main + pushed).

**Files:** none (deploy + verify).

- [ ] **Step 1: Land the branch on main**

```bash
git checkout main && git merge --ff-only woodpecker-ci-design && git push
```

- [ ] **Step 2: Deploy**

Run on the Mac: `just deploy-woodpecker`
Expected: ends with "Local health check passed" and the reachable-at line.

- [ ] **Step 3: Confirm the sidecar joined the tailnet as `woodpecker`**

Run: `just woodpecker-status` and `ssh picklelab "tailscale status | grep woodpecker"`
Expected: a `woodpecker` node, tagged `tag:ci`. If it shows `woodpecker-1`, the name deduped — check `/srv/data/woodpecker/ts-state` persistence and remove the stale machine in the admin console.

- [ ] **Step 4: Confirm Funnel is serving**

Run: `ssh picklelab "cd /opt/homelab/homelab/services/woodpecker && docker compose -f compose.yaml -f compose.picklelab.yaml exec ts-woodpecker tailscale funnel status"`
Expected: `woodpecker.tail2023b7.ts.net:443` → `http://127.0.0.1:8000`.

- [ ] **Step 5: Log into the UI via GitHub OAuth (HUMAN-RUN)**

Open `https://woodpecker.tail2023b7.ts.net` in a browser, click login, authorize the OAuth App.
Expected: redirect back to `/authorize` succeeds and you land in the Woodpecker UI as an admin. If the callback fails, re-check the OAuth App callback URL is exactly `https://woodpecker.tail2023b7.ts.net/authorize`.

- [ ] **Step 6: Confirm only your repos are listed**

In the UI, Add Repository.
Expected: the repo list is scoped to `technicalpickles` (effect of `WOODPECKER_REPO_OWNERS`). Registration is closed to others (`WOODPECKER_OPEN=false`).

> **Gate:** OAuth login + funnel both working is the foundation. Do not onboard repos until Steps 4 and 5 pass.

---

## Task 13: Onboard brineworks (net-new pipeline)

Do brineworks first — it is net-new (no cutover) and proves the rootless agent end to end. (Enabling the repo + push are done by you; the `.woodpecker.yml` is committed to the brineworks repo, not picklehome.)

**Files:**
- Create (in the **brineworks** repo): `.woodpecker.yml`

- [ ] **Step 1: Confirm the real test-deps install line**

In the brineworks repo (`~/github.com/technicalpickles/pickled-finances`):
```bash
grep -nE "optional-dependencies|dependency-groups|\[project\.optional|pytest" pyproject.toml
```
Determine whether pytest comes from `pip install -e '.[test]'`, `.[dev]`, a PEP 735 dependency group, or is a bare dev dep. Use whatever actually installs pytest in the next step. (If unclear, replicate locally in a clean venv: `python3.11 -m venv /tmp/v && /tmp/v/bin/pip install -e . && /tmp/v/bin/pytest --co -q` and see if it resolves.)

- [ ] **Step 2: Write `.woodpecker.yml`**

```yaml
when:
  - event: [push, pull_request]

steps:
  - name: test
    image: python:3.11
    commands:
      - pip install -e '.[test]'   # REPLACE with the line confirmed in Step 1
      - pytest
```

- [ ] **Step 3: Enable the repo in Woodpecker (HUMAN-RUN)**

In the Woodpecker UI → Add Repository → enable `technicalpickles/brineworks`. This auto-creates the GitHub webhook.

- [ ] **Step 4: Push a branch and confirm a build runs**

Commit `.woodpecker.yml` on a branch, push, open a PR.
Expected: a build appears in the Woodpecker UI and a `ci/woodpecker` (or similar) status appears on the GitHub commit/PR.

- [ ] **Step 5: Confirm the build passes and ran on the rootless daemon**

Expected: green build. Then verify the step container ran on the rootless daemon, not the root one:
```bash
sudo docker ps -a | grep -i wp_   # root daemon: should NOT show woodpecker step containers
sudo -iu ci bash -lc 'export DOCKER_HOST=unix:///run/user/2000/docker.sock; docker ps -a | head'  # rootless: shows recent step containers
```
Expected: step containers appear under the **ci** rootless daemon, confirming isolation is live.

- [ ] **Step 6: Merge**

Merge the PR once green.

---

## Task 14: Onboard pirpg + retire its test workflow (parallel-run cutover)

pirpg already has working Actions CI. Run both in parallel, confirm parity, then delete only `ci.yml` (keep `dependabot-auto-merge.yml` and the shrunken runner — decision B1).

**Files:**
- Create (in the **pirpg** repo): `.woodpecker.yml`
- Delete (in the **pirpg** repo): `.github/workflows/ci.yml`

- [ ] **Step 1: Write `.woodpecker.yml`**

```yaml
when:
  - event: [push, pull_request]

steps:
  - name: check
    image: node:22
    commands:
      - npm ci
      - npx prettier --check .
      - npx tsc --noEmit
      - npm run build
      - npm test
```

- [ ] **Step 2: Enable the repo in Woodpecker (HUMAN-RUN)**

Woodpecker UI → Add Repository → enable `technicalpickles/pirpg`.

- [ ] **Step 3: Push a branch; confirm BOTH checks run in parallel**

Commit `.woodpecker.yml` on a branch, push, open a PR.
Expected: two checks on the PR — `CI` (Actions, from `ci.yml`) and the Woodpecker check. Both should go green.

- [ ] **Step 4: Confirm parity**

Compare: the Woodpecker `check` step runs the same five commands as the Actions `check` job. Confirm prettier/tsc/build/test all pass under Woodpecker.

- [ ] **Step 5: Delete the Actions test workflow**

In the same PR (or a follow-up), `git rm .github/workflows/ci.yml`. Leave `.github/workflows/dependabot-auto-merge.yml` untouched.
Expected after merge: pushes trigger only the Woodpecker check; `dependabot-auto-merge.yml` still targets `[self-hosted, picklelab]`.

- [ ] **Step 6: Confirm dependabot-auto-merge still works**

Confirm the `github-actions-runner` is still running (`just github-runner-status`) and that the next Dependabot PR enables auto-merge as before.
Expected: the runner remains online; the auto-merge workflow is unaffected by removing `ci.yml`.

---

## Task 15: Backup verification, docs, and follow-up task

(AGENT-RUN for docs/task; HUMAN-RUN for the restic check on host.)

**Files:**
- Modify: `homelab/services/README.md` (registry entry)
- Create: `homelab/services/woodpecker/README.md`
- Modify: `homelab/plans/homelab_03_host_setup.md` (rootless-docker-for-ci section)
- Modify: `homelab/README.md` (services table row)

- [ ] **Step 1: Verify Woodpecker data is on the restic path**

Run on picklelab: `ls /srv/data/woodpecker/`
Expected: `server/` and `ts-state/` present (these are under `/srv/data`, already swept nightly). Optionally confirm with `just backup-snapshots` after the next nightly run that the path is captured.

- [ ] **Step 2: Write `homelab/services/woodpecker/README.md`**

Cover (per docs/CONVENTIONS.md — README is reference for users): purpose; the sidecar/Funnel model and `funnel.json`; the rootless `ci`-user isolation and why (link the design doc); the OAuth-App-not-GitHub-App note; secrets/`.env.vars`; deploy/logs/status commands; onboarding a new repo; the dependabot-auto-merge B1 caveat; rebuildable-state recovery story.

- [ ] **Step 3: Add the registry entry to `homelab/services/README.md`**

Add a `### woodpecker` section in the service registry table style (Purpose / Compose / Data / Access / Env vars / Backup / Restart) and a Commands line (`just deploy-woodpecker`, `just woodpecker-logs`, `just woodpecker-status`).

- [ ] **Step 4: Add the rootless-docker section to `homelab_03_host_setup.md`**

Document the one-time host setup from Task 3 (create `ci` uid 2000, install rootless docker, enable linger, the isolation-verification command) so the host is reproducible from bare metal.

- [ ] **Step 5: Add the services-table row to `homelab/README.md`**

Add a `woodpecker` row to the top-level services table linking to the new README.

- [ ] **Step 6: File the dependabot follow-up as a taskwarrior task**

Run on the Mac:
```bash
task add project:picklehome.homelab "Decide pirpg dependabot-auto-merge under Woodpecker: reimplement as Woodpecker pipeline (B2) or drop (B3); currently kept on the shrunken github-actions-runner (B1)"
```

- [ ] **Step 7: Commit the docs**

```bash
git add homelab/services/woodpecker/README.md homelab/services/README.md homelab/plans/homelab_03_host_setup.md homelab/README.md
git commit -m "docs(woodpecker): service README, registry, host-setup, services table"
```

---

## Self-Review notes

- **Spec coverage:** Section 1→Tasks 6-11; Section 2 (Funnel/sidecar)→Tasks 1,2,6,7,12; Section 3 (OAuth/secrets)→Tasks 4,5,7; Section 4 (rootless Option D)→Tasks 3,7,8,13; Section 5 (pipelines)→Tasks 13,14; Section 6 (cutover/B1)→Task 14; Section 7 (backup)→Task 15. All four design "open items" are covered: brineworks test-deps (Task 13 Step 1), userspace-Funnel smoke test (Task 1), fork-PR gate (verify in Woodpecker UI during Task 13/14 — note in README), B2/B3 follow-up task (Task 15 Step 6).
- **Ordering rationale:** de-risk Funnel (1) → tailnet/host/secrets prep (2-5) → build service files (6-11) → deploy+prove foundation (12) → onboard net-new brineworks before touching working pirpg CI (13 before 14) → docs/backup last (15).
- **Note:** `.woodpecker.yml` files for pirpg/brineworks are committed to *those* repos, not picklehome. Everything else lands in picklehome.
