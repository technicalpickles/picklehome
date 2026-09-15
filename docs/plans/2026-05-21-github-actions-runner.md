# GitHub Actions Self-Hosted Runner on picklelab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a self-hosted GitHub Actions runner on picklelab so pirpg's CI workflow executes against the homelab instead of GitHub-hosted runners. This bypasses the GitHub Actions billing block currently preventing CI on the private pirpg repo.

**Architecture:** Single Docker container (`myoung34/github-runner:latest`), managed by systemd, registered against `technicalpickles/pirpg` with label `picklelab`. Follows the existing picklehome service pattern: layered compose files (`compose.yaml` + `compose.picklelab.yaml`), `.env.vars` for secrets filtering, a `deploy.sh` invoked over SSH by a `just` recipe. Runner is **persistent** (long-running container, sequential jobs) for simplicity - ephemeral can be a future upgrade if isolation becomes important.

**Tech Stack:** Docker + Compose v2, systemd, GitHub Actions self-hosted runner protocol, picklehome's existing 1Password / `.env.vars` / `just deploy-*` pattern.

---

## Prerequisites & Pre-Plan Validation

Run all V-checks before starting Task 1. Any failure means the plan doesn't apply as-written - fix the underlying issue or adjust the plan first.

- [ ] **V1: picklelab is reachable over Tailscale**
  Run: `tailscale ping --c 3 picklelab`
  Expected: 3 replies, latency under 100 ms

- [ ] **V2: SSH to picklelab works passwordlessly**
  Run: `ssh picklelab 'whoami && uname -a && uptime'`
  Expected: prints your user, Linux kernel info, and uptime - no password prompt

- [ ] **V3: Docker and Compose v2 are installed on picklelab**
  Run: `ssh picklelab 'docker --version && docker compose version'`
  Expected: Docker 20.10+, Compose v2.x
  If Compose is v1 (`docker-compose`): upgrade before proceeding - this plan assumes v2 (`docker compose`)

- [ ] **V4: Confirm picklelab hardware reality vs docs**
  Run:
  ```bash
  ssh picklelab 'lscpu | grep -E "Model name|^CPU\(s\)"; free -h | head -2; df -h /'
  ```
  Expected: 4-core CPU (Celeron J3455 or similar), 16 GB RAM, several GB free on `/`
  Note: `homelab/README.md` currently says "4 GB RAM" - Task 7 includes the fix.

- [ ] **V5: Mac has Docker available for the local POC**
  Run: `docker --version && docker info | head -5`
  Expected: any recent Docker version, daemon running
  If fails: install Docker Desktop or Colima before Task 1

- [ ] **V6: `gh` CLI is authenticated against the right account**
  Run: `gh auth status`
  Expected: logged in as `technicalpickles`, has `repo` scope

- [ ] **V7: Confirm pirpg's CI PR is still open**
  Run: `gh pr view 11 --repo technicalpickles/pirpg --json state,headRefName`
  Expected: state OPEN, headRefName `add-ci`
  This plan ends by updating that PR's workflow to use the self-hosted runner.

- [ ] **V8: Decide on registration token approach**
  This plan uses **short-lived registration tokens** (Option A) - fetched fresh from GitHub UI per registration. They expire in ~1 hour but only matter at first registration; the runner stays registered after. Alternative is a PAT with `repo` scope (Option B) - needed for ephemeral runners that re-register every job, but unnecessary for a persistent runner.
  Decision: **Option A (registration token)**. Picked up in Task 1 (POC) and Task 4 (production).

---

## Phase 1: Local Proof-of-Concept

Goal: prove the runner container config works end-to-end against pirpg before investing in homelab service files. Total time estimate: 30 minutes.

### Task 1: Run runner container on Mac and verify it picks up a workflow

**Files:**
- Modify (temporarily, on a throwaway branch in pirpg): `.github/workflows/ci.yml`

- [ ] **Step 1: Get a registration token from GitHub**
  Open https://github.com/technicalpickles/pirpg/settings/actions/runners/new and copy the token (looks like `A1B2C3D4...`). Token is one-time use, ~1 hour TTL.

- [ ] **Step 2: Start the runner container locally**
  Run on your Mac:
  ```bash
  docker run -d --rm \
    --name pirpg-runner-poc \
    -e REPO_URL=https://github.com/technicalpickles/pirpg \
    -e RUNNER_TOKEN=<paste-token-from-step-1> \
    -e RUNNER_NAME=local-poc \
    -e LABELS=self-hosted,local-poc \
    -e RUNNER_SCOPE=repo \
    myoung34/github-runner:latest
  ```

