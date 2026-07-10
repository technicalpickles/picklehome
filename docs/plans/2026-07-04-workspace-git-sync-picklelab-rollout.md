# Workspace git-sync rollout to picklelab

**Status:** design, not yet implemented
**Depends on:** [2026-06-30-openclaw-deploy.md](2026-06-30-openclaw-deploy.md) (picklelab OpenClaw deploy, already live)
**Companion:** `pickleclaw`'s `scripts/workspace-git-sync.sh` (committed, already run manually against the dev VM) and its `docs/setup-notes.md` "Workspace git backup" section.

## Problem

`/srv/data/openclaw/workspace` (the agent's identity/memory repo, `openclaw-workspace`) is cloned onto picklelab but nothing keeps it synced with its GitHub remote. Per `homelab/services/openclaw/README.md` line 141, sync is currently manual. Uncommitted local changes and remote-ahead drift just accumulate until someone notices.

`scripts/workspace-git-sync.sh` (already written and committed in `pickleclaw`, proven manually on the dev VM) solves this: commit local changes, `git pull --rebase`, push; on a real rebase conflict, escalate to an LLM (`openclaw agent --model <bigger>`) to resolve it, since conflict resolution needs judgment a plain script shouldn't guess at.

What's missing is *how it runs on a schedule on picklelab* — that's this design.

## Decision: in-container `openclaw cron --command`, git auth via a fine-grained PAT over HTTPS

Two options were considered:

1. **Host systemd timer.** Runs on the picklelab host, reusing the workspace's existing SSH deploy key (`/srv/data/openclaw/ssh/workspace_deploy_key`, already verified working via `git ls-remote`). Escalation reaches into the container via `docker exec openclaw-openclaw-1 openclaw agent ...`.
2. **In-container `openclaw cron --command` job** (chosen). The Gateway's own scheduler runs the sync script directly inside `openclaw-openclaw-1`, no LLM call needed for the common (no-conflict) case. Escalation is a plain in-container `openclaw agent` call — no docker-exec bridge needed, since the job is already inside the container.

Why (1) needs ssh and why that's blocked in-container, and why (2) sidesteps it entirely, is worth being explicit about — this was the crux of the decision:

- The container image (`node:24-bookworm-slim`) has no ssh client (`openssh-client` isn't in the official Dockerfile's apt-install list) and there's no way to add one without a custom image build (compose declares no `build:` key) or runtime `apt-get` (uid 1000, no sudo). So SSH-based git auth is genuinely blocked *inside* the container — this part doesn't change between options.
- Git over **HTTPS doesn't need an ssh client at all** — just the `git` binary (already present) plus credentials. A fine-grained GitHub PAT scoped to just `openclaw-workspace` sidesteps the ssh blocker with zero image changes.
- Once git auth works in-container, running the *whole* sync job (cheap path + escalation) as a native `cron --command` job beats bolting a host-side systemd timer + docker-exec bridge onto it: no new host-side unit files, no cross-process bridge for escalation, and the job becomes visible in `openclaw cron list` / `cron runs` like any other scheduled job on this Gateway.

The tradeoff accepted: a new credential (PAT) to provision, store, and eventually rotate — instead of reusing the already-provisioned SSH deploy key.

## Design

### 1. Credential

A new GitHub **fine-grained PAT**, scoped to only `technicalpickles/openclaw-workspace`, permission **Contents: Read and write**, no other repo access. Provisioned by hand (same operator-places-secrets-directly convention as the existing deploy key — see `pickleclaw`'s CLAUDE.md "Secret hygiene"), landed in `homelab/services/openclaw/.env` as a new plain var, e.g. `OPENCLAW_WORKSPACE_GITHUB_TOKEN`. Unlike the deploy key, no base64 encoding is needed — a PAT is already a single-line string, not a key file with strict permission bits.

### 2. Git auth wiring (idempotent, in `deploy.sh`)

- Point the workspace repo's `origin` remote at the HTTPS form: `https://github.com/technicalpickles/openclaw-workspace.git` (currently the SSH form).
- Hand git the token via a `GIT_ASKPASS` helper script that reads `OPENCLAW_WORKSPACE_GITHUB_TOKEN` from the environment, rather than embedding the token directly in `.git/config`. This keeps the secret in exactly one place (the container's env, same tier `OPENROUTER_API_KEY` already lives at) instead of duplicating it onto disk in a repo file.
- Do this once per deploy, gated so a redeploy doesn't repeatedly rewrite a remote a human may have since touched (mirrors the existing "workspace already cloned, leave it alone" gate).

### 3. Ship the script — no compose changes needed

`compose.picklelab.yaml` already bind-mounts `/srv/data/openclaw/bin:/opt/tools:ro`. Add an `scp` of `pickleclaw`'s `scripts/workspace-git-sync.sh` → `$DATA_DIR/bin/workspace-git-sync.sh` (+ `chmod +x`) to `deploy.sh`. It then appears at `/opt/tools/workspace-git-sync.sh` inside the container, executable, with no new mount.

The script itself needs **no changes** for this environment:
- Its default `WORKSPACE_DIR` (`$HOME/.openclaw/workspace`) already resolves to `/home/node/.openclaw/workspace` in-container — exactly where the workspace is bind-mounted.
- Its escalation call (`openclaw agent --agent main --model "$ESCALATION_MODEL" ...`) already assumes a locally-reachable `openclaw` CLI talking to the local Gateway — true once the job runs inside the container.

### 4. Register the cron job (idempotent, in `deploy.sh`)

```bash
docker exec openclaw-openclaw-1 openclaw cron create "every 1h" \
  --name workspace-git-sync \
  --command "/opt/tools/workspace-git-sync.sh" \
  --command-cwd "/home/node/.openclaw/workspace" \
  --no-deliver
```

Guarded by an `openclaw cron list --json` check for a job named `workspace-git-sync` so redeploys don't create duplicates.

Delivery mode: `--no-deliver` (default recommendation). This is a housekeeping job; `cron runs --id <jobId>` and cron's own failure-alert path give enough visibility without pinging Telegram hourly. Open to revisiting if silent failures turn out to be a problem in practice.

### 5. Register the escalation model

Add `"ollama-cloud/kimi-k2.7-code": {}` to the `agents.defaults.models` batch-json block already in `deploy.sh` (§ "Applying declarative config"). Confirmed live in the `ollama-cloud` catalog on picklelab, but not yet registered — an unregistered `--model` hard-errors (same registration trap documented in `pickleclaw`'s CLAUDE.md).

## Rollout steps

workspace-git-sync-credential: Generate the fine-grained PAT, add `OPENCLAW_WORKSPACE_GITHUB_TOKEN` to `.env.template` + `.env` (`just dotenv`).

workspace-git-sync-remote: Add the idempotent git-remote-to-HTTPS + `GIT_ASKPASS` wiring to `deploy.sh`, gated so it only runs if the remote is still SSH.

workspace-git-sync-script-ship: Add the `scp` + `chmod +x` step for `workspace-git-sync.sh` to `deploy.sh`.

workspace-git-sync-cron-register: Add the guarded `openclaw cron create` step to `deploy.sh`.

workspace-git-sync-model-register: Add `kimi-k2.7-code` to the `agents.defaults.models` batch-json.

workspace-git-sync-deploy: Run `just deploy-openclaw`, confirm each new step's idempotency by running it twice.

workspace-git-sync-verify: Manufacture a real conflict — diverge a line in `AGENTS.md` across two independent clones of `openclaw-workspace`, push one, then run the cron job manually (`docker exec openclaw-openclaw-1 openclaw cron run <jobId> --wait`) against the other's checked-out state:
  - First confirm the **cheap path**: a non-conflicting local change commits, rebases, and pushes with no LLM call.
  - Then confirm **escalation**: a genuine `UU` conflict triggers the `openclaw agent` call, resolves sensibly, and pushes. This is the first real proof that the in-container `openclaw agent` call behaves as expected (wiring was verified this session; the actual LLM turn was not).

workspace-git-sync-docs: Update `homelab/services/openclaw/README.md` (currently says sync is manual) and cross-link from `pickleclaw`'s `docs/setup-notes.md`.

## Open questions

- **Does a real `UU` conflict actually get resolved sensibly by `kimi-k2.7-code` via this path, end to end?** Everything up to the LLM call itself is either already true (script logic, path defaults) or mechanical (cron registration, credential wiring). The one behavioral unknown is the escalation step's real output quality — answered at the verify step above, not before.
- **PAT rotation policy.** Fine-grained PATs can carry an expiration. Decide whether to set one (forces a periodic manual rotation) or leave it non-expiring (matches the existing deploy key's posture, but is a live credential with standing repo write access either way).
- **Should the picklehome README/Justfile's stale `docker exec openclaw` → `openclaw-openclaw-1` container-name reference be fixed as part of this work, or filed separately?** Discovered during the picklelab investigation, not otherwise related to this rollout.