- [ ] **Step 3: Verify runner registered**
  Wait 20 seconds, then run:
  ```bash
  gh api repos/technicalpickles/pirpg/actions/runners \
    --jq '.runners[] | {name, status, labels: [.labels[].name]}'
  ```
  Expected: includes `{"name": "local-poc", "status": "online", "labels": ["self-hosted", "local-poc"]}`
  If not online: `docker logs pirpg-runner-poc` to debug

- [ ] **Step 4: Create a throwaway test branch in pirpg**
  ```bash
  cd /Users/technicalpickles/github.com/technicalpickles/pirpg/.worktrees/add-ci
  git checkout -b poc-self-hosted-test
  ```

- [ ] **Step 5: Point workflow at the local-poc label**
  Edit `.github/workflows/ci.yml`, change:
  ```yaml
  runs-on: ubuntu-latest
  ```
  to:
  ```yaml
  runs-on: [self-hosted, local-poc]
  ```

- [ ] **Step 6: Commit and push the throwaway branch**
  ```bash
  git add .github/workflows/ci.yml
  git commit -m "poc: target local self-hosted runner for testing"
  git push -u origin poc-self-hosted-test
  ```

- [ ] **Step 7: Verify workflow ran on the local runner**
  ```bash
  gh run list --branch poc-self-hosted-test --limit 1 --repo technicalpickles/pirpg
  gh run watch --repo technicalpickles/pirpg
  ```
  Expected: status `queued` → `in_progress` → `completed` (success ideally; even a failure tells us the runner picked it up).
  Also confirm via container logs:
  ```bash
  docker logs --tail 50 pirpg-runner-poc
  ```
  Expected: log lines showing the job being claimed and steps executing.

- [ ] **Step 8: Record observations**
  Note in a scratch file or just remember:
  - Total wall time of CI run on your Mac:
  - Did all 4 steps (prettier, tsc, build, jest) pass?
  - Any surprises (missing tools in image, permission issues, network blockers)?

- [ ] **Step 9: Tear down**
  ```bash
  docker stop pirpg-runner-poc
  git checkout add-ci
  git branch -D poc-self-hosted-test
  git push origin --delete poc-self-hosted-test
  ```
  In GitHub UI: `Settings → Actions → Runners`, click the `local-poc` runner, **Remove**.

- [ ] **Step 10: Decision point**
  - If Task 1 succeeded with no significant issues: proceed to Task 2.
  - If Task 1 had issues (missing tools, network problems, runner crashes): debug and resolve before building the homelab service. Common fixes:
    - Add tools via a custom Dockerfile that extends `myoung34/github-runner`
    - Add network access via the homelab sandbox config (only relevant once on picklelab)

---

## Phase 2: Build the picklehome service

Goal: produce all the files needed to deploy the runner as a picklehome service, following the same pattern as climate-auto-switch and vikunja.

### Task 2: Scaffold service directory

**Files:**
- Create: `homelab/services/github-actions-runner/.env.vars`
- Create: `homelab/services/github-actions-runner/compose.yaml`
- Create: `homelab/services/github-actions-runner/compose.picklelab.yaml`
- Create: `homelab/services/github-actions-runner/github-actions-runner.service`
- Create: `homelab/services/github-actions-runner/deploy.sh`

- [ ] **Step 1: Create the service directory**
  From picklehome repo root:
  ```bash
  mkdir -p homelab/services/github-actions-runner
  ```

- [ ] **Step 2: Write `.env.vars`**
  Path: `homelab/services/github-actions-runner/.env.vars`
  Content:
  ```
  GITHUB_RUNNER_TOKEN
  GITHUB_RUNNER_REPO_URL
  ```

- [ ] **Step 3: Write base `compose.yaml`**
  Path: `homelab/services/github-actions-runner/compose.yaml`
  Content:
  ```yaml
  services:
    github-actions-runner:
      image: myoung34/github-runner:latest
      restart: unless-stopped
      env_file:
        - .env
      environment:
        - REPO_URL=${GITHUB_RUNNER_REPO_URL}
        - RUNNER_TOKEN=${GITHUB_RUNNER_TOKEN}
        - RUNNER_NAME=picklelab
        - RUNNER_SCOPE=repo
        - LABELS=self-hosted,linux,picklelab
      volumes:
        - /var/run/docker.sock:/var/run/docker.sock
        - runner-work:/runner/_work

  volumes:
    runner-work:
  ```

- [ ] **Step 4: Write `compose.picklelab.yaml` overrides**
  Path: `homelab/services/github-actions-runner/compose.picklelab.yaml`
  Content:
  ```yaml
  services:
    github-actions-runner:
      env_file:
        - /opt/homelab/.env
  ```

- [ ] **Step 5: Write the systemd unit**
  Path: `homelab/services/github-actions-runner/github-actions-runner.service`
  Content:
  ```ini
  [Unit]
  Description=GitHub Actions self-hosted runner (pirpg)
  After=network-online.target docker.service
  Wants=network-online.target
  Requires=docker.service

  [Service]
  Type=oneshot
  RemainAfterExit=yes
  WorkingDirectory=/opt/homelab/homelab/services/github-actions-runner
  ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml up -d --pull always
  ExecStop=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml down

  [Install]
  WantedBy=multi-user.target
  ```

- [ ] **Step 6: Write `deploy.sh`**
  Path: `homelab/services/github-actions-runner/deploy.sh`
  Content:
  ```bash
  #!/usr/bin/env bash
  # Deploy github-actions-runner on picklelab.
  # Idempotent: safe to run on first setup or any subsequent deploy.
  # Run from the repo root on the target host.
  set -euo pipefail

  REPO_DIR=/opt/homelab
  SERVICE_DIR="$REPO_DIR/homelab/services/github-actions-runner"

  cd "$REPO_DIR"

  echo "==> Deploying commit $(git rev-parse --short HEAD)"

  echo "==> Pulling runner image"
  cd "$SERVICE_DIR"
  docker compose -f compose.yaml -f compose.picklelab.yaml pull

  echo "==> Linking systemd unit"
  sudo ln -sf "$SERVICE_DIR/github-actions-runner.service" /etc/systemd/system/

  echo "==> Reloading systemd and (re)starting service"
  sudo systemctl daemon-reload
  sudo systemctl enable github-actions-runner.service
  sudo systemctl restart github-actions-runner.service

  echo "==> Status"
  systemctl status github-actions-runner.service --no-pager
  ```

- [ ] **Step 7: Make `deploy.sh` executable**
  ```bash
  chmod +x homelab/services/github-actions-runner/deploy.sh
  ```

- [ ] **Step 8: Verify locally that compose parses**
  ```bash
  cd homelab/services/github-actions-runner
  GITHUB_RUNNER_TOKEN=dummy GITHUB_RUNNER_REPO_URL=dummy docker compose -f compose.yaml config > /dev/null
  cd ../../..
  ```
  Expected: no errors. (Compose just validates the file - it won't try to pull yet.)

- [ ] **Step 9: Commit**
  ```bash
  git add homelab/services/github-actions-runner/
  git commit -m "feat(homelab): scaffold github-actions-runner service"
  ```

### Task 3: Add Justfile deploy recipe

**Files:**
- Modify: `Justfile` (top-level)

- [ ] **Step 1: Locate the climate deploy recipe for reference**
  ```bash
  grep -n "^deploy-climate" Justfile
  ```
  Note the line number to find a good spot to add the new recipe.

- [ ] **Step 2: Append `deploy-github-runner` recipe to `Justfile`**
  Add (after the climate recipes is a natural spot):
  ```just
  # Deploy github-actions-runner to picklelab
  deploy-github-runner host="picklelab":
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
      echo "==> Copying .env to {{host}}"
      mkdir -p tmp
      scripts/service-env homelab/services/github-actions-runner/.env.vars > tmp/github-actions-runner.env
      scp tmp/github-actions-runner.env {{host}}:/opt/homelab/homelab/services/github-actions-runner/.env
      rm tmp/github-actions-runner.env
      ssh {{host}} "cd /opt/homelab && git pull && homelab/services/github-actions-runner/deploy.sh"

  # Tail github-actions-runner logs on picklelab
  github-runner-logs host="picklelab":
      ssh {{host}} "docker logs --tail 100 -f \$(docker ps -q --filter name=github-actions-runner)"

  # Show runner status on picklelab
  github-runner-status host="picklelab":
      ssh {{host}} "systemctl status github-actions-runner.service --no-pager && docker ps --filter name=github-actions-runner"
  ```

- [ ] **Step 3: Verify the recipes parse**
  ```bash
  just --list 2>&1 | grep -E "github-runner|deploy-github"
  ```
  Expected: shows all three recipes (`deploy-github-runner`, `github-runner-logs`, `github-runner-status`)

- [ ] **Step 4: Commit**
  ```bash
  git add Justfile
  git commit -m "feat(homelab): add deploy-github-runner Justfile recipes"
  ```

### Task 4: Add secrets to 1Password and `.env.template`

**Files:**
- Modify: `.env.template`

- [ ] **Step 1: Get a fresh registration token**
  Open https://github.com/technicalpickles/pirpg/settings/actions/runners/new (must be a different token than Task 1 used; that one was for `local-poc`).
  Copy the token.

- [ ] **Step 2: Create the 1Password item**
  - Vault: `picklehome`
  - Type: API Credential (or generic Password)
  - Title: `GitHub Actions Runner (pirpg)`
  - Fields:
    - `token` (concealed): the registration token from Step 1
    - `repo_url`: `https://github.com/technicalpickles/pirpg`

- [ ] **Step 3: Verify the item via `op`**
  ```bash
  op item get "GitHub Actions Runner (pirpg)" --vault picklehome --format json \
    | jq '[.fields[] | {label, id}]'
  ```
  Expected: lists `token` and `repo_url` (plus default fields like `notesPlain`)

- [ ] **Step 4: Add references to `.env.template`**
  Append (in a sensible spot near other homelab service secrets):
  ```
  # GitHub Actions self-hosted runner (pirpg)
  GITHUB_RUNNER_TOKEN={{ op://picklehome/GitHub Actions Runner (pirpg)/token }}
  GITHUB_RUNNER_REPO_URL={{ op://picklehome/GitHub Actions Runner (pirpg)/repo_url }}
  ```

- [ ] **Step 5: Regenerate local `.env`**
  ```bash
  just dotenv
  ```
  Expected: no errors; `.env` now contains the two new vars

- [ ] **Step 6: Verify `service-env` filter works for the new service**
  ```bash
  scripts/service-env homelab/services/github-actions-runner/.env.vars
  ```
  Expected: outputs `GITHUB_RUNNER_TOKEN=...` and `GITHUB_RUNNER_REPO_URL=...` lines with actual values

- [ ] **Step 7: Commit**
  ```bash
  git add .env.template
  git commit -m "feat(homelab): add github-actions-runner secrets to env template"
  ```

---

## Phase 3: Deploy and Validate on picklelab

### Task 5: First deploy

- [ ] **Step 1: Push picklehome to origin/main**
  ```bash
  git push origin main
  ```

- [ ] **Step 2: Run the deploy recipe**
  ```bash
  just deploy-github-runner
  ```
  Expected: completes with `Active: active (exited)` (correct for `Type=oneshot RemainAfterExit=yes`).

- [ ] **Step 3: Verify container is running on picklelab**
  ```bash
  just github-runner-status
  ```
  Expected: systemd unit active; `docker ps` shows the runner container in `Up` state.

- [ ] **Step 4: Verify runner registered with GitHub**
  ```bash
  gh api repos/technicalpickles/pirpg/actions/runners \
    --jq '.runners[] | {name, status, labels: [.labels[].name]}'
  ```
  Expected: includes `{"name": "picklelab", "status": "online", "labels": ["self-hosted", "linux", "picklelab"]}`

- [ ] **Step 5: Check container logs for healthy startup**
  ```bash
  just github-runner-logs
  ```
  Expected (Ctrl-C to exit): log lines ending in `Listening for Jobs` (or similar). No error stack traces.

- [ ] **Step 6: Smoke-test from GitHub side - manually dispatch a no-op**
  Optional: create a tiny workflow_dispatch in pirpg that echoes hello, target `[self-hosted, picklelab]`, run it, see it complete. Skip if you're confident from Task 1's POC.

---

## Phase 4: Switch pirpg to the homelab runner

### Task 6: Update pirpg workflow

**Files (pirpg repo):**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Switch to the pirpg add-ci worktree**
  ```bash
  cd /Users/technicalpickles/github.com/technicalpickles/pirpg/.worktrees/add-ci
  ```

- [ ] **Step 2: Update the `runs-on` line**
  Edit `.github/workflows/ci.yml`, change:
  ```yaml
  runs-on: ubuntu-latest
  ```
  to:
  ```yaml
  runs-on: [self-hosted, picklelab]
  ```

- [ ] **Step 3: Commit and push**
  ```bash
  git add .github/workflows/ci.yml
  git commit -m "ci: target self-hosted picklelab runner"
  git push
  ```

- [ ] **Step 4: Watch the workflow run on picklelab**
  ```bash
  gh run watch --repo technicalpickles/pirpg
  ```
  Expected: job picked up by `picklelab` runner; completes (success ideally; may take 5-8 minutes for the slower CPU).
  If it fails or hangs: `just github-runner-logs` for the runner side; `gh run view --log-failed` for the workflow side.

- [ ] **Step 5: Record actual wall time**
  Note total CI wall time on picklelab. This is the baseline for future "is it slower than usual?" comparisons.

- [ ] **Step 6: Merge PR #11**
  Once green:
  ```bash
  gh pr merge 11 --squash --repo technicalpickles/pirpg
  ```
  (Or merge through the UI.)

---

## Phase 5: Documentation

### Task 7: Update homelab docs

**Files (picklehome repo):**
- Create: `homelab/services/github-actions-runner/README.md`
- Modify: `homelab/README.md` (services list + RAM line)

- [ ] **Step 1: Write the service README**
  Path: `homelab/services/github-actions-runner/README.md`
  Content:
  ```markdown
  # github-actions-runner

  Self-hosted GitHub Actions runner registered against `technicalpickles/pirpg`.
  Runs in a Docker container under systemd. Labels: `self-hosted, linux, picklelab`.

  Built to avoid GitHub Actions billing on the private pirpg repo. Workflows in
  pirpg target this runner via `runs-on: [self-hosted, picklelab]`.

  ## Deploy

  ```bash
  just deploy-github-runner
  ```

  ## Logs

  ```bash
  just github-runner-logs
  ```

  ## Status

  ```bash
  just github-runner-status
  ```

  ## Re-registration

  Registration tokens expire ~1 hour after creation, but only matter at first
  registration. If the runner falls off (long downtime, container reset, repo
  rename), fetch a fresh token from
  https://github.com/technicalpickles/pirpg/settings/actions/runners/new, update
  the 1Password item `GitHub Actions Runner (pirpg)` → `token`, then redeploy:

  ```bash
  just dotenv         # pull updated secrets
  just deploy-github-runner
  ```
  ```

- [ ] **Step 2: Update `homelab/README.md` services list**
  Add a section (alphabetical order, between `climate-auto-switch` and `obsidian-sync` or wherever fits):
  ```markdown
  ### github-actions-runner

  Self-hosted GitHub Actions runner for `technicalpickles/pirpg`. Bypasses GitHub
  Actions billing on the private repo. See
  [../services/github-actions-runner/README.md](../services/github-actions-runner/README.md).

  **Deploy updates (from Mac):**

  ```bash
  just deploy-github-runner
  ```
  ```

- [ ] **Step 3: Fix the stale RAM line in `homelab/README.md`**
  Find the line that says `4 GB RAM` (in the opening "Single Intel NUC..." paragraph). Change `4 GB RAM` to the actual amount confirmed in V4 (likely `16 GB RAM`).

- [ ] **Step 4: Commit and push**
  ```bash
  git add homelab/README.md homelab/services/github-actions-runner/README.md
  git commit -m "docs(homelab): add github-actions-runner README; correct picklelab RAM"
  git push
  ```

---

## Out of scope (future considerations)

- **Ephemeral runners.** Current setup keeps a long-lived container. For better isolation between jobs, switch to ephemeral (container exits after each job, fresh workspace). Requires a PAT with `repo` scope so the container can re-register itself on restart. Not needed for solo private-repo work.
- **Concurrent runners.** Currently one job at a time. To run jobs in parallel, scale via compose `deploy.replicas` or by running multiple compose stacks with different runner names.
- **Org-level runners.** Could be shared across multiple repos by registering at the org level instead of repo level. Single repo is simpler today.
- **Caching strategy.** GitHub Actions cache (the `actions/cache` action) works on self-hosted runners but round-trips to GitHub. On a persistent runner, local `~/.npm` persists across jobs for free - usually faster.
- **Auto-update runner agent.** `--pull always` in the systemd unit pulls the latest `myoung34/github-runner` image on each restart, which contains the latest GitHub runner agent. No manual updates needed.

---

## Self-review notes

- **Spec coverage:** All asks - validation up front, local POC before deploy, fits picklehome service pattern, plan covers both repos - have tasks.
- **Placeholder check:** No "TBD" or "implement later". Every code block contains the actual file content.
- **Type/name consistency:** `GITHUB_RUNNER_TOKEN` / `GITHUB_RUNNER_REPO_URL` env var names used identically across `.env.vars`, `compose.yaml`, `.env.template`, and 1Password references. Runner name `picklelab` matches the label used in pirpg's `runs-on`. POC uses different name (`local-poc`) and label (`local-poc`) to avoid colliding with the production runner.
- **Multi-repo nature:** Plan touches both picklehome (Tasks 2-5, 7) and pirpg (Tasks 1, 6). Each task explicitly names which repo. The pirpg side is intentionally small - just two workflow edits (POC temp + final switch).
