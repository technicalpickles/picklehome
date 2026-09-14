# Homelab Service Deploy Redesign: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current "Mac materializes `.env`, scp's it to picklelab" deploy flow with a host-side 1Password `op run` secrets model driven by a single remote `ssh` call, and move the two extractable services (`second-brain-agent`, `homelab/dev`) plus the two split-repo apps' compose ownership (`brineworks-server`/`brineworks-agent`, `nikke`) out of picklehome where they don't belong.

**Architecture:** Every `homelab/services/<name>/deploy.sh` currently depends on a `.env` file scp'd from the Mac. That file goes away entirely. Instead, two read-only 1Password service-account tokens live on picklelab (`/etc/opt/homelab/op-token-{picklehome,pickleclaw}`, 0600), and each service's systemd unit wraps its `docker compose up` in `op run --env-file=<filtered-template>`, resolving secrets straight from 1Password at container-start time — no secret ever touches disk on picklelab or the Mac. `scripts/service-env` gains a template-filtering mode that turns the committed `.env.template` (safe, `op://`-reference-only) into a per-service filtered copy in the same op-run-compatible syntax. Once no `.env` needs scp'ing, `just deploy-<service>` on the Mac collapses to one `ssh picklelab "cd /opt/homelab && git pull && homelab/services/<name>/deploy.sh"` call, matching the pattern `climate-auto-switch`/`github-actions-runner`/etc. already use for their ssh step (they just don't have the scp yet removed). Repo-ownership moves (extracting `second-brain-agent` and `homelab/dev`, and relocating `brineworks`/`nikke`'s `compose.yaml` to their own repos) are orthogonal to the secrets/execution work and land as a separate wave after the secrets model is proven on at least two services, so a bad extraction doesn't block the secrets rollout or vice versa.

**Tech Stack:** Bash (`deploy.sh`, `Justfile` recipes via `just`), Docker Compose, systemd, 1Password CLI (`op`) service accounts, Tailscale Services.

**Spec:** [docs/plans/2026-08-10-homelab-service-deploy-design.md](../../plans/2026-08-10-homelab-service-deploy-design.md), sections 1-3 only (repo/compose ownership, deploy execution model, secrets injection). Section 3a (Automic Vault, Mac-side dev secrets) and section 5 (further deploy.sh app/host split) are explicitly out of scope for this plan — see that doc's "Open questions for implementation planning."

## Global Constraints

- No secret may be written to disk on picklelab or the Mac at any point in the new flow — this is the entire point of the redesign. If a task's verification step finds a resolved secret value in a file (not an `op://` reference), that task is not done.
- Each service-account token is read-only and scoped to exactly one 1Password vault (`picklehome` or `Brent Pickleclaw`). Never request write access when minting a token.
- `.env.template` stays the single source of truth for which secrets exist (unchanged from today) — the filtered per-service templates are always derived from it, never hand-maintained separately.
- Every migrated service must still pass its own existing health-check verification in `deploy.sh` (curl loops, `systemctl status`, etc.) after migration — the redesign changes *how* secrets arrive, not what the service does with them.
- Don't touch `climate-auto-switch`'s repo location or `homelab/services/backup`'s mechanism beyond the secrets-injection change — both are explicitly staying in picklehome per the design doc, and `backup` has no `docker compose`/systemd-unit-wrapping angle (it runs restic directly under a dedicated system user), so its secrets migration looks different from the others (see Task 11).
- `nikke` has no `.env.vars` and no secrets today — its task is execution-model-only, don't invent a secrets requirement for it.

---

## File Structure

**picklehome (this repo):**

| File | Change |
|---|---|
| `scripts/service-env` | Gains a `--template <path> --op-run` mode alongside the existing `.env`-filtering mode |
| `homelab/services/<name>/<name>.service` (each migrated service) | `ExecStart=`/`ExecStop=` gain an `op run --env-file=...` wrapper; `EnvironmentFile=` gains the token file |
| `homelab/services/<name>/deploy.sh` (each migrated service) | Drop any logic that assumes a `.env` file already exists in `$SERVICE_DIR`; write the filtered op-run template instead |
| `homelab/services/<name>/.env.vars` | Unchanged in content, but now also consumed by the new template-filtering mode |
| `Justfile` | New shared recipe `_deploy-remote`; every `deploy-<service>` recipe shrinks to a one-line call into it; `scripts/dotenv`/`just dotenv` remain for **local Mac dev** use only, no longer load-bearing for deploys |
| `homelab/services/README.md` | Deployment-pattern section rewritten: no more "scp filtered `.env`" step; document the token files and the new `.env.vars` → filtered-template flow |
| `homelab/services/second-brain-agent/` | Deleted after Task 12 (extracted) except systemd unit, `deploy.sh`, `.env.vars`, README pointer |
| `homelab/dev/` | Deleted after Task 13 (extracted) except `deploy.sh`, README pointer |
| `homelab/services/brineworks-server/compose.yaml`, `homelab/services/brineworks-agent/compose.yaml` | Deleted after Task 14 (moved to `brineworks` repo); `compose.picklelab.yaml` stays |
| `homelab/services/nikke/compose.yaml` | Deleted after Task 15 (moved to `nikke-roster-scanner` repo); `compose.picklelab.yaml` stays |

**picklelab (host, not a repo — changes applied over ssh):**

| Path | Change |
|---|---|
| `/etc/opt/homelab/op-token-picklehome`, `/etc/opt/homelab/op-token-pickleclaw` | New, 0600, `OP_SERVICE_ACCOUNT_TOKEN=ops_...` each |
| `/usr/bin/op` (or wherever the Linux `op` CLI lands) | New, installed as part of Task 1 |

**`brineworks` repo** (`~/github.com/technicalpickles/brineworks`, already cloned): gains `compose.yaml` (moved from picklehome) in Task 14.

**`nikke-roster-scanner` repo** (`~/github.com/technicalpickles/nikke-roster-scanner`, already cloned): gains `compose.yaml` (moved from picklehome) in Task 15.

**New repos:** `technicalpickles/second-brain-agent` (Task 12), `technicalpickles/homelab-dev` (Task 13) — both private, created fresh, no existing clone.

---

## Task 1: Validate `op run` + service-account behavior on picklelab (spike)

> **Findings (2026-09-14):**
> (a) `op service-account create <name> --vault <vault>:read_items --raw` is the real, current syntax (confirmed via `op service-account create --help` and two successful real invocations, one per vault — `Brent Pickleclaw` needs quoting around the vault name for the space). `--raw` prints only the bare token, nothing else.
> (b) `op run --env-file` wants bare `KEY=op://vault/item/field` lines — **no** `{{ }}` mustache wrapping (that syntax is `op inject`-only). Confirmed live: `HOME_LAT=op://picklehome/Home/latitude` resolved correctly. This settles Task 3's `--strip-mustache` design as necessary and correct.
> (c) Bad/invalid token fails loud: exit code 1, with `op`'s CLI printing a client-side SDK decode error (`failed to DecodeSACredentials`) rather than a server-rejection message — the exact wording differs from what might be expected (a "bad token" test with a well-formed-but-revoked token might produce a different message than the malformed `ops_invalid` placeholder used here), but the important property holds: nonzero exit, wrapped command never runs, no silent empty-env success.
> (d) Install command confirmed for Ubuntu 24.04.4 LTS (picklelab's actual OS): `curl -sS https://downloads.1password.com/linux/debian/amd64/stable/1password-cli-amd64-latest.deb -o /tmp/op.deb && sudo apt-get install -y /tmp/op.deb` — **not** `dpkg -i`, which isn't in picklelab's passwordless sudoers list (`apt-get install *` is). `op` 2.39.0 is now installed on picklelab.
> (e) Process note: verifying `op run` against the placed token files required real interactive `sudo` (the token files are correctly `0600 root:root`, unreadable by the non-root deploy user an agent session runs as) — done via a single script scp'd to picklelab and run with `ssh -t` so `sudo` had a pty to prompt on. `homelab/services/README.md`'s systemd-unit approach doesn't hit this at all, since `EnvironmentFile=` is read by `systemd` itself (root), not by a shell needing its own `sudo`.

This is the design doc's own explicit prerequisite ("Validate before writing the plan") — it wasn't done before the doc was written, so it's the first task here instead. Everything downstream assumes the answers this task produces.

**Files:** none changed yet — this is pure investigation, done live against picklelab. Record findings in this plan file's Task 1 notes (edit this file, add a `> Findings:` blockquote under this task) before moving on, so this plan isn't itself stale the moment the CLI's real behavior turns out to differ from what's assumed below.

- [ ] **Step 1: Mint one read-only service-account token scoped to the `picklehome` vault.**

  Try the CLI first: `op service-account create --help` (run this locally, where `op` already works per `scripts/dotenv`) to see the exact current flags — 1Password's CLI syntax for service accounts has changed across versions before, don't trust a remembered invocation. Expect something in the shape of a name, `--vault picklehome:read_items`, and an expiry. If the CLI path isn't available on this account's plan tier, use the web console instead: https://my.1password.com → sidebar → "Service Accounts" (or the Business console's equivalent) → New Service Account → grant read-only access to the `picklehome` vault only.

  Capture the token (`ops_...`) exactly once — 1Password only shows it at creation time.

- [ ] **Step 2: Install the Linux `op` CLI on picklelab, confirm which install path.**

  ```bash
  ssh picklelab "curl -sS https://downloads.1password.com/linux/debian/amd64/stable/1password-cli-amd64-latest.deb -o /tmp/op.deb && sudo dpkg -i /tmp/op.deb && op --version"
  ```

  (Adjust the URL/package format if picklelab isn't Debian-based — confirm with `ssh picklelab "cat /etc/os-release"` first if unsure. Record the actual command that worked.)

- [ ] **Step 3: Place the token file and test a one-variable `op run`.**

  ```bash
  ssh picklelab "sudo mkdir -p /etc/opt/homelab && echo 'OP_SERVICE_ACCOUNT_TOKEN=ops_...' | sudo tee /etc/opt/homelab/op-token-picklehome >/dev/null && sudo chmod 600 /etc/opt/homelab/op-token-picklehome"
  ssh picklelab "cat > /tmp/test.env.template <<'EOF'
  HOME_LAT=op://picklehome/Home/latitude
  EOF
  set -a; source /etc/opt/homelab/op-token-picklehome; set +a
  op run --env-file=/tmp/test.env.template -- env | grep HOME_LAT"
  ```

  Expected: prints `HOME_LAT=<real value>`. This also answers the syntax question: `op run --env-file` wants bare `KEY=op://vault/item/field` lines, **not** the `{{ op://... }}` mustache wrapping `.env.template` uses for `op inject`. Confirm this by testing both forms if there's any doubt — don't assume, this plan's Task 2 depends on knowing which syntax is real.

- [ ] **Step 4: Confirm the failure mode for a bad/revoked token.**

  ```bash
  ssh picklelab "OP_SERVICE_ACCOUNT_TOKEN=ops_invalid op run --env-file=/tmp/test.env.template -- env"
  echo "exit code: $?"
  ```

  Expected: nonzero exit, loud error, **not** a silently-empty environment reaching the wrapped command. If `op run` instead runs the command with the var simply missing, that's a real problem (a container could start with an empty required secret) — note it as a blocker and stop to discuss before Task 2, since the whole design leans on "fails loud" being true.

- [ ] **Step 5: Clean up the spike artifacts and record findings.**

  ```bash
  ssh picklelab "rm -f /tmp/test.env.template /tmp/op.deb"
  ```

  Edit this plan file: add a `> Findings:` note under this task's header recording (a) the exact `op service-account create` invocation or console steps that worked, (b) the confirmed `op run --env-file` line syntax, (c) the confirmed failure-mode behavior, (d) the exact `op` install command for picklelab's actual OS. Commit this plan update on its own before starting Task 2.

## Task 2: Mint and place the second (`Brent Pickleclaw`) token

Same as Task 1 Steps 1 and 3, for the vault openclaw/open-webui need, done once Task 1's method is proven.

**Files:** none in this repo.

- [ ] **Step 1: Mint a read-only service-account token scoped to the `Brent Pickleclaw` vault**, using whichever method Task 1 confirmed works.
- [ ] **Step 2: Place it on picklelab.**

  ```bash
  ssh picklelab "echo 'OP_SERVICE_ACCOUNT_TOKEN=ops_...' | sudo tee /etc/opt/homelab/op-token-pickleclaw >/dev/null && sudo chmod 600 /etc/opt/homelab/op-token-pickleclaw"
  ```

- [ ] **Step 3: Verify it resolves a known Brent-Pickleclaw-vault secret.**

  ```bash
  ssh picklelab "cat > /tmp/test2.env.template <<'EOF'
  OLLAMA_API_KEY=op://Brent Pickleclaw/fq45ph3greaikwivmta54w26wq/credential
  EOF
  set -a; source /etc/opt/homelab/op-token-pickleclaw; set +a
  op run --env-file=/tmp/test2.env.template -- env | grep OLLAMA_API_KEY
  rm /tmp/test2.env.template"
  ```

  Expected: prints the real key. If the vault name with a space needs quoting differently than shown here, that's exactly the kind of thing to nail down now, not mid-rollout.

## Task 3: Add op-run template-filtering mode to `scripts/service-env`

**Files:**
- Modify: `scripts/service-env`
- Test: manual invocation (this repo has no test suite for shell scripts under `scripts/`; verify by running it, per existing convention — see `docs/CONVENTIONS.md`)

**Interfaces:**
- Consumes: a service's `.env.vars` file (existing format, unchanged), `.env.template` (existing format, unchanged)
- Produces: a filtered template file with lines in `KEY=op://vault/item/field` form (no `{{ }}`), suitable for `op run --env-file=`

- [ ] **Step 1: Add the new mode.**

  Extend `scripts/service-env` with a `--template <path>` flag that switches its source file (default stays `.env`, so the existing scp-based callers — until they're migrated in later tasks — keep working unchanged) and a `--strip-mustache` flag that, when the source is a template, strips the `{{ ` / ` }}` wrapper from each matched line before printing it:

  ```bash
  # in scripts/service-env, after the existing arg-parsing block:
      case "$1" in
          --env) ENV_FILE="$2"; shift 2 ;;
          --template) ENV_FILE="$2"; STRIP_MUSTACHE=1; shift 2 ;;
          -*) echo "Unknown argument: $1" >&2; exit 1 ;;
          *) VARS_FILE="$1"; shift ;;
      esac
  ```

  And in the extraction loop, when `STRIP_MUSTACHE=1`, post-process each matched line:

  ```bash
      match=$(grep -m1 "^${key}=" "$ENV_FILE" || true)
      if [[ -n "$match" ]]; then
          if [[ "${STRIP_MUSTACHE:-0}" -eq 1 ]]; then
              # KEY={{ op://vault/item/field }}  ->  KEY=op://vault/item/field
              match=$(echo "$match" | sed -E 's/\{\{[[:space:]]*(.*[^[:space:]])[[:space:]]*\}\}/\1/')
          fi
          echo "$match"
      fi
  ```

  `STRIP_MUSTACHE` needs `declare`-ing near the top alongside `VARS_FILE`/`ENV_FILE` so it's not unbound under `set -u`.

- [ ] **Step 2: Verify against a known service.**

  ```bash
  scripts/service-env homelab/services/climate-auto-switch/.env.vars --template .env.template
  ```

  Expected output: lines like `HOME_LAT=op://picklehome/Home/latitude`, `ECOBEE_API_KEY=op://picklehome/Ecobee/api_key` — bare `op://` refs, no mustache, no resolved secret values. Confirm no line contains an actual secret (it shouldn't — the source is `.env.template`, which only ever holds references).

- [ ] **Step 3: Commit.**

  ```bash
  git add scripts/service-env
  git commit -m "feat(scripts): add op-run template mode to service-env"
  ```

## Task 4: Worked example — migrate `climate-auto-switch` (no local dev secrets complexity, already single-ssh-call)

Smallest possible diff: this service already uses the single-ssh-call Justfile pattern (`git pull && deploy.sh` in one `ssh`), so this task isolates *just* the secrets-mechanism change without also touching the execution-model shape.

> **Revised 2026-09-14, before implementation — real finding from the first implementer dispatch (BLOCKED, no commits):** the brief below originally assumed the systemd unit or `deploy.sh` reads `.env` directly. Neither does. The actual current mechanism is `compose.yaml`'s `env_file: - .env` directive, which docker compose reads as a **literal file path** — completely independent of the process environment `op run` populates. Wrapping `ExecStart` in `op run` alone is inert: compose would fail hard with `env file .env not found` the moment `deploy.sh` stops writing that file, verified live by the implementer via `docker compose run` against a missing `env_file` target. The fix is to convert `climate-auto-switch`'s `env_file:` entries to bare `environment:` entries with `${VAR:?required}` interpolation instead — that form **does** read from the process environment `op run` sets up, matching the pattern `taskchampion-sync`/`openclaw`/`open-webui`'s compose files already use today (confirmed: those three, plus `second-brain-agent`, already use `environment: ${VAR:?required}` for their secrets and need **no** compose changes in Task 7). Checked which of the remaining services this affects: **`climate-auto-switch`, `brineworks-server`, `brineworks-agent`, `github-actions-runner`, `woodpecker`** all currently use `env_file: - .env` for secrets and need the same conversion (folded into Task 5 for brineworks-server, and called out per-service in Task 7 for the rest). `nikke`'s `env_file:` usage is build metadata (`.env.build`) only, unaffected.
>
> Also discovered while investigating: `compose.picklelab.yaml` for both `climate-auto-switch` and `brineworks-server` additionally declares `env_file: - /opt/homelab/.env` — a **repo-root-level** `.env` that no current Justfile recipe or `deploy.sh` writes. It exists on picklelab today (`ssh picklelab "ls -la /opt/homelab/.env"` → a real file, `-rw-------`, dated well before this plan) but nothing in the tracked tooling explains how it got there or keeps it current — almost certainly a stale artifact predating the per-service `.env.vars` filtering scheme. Once `climate-auto-switch`/`brineworks-server` declare their real vars via `environment:` (this task and Task 5), that `env_file: - /opt/homelab/.env` line becomes dead weight — remove it as part of each task's compose edit. **Flagging to the human separately: an unrotated, untracked root `.env` sitting on a production host for months is worth its own look independent of this plan** (what's in it, is any of it stale/leaked, should it just be deleted now) — not blocking this task, but don't let it get lost.

**Files:**
- Modify: `homelab/services/climate-auto-switch/climate-auto-switch.service`
- Modify: `Justfile` (`deploy-climate` recipe, ~line 138)
- Modify: `homelab/services/climate-auto-switch/deploy.sh` (Step 1 first confirms it doesn't already reference `.env`, Step 3 adds the filtered-template write)
- Modify: `homelab/services/climate-auto-switch/compose.yaml` (convert `env_file: - .env` to explicit `environment:` entries for all 8 `.env.vars` — see revised Step 2 below)
- Modify: `homelab/services/climate-auto-switch/compose.picklelab.yaml` (drop the `env_file: - /opt/homelab/.env` line entirely)

- [ ] **Step 1: Check whether `deploy.sh` or the systemd unit currently reads `.env`.**

  ```bash
  grep -n "\.env" homelab/services/climate-auto-switch/climate-auto-switch.service homelab/services/climate-auto-switch/deploy.sh
  ```

  Confirmed (2026-09-14): this returns nothing. The unit's actual current shape is:

  ```ini
  [Service]
  Type=oneshot
  TimeoutStartSec=300
  WorkingDirectory=/opt/homelab/homelab/services/climate-auto-switch
  ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml run --rm climate-auto-switch
  ```

  No `EnvironmentFile=` line to begin with — don't go looking for one to replace, just add what Step 2 below specifies.

- [ ] **Step 1a: Convert `compose.yaml`'s `env_file:` to `environment:` entries.**

  Current `homelab/services/climate-auto-switch/compose.yaml`:

  ```yaml
  services:
    climate-auto-switch:
      build: ...
      env_file:
        - .env
      environment:
        - ECOBEE_TOKEN_PATH=/data/ecobee-tokens.json
        - CLIMATE_DATA_DIR=/data
  ```

  New:

  ```yaml
  services:
    climate-auto-switch:
      build: ...
      environment:
        - ECOBEE_TOKEN_PATH=/data/ecobee-tokens.json
        - CLIMATE_DATA_DIR=/data
        - HOME_LAT=${HOME_LAT:?required}
        - HOME_LON=${HOME_LON:?required}
        - AMBIENT_STATION_MACS=${AMBIENT_STATION_MACS:?required}
        - ECOBEE_API_KEY=${ECOBEE_API_KEY:?required}
        - BLUEAIR_USERNAME=${BLUEAIR_USERNAME:?required}
        - BLUEAIR_PASSWORD=${BLUEAIR_PASSWORD:?required}
        - BLUEAIR_REGION=${BLUEAIR_REGION:?required}
        - GOOGLE_POLLEN_API_KEY=${GOOGLE_POLLEN_API_KEY:?required}
  ```

  (the 8 vars are exactly `.env.vars`'s list — cross-check, don't hand-copy from memory). `:?required` matches the convention `taskchampion-sync`/`openclaw` compose files already use, so a missing var fails compose's own config-load step loudly rather than starting a container with an empty value.

- [ ] **Step 1b: Drop the stale `env_file:` line from `compose.picklelab.yaml`.**

  Remove the `env_file: - /opt/homelab/.env` entry from `homelab/services/climate-auto-switch/compose.picklelab.yaml` entirely, leaving the `volumes:` block untouched.

- [ ] **Step 2: Wrap the unit's `ExecStart` in `op run`.**

  Edit `homelab/services/climate-auto-switch/climate-auto-switch.service`:

  ```ini
  EnvironmentFile=/etc/opt/homelab/op-token-picklehome
  ExecStart=/usr/bin/op run --env-file=/opt/homelab/homelab/services/climate-auto-switch/.env.op.template -- /usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml run --rm climate-auto-switch
  ```

  (`.env.op.template` is a filtered, checked-in-safe file `deploy.sh` regenerates every deploy — see Step 3. It's fine for this file to live in the repo's working tree on picklelab; it contains only `op://` references, never a secret, so it doesn't need `.gitignore` treatment beyond what already ignores `.env` there.)

- [ ] **Step 3: Have `deploy.sh` write the filtered template instead of expecting a scp'd `.env`.**

  Add near the top of `homelab/services/climate-auto-switch/deploy.sh` (after `cd "$REPO_DIR"`):

  ```bash
  echo "==> Writing filtered op-run template"
  "$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" > "$SERVICE_DIR/.env.op.template"
  ```

- [ ] **Step 4: Update the Justfile recipe — drop the scp, keep everything else.**

  In `deploy-climate` (Justfile ~line 138), remove:

  ```
  echo "==> Copying .env to {{host}}"
  mkdir -p tmp
  scripts/service-env homelab/services/climate-auto-switch/.env.vars > tmp/climate-auto-switch.env
  scp tmp/climate-auto-switch.env {{host}}:/opt/homelab/homelab/services/climate-auto-switch/.env
  rm tmp/climate-auto-switch.env
  ```

  leaving just the pre-flight git checks and the final `ssh {{host}} "cd /opt/homelab && git pull && homelab/services/climate-auto-switch/deploy.sh"` line, unchanged.

- [ ] **Step 5: Deploy and verify no `.env` is involved anywhere.**

  ```bash
  just deploy-climate
  ssh picklelab "ls /opt/homelab/homelab/services/climate-auto-switch/ | grep -E '\.env'"
  ```

  Expected: only `.env.op.template` appears (containing `op://` refs, verify with `ssh picklelab "cat /opt/homelab/homelab/services/climate-auto-switch/.env.op.template"` — every value must start with `op://`, none may be a real secret). No plain `.env` file should exist at all.

  ```bash
  ssh picklelab "cat /srv/data/climate-auto-switch/last-state.json"
  ```

  Expected: a recent timestamp, confirming the container actually ran with real resolved secrets (not empty/failed).

- [ ] **Step 6: Commit.**

  ```bash
  git add homelab/services/climate-auto-switch/climate-auto-switch.service homelab/services/climate-auto-switch/deploy.sh Justfile
  git commit -m "feat(climate-auto-switch): switch secrets from scp'd .env to op run"
  ```

## Task 5: Worked example — migrate `brineworks-server` (build metadata + health checks + two ssh calls collapsed to one)

This is the more complex worked example: it has `.env.build` (deploy-time metadata, unrelated to secrets — leave that mechanism alone), a health-check loop, and today's Justfile recipe does two separate `ssh` calls plus a local scp.

> **Revised 2026-09-14** — see Task 4's revision note for the full `env_file:`-vs-`environment:` investigation. `brineworks-server` turns out to be the easy case: its base `compose.yaml` already declares `BRINEWORKS_DB_PASSWORD`/`BRINEWORKS_API_KEY` via `environment: ${VAR}` interpolation (confirmed by reading the file) — that mechanism already reads from the process environment `op run` will populate. The only thing to fix is `compose.picklelab.yaml`'s `server` service, which additionally declares `env_file: - /opt/homelab/.env` (the same stale repo-root file flagged in Task 4) alongside `.env.build`. Drop the `/opt/homelab/.env` line, keep `.env.build` (deploy metadata, unrelated to secrets) — no new `environment:` entries needed here, unlike `climate-auto-switch`.

**Files:**
- Modify: `homelab/services/brineworks-server/brineworks-server.service`
- Modify: `homelab/services/brineworks-server/deploy.sh`
- Modify: `Justfile` (`deploy-brineworks-server` recipe, ~line 269)
- Modify: `homelab/services/brineworks-server/compose.picklelab.yaml` (remove `env_file: - /opt/homelab/.env` from the `server` service, keep `- .env.build`)

- [ ] **Step 0: Drop the stale `env_file:` entry from `compose.picklelab.yaml`.**

  In `homelab/services/brineworks-server/compose.picklelab.yaml`, the `server` service has:

  ```yaml
      env_file:
        - /opt/homelab/.env
        - .env.build
  ```

  Change to:

  ```yaml
      env_file:
        - .env.build
  ```

  (`BRINEWORKS_DB_PASSWORD`/`BRINEWORKS_API_KEY` are already delivered via `${VAR}` interpolation in the base `compose.yaml` — confirmed by reading it — so removing the `/opt/homelab/.env` line doesn't lose anything real, it just stops reading a stale file that was never part of this service's own filtered-secrets scheme.)

- [ ] **Step 1: Wrap the systemd unit's `ExecStart`/`ExecStop`.**

  Current (`homelab/services/brineworks-server/brineworks-server.service`):

  ```ini
  EnvironmentFile=-/opt/homelab/homelab/services/brineworks-server/.env.build
  ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml up -d --build
  ExecStop=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml down
  ```

  New:

  ```ini
  EnvironmentFile=/etc/opt/homelab/op-token-picklehome
  EnvironmentFile=-/opt/homelab/homelab/services/brineworks-server/.env.build
  ExecStart=/usr/bin/op run --env-file=/opt/homelab/homelab/services/brineworks-server/.env.op.template -- /usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml up -d --build
  ExecStop=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml down
  ```

  (`ExecStop` doesn't need secrets — `down` doesn't require interpolated values compose already resolved at `up` time — so it's left unwrapped. `.env.build`'s `EnvironmentFile` line stays exactly as-is; it's deploy metadata, not secrets, and doesn't go through `op run`.)

- [ ] **Step 2: Update `deploy.sh` to write the filtered template.**

  In `homelab/services/brineworks-server/deploy.sh`, after the existing "Writing build metadata" block (which writes `.env.build`), add:

  ```bash
  echo "==> Writing filtered op-run template"
  "$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" > "$SERVICE_DIR/.env.op.template"
  ```

- [ ] **Step 3: Update the log-tailing recipes that reference `--env-file .env`.**

  `brineworks-server-logs` and `brineworks-server-logs-follow` (Justfile ~line 298-303) currently run:

  ```
  docker compose --env-file .env --env-file .env.build -f compose.yaml -f compose.picklelab.yaml logs ...
  ```

  `logs` doesn't need real secret values (it's reading container output, not starting anything), but compose still evaluates `${VAR:?required}` interpolation at parse time for the whole compose file, so a missing `.env` could break even a `logs` call if any required var has no default. Change these two recipes to go through `op run` too, matching the unit:

  ```
  ssh {{host}} "cd /opt/homelab/homelab/services/brineworks-server && set -a; . /etc/opt/homelab/op-token-picklehome; set +a; op run --env-file=.env.op.template -- docker compose --env-file .env.build -f compose.yaml -f compose.picklelab.yaml logs --tail={{lines}}"
  ```

  (drop the `--env-file .env` flag entirely — that file no longer exists — and add the `op run` wrap around `docker compose`.)

- [ ] **Step 4: Collapse the Justfile recipe to one ssh call, no local scp.**

  Replace the whole body of `deploy-brineworks-server` (Justfile ~line 269-295) from the point after `echo "Deploying commit ..."` onward:

  ```
  echo "Deploying commit $(git rev-parse --short HEAD) to {{host}}"
  ssh {{host}} "cd /opt/homelab && git pull && homelab/services/brineworks-server/deploy.sh"
  ```

  (the pre-flight uncommitted-changes / branch / push-if-needed block above that line stays unchanged — it's still needed so `git pull` on the host actually picks up something new).

- [ ] **Step 5: Deploy and verify.**

  ```bash
  just deploy-brineworks-server
  ssh picklelab "ls /opt/homelab/homelab/services/brineworks-server/ | grep -E '\.env'"
  ```

  Expected: `.env.build` (deploy metadata, unchanged) and `.env.op.template` (op:// refs only) — no plain `.env`.

  ```bash
  curl -sf https://brineworks-server.$(ssh picklelab "tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix'")/health
  ```

  Expected: `200`/healthy response, confirming the container started with real `BRINEWORKS_DB_PASSWORD`/`BRINEWORKS_API_KEY` values (a missing/empty DB password would fail Postgres connection and this health check).

- [ ] **Step 6: Commit.**

  ```bash
  git add homelab/services/brineworks-server/brineworks-server.service homelab/services/brineworks-server/deploy.sh Justfile
  git commit -m "feat(brineworks-server): switch secrets from scp'd .env to op run"
  ```

## Task 6: Extract the shared Justfile deploy wrapper

Two worked examples in, the repeated shape (pre-flight checks + one ssh call) is proven. Deduplicate it before rolling out to the remaining eight services, so their migration in Task 7 is a one-line Justfile change each instead of another ~15-line copy-paste block.

**Files:**
- Modify: `Justfile` (add `_deploy-remote`, rewrite `deploy-climate` and `deploy-brineworks-server` to use it)

**Interfaces:**
- Produces: `_deploy-remote service host="picklelab"` — takes a service directory name (matching `homelab/services/<name>/`), runs the pre-flight checks against the *calling* repo, then `ssh {{host}} "cd /opt/homelab && git pull && homelab/services/{{service}}/deploy.sh"`.

- [ ] **Step 1: Add the shared recipe.**

  ```just
  # Shared implementation for every deploy-<service> recipe: pre-flight checks,
  # push if needed, then one ssh call that pulls and runs that service's deploy.sh
  # on the host. No local .env involved -- deploy.sh resolves its own secrets via
  # op run against the host's 1Password service-account token.
  _deploy-remote service host="picklelab":
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
      ssh {{host}} "cd /opt/homelab && git pull && homelab/services/{{service}}/deploy.sh"
  ```

- [ ] **Step 2: Rewrite the two already-migrated recipes to call it.**

  ```just
  deploy-climate host="picklelab":
      just _deploy-remote climate-auto-switch {{host}}

  deploy-brineworks-server host="picklelab":
      just _deploy-remote brineworks-server {{host}}
  ```

- [ ] **Step 3: Verify both still deploy correctly.**

  ```bash
  just deploy-climate
  just deploy-brineworks-server
  ```

  Same expectations as Tasks 4 and 5's verification steps — this should be a no-op behavior change, only less Justfile code.

- [ ] **Step 4: Commit.**

  ```bash
  git add Justfile
  git commit -m "refactor(justfile): extract shared _deploy-remote recipe"
  ```

## Task 7: Roll out the pattern to the remaining single-vault services

Applies the exact mechanism from Tasks 4/5/6 to every remaining service whose secrets live only in the `picklehome` vault: `brineworks-agent`, `second-brain-agent`, `taskchampion-sync`, `github-actions-runner`, `woodpecker`, `nikke` (no `.env.vars` — this one is execution-model-only, no template to write). Each is the identical three-part change (systemd unit `ExecStart` wrap, `deploy.sh` writes `.env.op.template`, Justfile recipe calls `_deploy-remote`) — call out only what's different per service below.

> **Revised 2026-09-14 — carry Task 4/5's `env_file:`-vs-`environment:` check into every step below.** Task 4 discovered that `op run`'s process-env injection is inert against a compose `env_file:` directive (which reads a literal file path, ignoring the process environment) — only bare `environment: ${VAR}` interpolation actually receives what `op run` resolves. Before wrapping any of this task's systemd units, `grep -n "env_file:" homelab/services/<name>/compose*.yaml` for that service and reason about each hit: if the same vars are *already* also declared via `environment: ${VAR}` (or `${VAR:?required}`) elsewhere in the same compose stack, the `env_file:` line is redundant — drop it. If a var is delivered *only* via `env_file:` with no `environment:` fallback, it needs a new `environment: ${VAR:?required}` entry before the `env_file:` line can be safely removed (same shape as Task 4's `climate-auto-switch` fix). Already checked and confirmed clean, no compose changes needed: `second-brain-agent`, `taskchampion-sync`, `openclaw`, `open-webui` (all already use `environment: ${VAR:?required})` for every secret). Confirmed needing a compose change: `github-actions-runner` and `woodpecker`'s server both already declare their secrets via `environment: ${VAR}` *alongside* a same-scope `env_file: - .env` — almost certainly redundant (drop the `env_file:` line after confirming no var is env_file-only), but verify per the rule above rather than trusting this summary. `brineworks-agent` needs a closer look: its base `compose.yaml` only declares non-secret `environment:` entries, and the picklelab overlay has *two* `env_file: - .env` blocks (one on the `ts-agent` sidecar for `TS_AUTHKEY`, one on the main agent service, per a comment there about deliberately scoping which secrets that container sees) — actually read both files before deciding whether `KEYRING_CRYPTFILE_PASSWORD`/`BRINEWORKS_API_KEY` need new `environment:` entries or whether `TS_AUTHKEY`'s sidecar usage is a special case (a `tailscale/tailscale` image reading `TS_AUTHKEY` from its own env is a different code path than this repo's own containers, so don't assume it works identically). Also drop any `env_file: - /opt/homelab/.env` you find anywhere in this pass — same stale file Task 4 flagged, not this service's concern to preserve.

**Files:** for each service `<name>` in the list: `homelab/services/<name>/<name>.service`, `homelab/services/<name>/deploy.sh`, and (per the `env_file:` investigation above) possibly `homelab/services/<name>/compose.yaml` and/or `compose.picklelab.yaml`. (The Justfile collapse onto `_deploy-remote` is Task 9's job, not this task's — don't touch `Justfile` here.)

- [ ] **Step 1: `brineworks-agent`.** Same pattern as Task 5. Note: its `.env.vars` includes `TS_AUTHKEY` (ts-agent sidecar) alongside `KEYRING_CRYPTFILE_PASSWORD`/`BRINEWORKS_API_KEY`/`WORKSPACE_DEPLOY_KEY_B64` — all four are `picklehome`-vault, single token, no special handling needed. Verify with `ssh picklelab "timeout 2 bash -c 'cat < /dev/null > /dev/tcp/brineworks-agent.$(...)/22'"` (same check `deploy.sh` already does).

- [ ] **Step 2: `second-brain-agent`.** Its `.env.vars` has just `SECOND_BRAIN_AGENT_TS_AUTHKEY`. Verify via the same sshd-reachability check its `deploy.sh` already runs.

- [ ] **Step 3: `taskchampion-sync`.** `.env.vars` holds `TASKCHAMPION_SYNC_HOST`/`TASKCHAMPION_SYNC_SERVER_CLIENT_ID`, both consumed via compose interpolation (not baked into an image at build time), so the standard `ExecStart` wrap applies unmodified. Verify with `just taskchampion-status`.

- [ ] **Step 4: `github-actions-runner`.** `.env.vars` holds `GITHUB_RUNNER_REPO_URL`/`GITHUB_RUNNER_TOKEN`. Per the service README, `GITHUB_RUNNER_TOKEN` is a one-time bootstrap value read at container first-start, not re-read on every restart — registration state lives in the `runner-config` Docker volume, not in `.env`, so removing the persisted `.env` doesn't touch already-registered state. Verify with `just github-runner-status`.

- [ ] **Step 5: `woodpecker`.** `.env.vars` holds `WOODPECKER_GITHUB_CLIENT`/`WOODPECKER_GITHUB_SECRET`/`WOODPECKER_AGENT_SECRET`/`WOODPECKER_TS_AUTHKEY`. This service runs CI under a separate rootless `ci`-user dockerd (per its README) for the *agent* half — the `op run` wrap goes on the **server**'s systemd unit (root-owned dockerd, standard pattern). Check whether the agent's compose invocation (under the rootless `ci` user) can read `/etc/opt/homelab/op-token-picklehome` at all — that file is 0600 owned by whatever user placed it (Task 1's `ssh picklelab "sudo ... chmod 600"`, i.e. root or the deploy user), and the `ci` system user won't have read access unless the file is separately group-readable or duplicated for that user. If the agent's `WOODPECKER_AGENT_SECRET` needs to reach the rootless dockerd, either place a `ci`-readable copy of the token at a second path (e.g. `/etc/opt/homelab/op-token-picklehome-ci`, `chmod 640` + `chgrp ci`) or confirm the agent already receives its secret some other way (check `homelab/services/woodpecker/compose.yaml` for how `WOODPECKER_AGENT_SECRET` currently flows to the agent container before assuming it needs its own `op run` wrap at all). Verify with `just woodpecker-status`.

- [ ] **Step 6: `nikke`.** No `.env.vars`, no secrets, so no `op run` wrap needed — skip Task 4/5's Steps 1-3 entirely for this one. Only apply Task 6's Justfile change (`deploy-nikke` calls `_deploy-remote nikke`) to drop the (currently secret-free but still two-ssh-call) old recipe shape. Verify with `just deploy-nikke` then `curl -sf https://nikke.$(...)/`.

- [ ] **Step 7: Commit each service's change separately** (not one giant commit — each is independently revertable if one service's verification fails):

  ```bash
  git add homelab/services/brineworks-agent/ Justfile && git commit -m "feat(brineworks-agent): switch secrets from scp'd .env to op run"
  # ... repeat per service
  ```

## Task 8: Roll out the dual-vault pattern to `openclaw` and `open-webui`

These two need **both** tokens: per `.env.vars`, `openclaw` needs `OPENCLAW_HOST`, `OPENCLAW_GATEWAY_TOKEN`, `OPENCLAW_ALLOWED_CHAT_IDS`, `GOOGLE_PLACES_API_KEY`, `OPENCLAW_WORKSPACE_DEPLOY_KEY_B64`, `OPENCLAW_WORKSPACE_GITHUB_TOKEN`, `GOG_MCP_TOKEN`, `GOG_KEYRING_PASSWORD`, `OPENCLAW_PICKLECLAW_DEPLOY_KEY_B64` (all `picklehome`-vault) **plus** `OLLAMA_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY` (`Brent Pickleclaw`-vault). `open-webui` needs `OPEN_WEBUI_HOST`/`OPEN_WEBUI_ADMIN_EMAIL`/`OPEN_WEBUI_ADMIN_PASSWORD`/`OPEN_WEBUI_SECRET_KEY`/`OPEN_TERMINAL_API_KEY` (`picklehome`) plus `OLLAMA_API_KEY` (`Brent Pickleclaw`). `op run` takes exactly one service-account token per invocation (confirmed in Task 1), so these need **two chained `op run` calls**, one per vault.

**Files:** `homelab/services/openclaw/openclaw.service`, `homelab/services/openclaw/deploy.sh`, `homelab/services/open-webui/open-webui.service` (or equivalent unit name — check), `homelab/services/open-webui/deploy.sh`, `Justfile`.

- [ ] **Step 1: Have `deploy.sh` write two filtered templates per service instead of one.**

  For `openclaw`, split `.env.vars` conceptually into the two vault groups. Rather than maintaining two separate `.env.vars` files (extra maintenance burden vs. the single-vault services), have `deploy.sh` run `service-env` twice against the *same* `.env.vars`, filtering each run's output by which vault the resolved template line references:

  ```bash
  echo "==> Writing filtered op-run templates (dual vault)"
  "$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" \
      | grep '^[A-Z_]*=op://picklehome/' > "$SERVICE_DIR/.env.op.picklehome.template"
  "$REPO_DIR/scripts/service-env" "$SERVICE_DIR/.env.vars" --template "$REPO_DIR/.env.template" \
      | grep '^[A-Z_]*=op://Brent Pickleclaw/' > "$SERVICE_DIR/.env.op.pickleclaw.template"
  ```

- [ ] **Step 2: Chain both `op run` calls in the systemd unit.**

  ```ini
  EnvironmentFile=/etc/opt/homelab/op-token-picklehome
  ExecStart=/usr/bin/op run --env-file=/opt/homelab/homelab/services/openclaw/.env.op.picklehome.template -- \
            /usr/bin/env OP_SERVICE_ACCOUNT_TOKEN_FILE=/etc/opt/homelab/op-token-pickleclaw \
            /usr/bin/op run --env-file=/opt/homelab/homelab/services/openclaw/.env.op.pickleclaw.template -- \
            /usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml up -d
  ```

  Verify during Task 1 whether `op run` actually supports an `OP_SERVICE_ACCOUNT_TOKEN_FILE`-style override for a *nested* invocation, or whether the inner `op run` needs its own `set -a; source .../op-token-pickleclaw; set +a` wrapper instead (both env vars can't simultaneously be named `OP_SERVICE_ACCOUNT_TOKEN` in the same process without the second overriding the first before the first `op run` reads it — this needs a real live test, don't ship this exact line unverified). If chaining two token env vars in one `ExecStart=` proves awkward, fall back to a wrapper script (`homelab/services/openclaw/op-run-dual.sh`) that `deploy.sh` installs and the unit calls instead — simpler to get right than a one-line `ExecStart`.

- [ ] **Step 3: Same for `open-webui`**, with its own two filtered templates.

- [ ] **Step 4: Deploy and verify both.**

  ```bash
  just deploy-openclaw
  curl -fsS https://openclaw.$(...)/healthz
  just deploy-open-webui
  curl -sf https://openwebui.$(...)/
  ```

  Also confirm the Telegram bot still responds (openclaw's `.env.vars` includes chat-facing secrets — a silent auth failure wouldn't necessarily show up in a bare health check).

- [ ] **Step 5: Commit.**

  ```bash
  git add homelab/services/openclaw/ homelab/services/open-webui/ Justfile
  git commit -m "feat(openclaw,open-webui): switch secrets from scp'd .env to chained op run (dual vault)"
  ```

## Task 9: `taskchampion-sync`, `github-actions-runner`, `woodpecker`, `backup` — apply the shared Justfile recipe

Task 7 already migrated these services' secrets; this task is the mechanical Justfile cleanup (collapse to `_deploy-remote`) that Task 6 did for `climate`/`brineworks-server`. Fold in during Task 7 if it's more natural to do both at once per-service — listed separately here only because Task 7's focus was secrets correctness, not Justfile shape.

**Files:** `Justfile`.

- [ ] **Step 1:** Rewrite `deploy-taskchampion`, `deploy-github-runner`, `deploy-woodpecker`, `deploy-backup`, `deploy-nikke`, `deploy-brineworks-agent`, `deploy-second-brain-agent`, `deploy-openclaw`, `deploy-open-webui` to each call `just _deploy-remote <service-dir-name>`.
- [ ] **Step 2:** Re-run each `just deploy-<service>` once to confirm the collapsed recipe still works (should be a no-op vs. Tasks 7/8's already-passing deploys, just less code running).
- [ ] **Step 3: Commit.**

  ```bash
  git add Justfile
  git commit -m "refactor(justfile): collapse remaining deploy recipes onto _deploy-remote"
  ```

## Task 10: Remove `scripts/dotenv`'s deploy role from documentation (Mac-side `.env` stays for local dev only)

`just dotenv` still exists and still matters — it's how the Mac's own local dev/test `.env` gets refreshed (Python modules under `climate/`, `garage/`, etc. still load it directly). What changes is that it's no longer *load-bearing for deploys*. Make that explicit so nobody re-adds a deploy-time dependency on it later.

**Files:** `Justfile` (comment above the `dotenv` recipe), `homelab/services/README.md`.

- [ ] **Step 1:** Add a comment above the `dotenv` recipe in `Justfile` noting it's local-dev-only as of this redesign, and update `homelab/services/README.md`'s "Deployment pattern" section (see Task 11 for the full rewrite — do both edits together).

## Task 11: Rewrite `homelab/services/README.md`'s deployment pattern

**Files:** `homelab/services/README.md`.

- [ ] **Step 1:** Replace the "Deployment pattern" section's current content:

  ```markdown
  ## Deployment pattern

  All services follow the same shape. Deploy from any machine with an `ssh` config
  entry for `picklelab` (no local picklehome checkout needed):

  ```bash
  just deploy-<service>          # push if needed, ssh in, git pull, run deploy.sh
  ```

  Secrets never touch the Mac or scp anywhere. Each service directory in
  `homelab/services/<name>/` contains:

  | File | Purpose |
  |------|---------|
  | `compose.yaml` | Local dev compose (or, for extracted services, lives in the app's own repo — see that service's README) |
  | `compose.picklelab.yaml` | Production overrides (volumes, restart policy) |
  | `deploy.sh` | Called by `just deploy-<name>` (via the shared `_deploy-remote` Justfile recipe); writes the filtered op-run template, handles systemd + Tailscale |
  | `.env.vars` | Which env vars this service needs, filtered from `.env.template` (not `.env`) into a per-service op-run template by `scripts/service-env` |
  | `<name>.service` | systemd unit; `ExecStart` wraps `docker compose up` in `op run --env-file=<filtered-template>`, resolving secrets from 1Password directly on the host |

  On picklelab, `/etc/opt/homelab/op-token-picklehome` and `/etc/opt/homelab/op-token-pickleclaw`
  are read-only, single-vault 1Password service-account tokens (0600), referenced by each
  service's systemd unit via `EnvironmentFile=`. No `.env` file exists anywhere under
  `homelab/services/*/` on picklelab — only `.env.op.template` (or `.env.op.<vault>.template`
  for the two dual-vault services), which contain `op://` references, never resolved secrets.

  `just dotenv` still exists for **local Mac dev/test** (`climate/`, `garage/`, etc. load `.env`
  directly via `python-dotenv`), but is no longer part of the deploy path.
  ```

  replacing the old scp-based description.

- [ ] **Step 2:** Update the "Container user model" and per-service registry entries only where they reference `.env` scp'ing (search for `scp` and `.env` scoped to that file, update each hit).

- [ ] **Step 3: Commit.**

  ```bash
  git add homelab/services/README.md Justfile
  git commit -m "docs(homelab): rewrite deployment pattern for op-run secrets model"
  ```

## Task 12: Extract `second-brain-agent` into `technicalpickles/second-brain-agent`

**Files:**
- New repo: `technicalpickles/second-brain-agent` (private) — gets `Dockerfile`, `entrypoint.sh`, `tmux.conf`, `tmux-autoattach.sh`, `compose.yaml`, `compose.picklelab.yaml` (moved as-is from picklehome, git history not preserved unless you use `git subtree split` — decide whether that matters; the design doc doesn't require it)
- Delete from picklehome: `homelab/services/second-brain-agent/{Dockerfile,entrypoint.sh,tmux.conf,tmux-autoattach.sh,compose.yaml,compose.picklelab.yaml}`
- Keep in picklehome: `homelab/services/second-brain-agent/{deploy.sh,second-brain-agent.service,.env.vars,README.md}`

- [ ] **Step 1: Create the new repo.**

  ```bash
  gh repo create technicalpickles/second-brain-agent --private --description "Always-on Claude Code session container, deployed to picklelab from picklehome"
  git clone git@github.com:technicalpickles/second-brain-agent.git ~/github.com/technicalpickles/second-brain-agent
  ```

- [ ] **Step 2: Move the app-owned files.**

  ```bash
  cd ~/github.com/technicalpickles/picklehome
  cp homelab/services/second-brain-agent/{Dockerfile,entrypoint.sh,tmux.conf,tmux-autoattach.sh,compose.yaml,compose.picklelab.yaml} ~/github.com/technicalpickles/second-brain-agent/
  cd ~/github.com/technicalpickles/second-brain-agent
  git add Dockerfile entrypoint.sh tmux.conf tmux-autoattach.sh compose.yaml compose.picklelab.yaml
  git commit -m "Initial import from picklehome homelab/services/second-brain-agent/"
  git push -u origin main
  ```

- [ ] **Step 3: Update `deploy.sh` to clone/pull the new repo, mirroring the pattern `brineworks-server/deploy.sh` already uses.**

  Add near the top of `homelab/services/second-brain-agent/deploy.sh` (picklehome copy):

  ```bash
  AGENT_REPO=/opt/second-brain-agent

  if [ -d "$AGENT_REPO/.git" ]; then
      git -C "$AGENT_REPO" pull --ff-only
  else
      echo "    Cloning second-brain-agent to $AGENT_REPO"
      sudo mkdir -p "$AGENT_REPO"
      sudo chown "$(id -u):$(id -g)" "$AGENT_REPO"
      git clone git@github.com:technicalpickles/second-brain-agent.git "$AGENT_REPO"
  fi
  ```

  and change every `docker compose -f compose.yaml -f compose.picklelab.yaml` reference (in `deploy.sh` and the systemd unit) to point at `$AGENT_REPO`'s copies instead of `$SERVICE_DIR`'s — either `cd "$AGENT_REPO"` before the compose call, or pass `-f "$AGENT_REPO/compose.yaml" -f "$AGENT_REPO/compose.picklelab.yaml"` explicitly. Also update the systemd unit's `WorkingDirectory=` if it currently points at `$SERVICE_DIR`.

- [ ] **Step 4: Delete the moved files from picklehome and update the README pointer.**

  ```bash
  cd ~/github.com/technicalpickles/picklehome
  git rm homelab/services/second-brain-agent/Dockerfile homelab/services/second-brain-agent/entrypoint.sh homelab/services/second-brain-agent/tmux.conf homelab/services/second-brain-agent/tmux-autoattach.sh homelab/services/second-brain-agent/compose.yaml homelab/services/second-brain-agent/compose.picklelab.yaml
  ```

  Update `homelab/services/second-brain-agent/README.md` to point at the new repo for app internals, matching how `brineworks-server/README.md` already references the `brineworks` repo.

- [ ] **Step 5: Deploy and verify.**

  ```bash
  just deploy-second-brain-agent
  ssh technicalpickles@second-brain-agent.$(ssh picklelab "tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix'") "tmux ls"
  ```

  Expected: the container rebuilds from `/opt/second-brain-agent` (a fresh clone, confirm with `ssh picklelab "ls /opt/second-brain-agent"`), and the persistent tmux session is still reachable.

- [ ] **Step 6: Commit picklehome's side.**

  ```bash
  git add homelab/services/second-brain-agent/
  git commit -m "refactor(second-brain-agent): extract app code to technicalpickles/second-brain-agent"
  ```

## Task 13: Extract `homelab/dev/` into `technicalpickles/homelab-dev`

Same shape as Task 12.

**Files:**
- New repo: `technicalpickles/homelab-dev` (private) — gets `Dockerfile`, `bootstrap.sh`, `compose.local.yaml`, `compose.picklelab.yaml`, `compose.yaml`, `entrypoint.sh`
- Keep in picklehome: a thin `homelab/dev/deploy.sh` pointer (or move the whole directory out and replace it with a README note — check whether anything else in picklehome references `homelab/dev/` paths before deleting outright: `grep -rn "homelab/dev" --include=*.md --include=Justfile .`)

- [ ] **Step 1: Confirmed (2026-09-13): there is no Justfile recipe for this at all.** `grep -n "homelab/dev" Justfile` returns nothing — `homelab/dev/deploy.sh` is run directly (`./homelab/dev/deploy.sh` or `ssh picklelab '.../homelab/dev/deploy.sh'`), not through `just`. The only reference anywhere is a prose mention in `homelab/services/README.md:232` ("Container internals copy `homelab/dev/`"), which needs its path updated once the repo moves. So this task has no Justfile step — smaller than Task 12.

- [ ] **Step 2: Create the repo and move the files.**

  ```bash
  gh repo create technicalpickles/homelab-dev --private --description "Dev container image for picklelab, deployed from picklehome"
  git clone git@github.com:technicalpickles/homelab-dev.git ~/github.com/technicalpickles/homelab-dev
  cd ~/github.com/technicalpickles/picklehome
  cp homelab/dev/{Dockerfile,bootstrap.sh,compose.local.yaml,compose.picklelab.yaml,compose.yaml,entrypoint.sh} ~/github.com/technicalpickles/homelab-dev/
  cd ~/github.com/technicalpickles/homelab-dev
  git add Dockerfile bootstrap.sh compose.local.yaml compose.picklelab.yaml compose.yaml entrypoint.sh
  git commit -m "Initial import from picklehome homelab/dev/"
  git push -u origin main
  ```

- [ ] **Step 3: Update `deploy.sh`** (note this one already has host-detection logic for running locally-on-picklelab vs. remotely — preserve that; add a clone/pull-into-`/opt/homelab-dev` step mirroring Task 12 Step 3, and repoint `$COMPOSE_FILES`/the `docker compose` invocation at `/opt/homelab-dev` instead of `$REMOTE_DIR/homelab/dev`). Delete the moved files from picklehome (`git rm homelab/dev/{Dockerfile,bootstrap.sh,compose.local.yaml,compose.picklelab.yaml,compose.yaml,entrypoint.sh}`), leaving only `deploy.sh` behind.

- [ ] **Step 4: Update the one prose reference** in `homelab/services/README.md:232` to point at the new repo instead of `homelab/dev/`.

- [ ] **Step 5: Deploy and verify**, using `deploy.sh`'s own existing verification (connect via the `picklelab-dev` SSH alias it sets up, per its final "Done! Connect with: ssh picklelab-dev" message).

- [ ] **Step 6: Commit** both repos' sides.

## Task 14: Move `brineworks-server`/`brineworks-agent`'s `compose.yaml` to the `brineworks` repo

Per design doc section 1: the app repo becomes the source of truth for the *portable* compose definition; `compose.picklelab.yaml` (the picklelab-specific overlay — loopback-bind security invariant, confirmed 2026-08-16) stays in picklehome.

**Files:**
- `brineworks` repo (`~/github.com/technicalpickles/brineworks`, already cloned): gains `server/compose.yaml` and `agent/compose.yaml` — confirmed (2026-09-13) the repo already has top-level `server/` and `agent/` directories matching the server/agent split, so each compose file lands next to that app's own code, not both dumped at repo root.
- Delete from picklehome: `homelab/services/brineworks-server/compose.yaml`, `homelab/services/brineworks-agent/compose.yaml`
- Modify: both services' `deploy.sh` (already clone `/opt/brineworks` — repoint the `-f compose.yaml` flag at `/opt/brineworks/server/compose.yaml` or `/opt/brineworks/agent/compose.yaml` respectively, instead of `$SERVICE_DIR`'s copy)
- Modify: both services' systemd units (`ExecStart`/`ExecStop` compose file paths, same repointing)

- [ ] **Step 1: Move each `compose.yaml`.**

  ```bash
  cd ~/github.com/technicalpickles/picklehome
  cp homelab/services/brineworks-server/compose.yaml ~/github.com/technicalpickles/brineworks/server/compose.yaml
  cp homelab/services/brineworks-agent/compose.yaml ~/github.com/technicalpickles/brineworks/agent/compose.yaml
  cd ~/github.com/technicalpickles/brineworks
  git add server/compose.yaml agent/compose.yaml
  git commit -m "Import compose.yaml from picklehome (deploy-design redesign)"
  git push
  ```

- [ ] **Step 2: Update `deploy.sh` and the systemd unit in each of `brineworks-server`/`brineworks-agent`** to reference `/opt/brineworks/server/compose.yaml` / `/opt/brineworks/agent/compose.yaml` instead of the local copy (picklehome keeps `compose.picklelab.yaml` unchanged, still passed as the second `-f`, e.g. `docker compose -f /opt/brineworks/server/compose.yaml -f compose.picklelab.yaml up -d --build`).
- [ ] **Step 3: `git rm` the now-moved files from picklehome** (`homelab/services/brineworks-server/compose.yaml`, `homelab/services/brineworks-agent/compose.yaml`).
- [ ] **Step 4: Deploy both and verify** with the same health checks Task 5/Task 7-Step-1 already established.
- [ ] **Step 5: Commit** both repos.

## Task 15: Move `nikke`'s `compose.yaml` to `nikke-roster-scanner`

Same shape as Task 14, single service instead of two. Confirmed (2026-09-13): `nikke-roster-scanner`'s repo is a flat layout (Dockerfile at root, no server/agent-style subdirectory split), so `compose.yaml` lands at repo root, not nested.

**Files:**
- `nikke-roster-scanner` repo (`~/github.com/technicalpickles/nikke-roster-scanner`, already cloned): gains `compose.yaml` at root
- Delete from picklehome: `homelab/services/nikke/compose.yaml`
- Modify: `homelab/services/nikke/deploy.sh`, `nikke.service`, `nikke-sync.service`/`.timer` (all three reference the same compose file)

- [ ] **Step 1: Move `compose.yaml`.**

  ```bash
  cd ~/github.com/technicalpickles/picklehome
  cp homelab/services/nikke/compose.yaml ~/github.com/technicalpickles/nikke-roster-scanner/compose.yaml
  cd ~/github.com/technicalpickles/nikke-roster-scanner
  git add compose.yaml
  git commit -m "Import compose.yaml from picklehome (deploy-design redesign)"
  git push
  ```

- [ ] **Step 2: Update `deploy.sh` and all three systemd units** to reference `/opt/nikke-roster-scanner/compose.yaml` instead of the local copy (picklehome keeps `compose.picklelab.yaml` unchanged as the second `-f`).
- [ ] **Step 3: `git rm homelab/services/nikke/compose.yaml`** from picklehome.
- [ ] **Step 4: Deploy and verify** (`just deploy-nikke`, curl the health endpoint, confirm the sync timer still fires: `systemctl list-timers nikke-sync.timer`).
- [ ] **Step 5: Commit** both repos.

## Task 16: Full end-to-end verification pass

**Files:** none — pure verification.

- [ ] **Step 1: Confirm zero `.env` files exist anywhere under `homelab/services/*/` on picklelab.**

  ```bash
  ssh picklelab "find /opt/homelab/homelab/services -name '.env' -o -name '.env.build'"
  ```

  Expected: only `.env.build`-style deploy-metadata files (not secrets) if any remain; no bare `.env`.

- [ ] **Step 2: Redeploy every service from a machine state that proves no local secret dependency remains** — e.g. temporarily rename the Mac's local `.env` (`mv .env .env.bak`) and run every `just deploy-<service>` recipe. Every one should succeed with no `.env` present locally, since none of them read it anymore.

  ```bash
  mv .env .env.bak
  for svc in climate brineworks-server brineworks-agent second-brain-agent taskchampion github-runner woodpecker backup nikke openclaw open-webui; do
      just deploy-$svc
  done
  mv .env.bak .env
  ```

- [ ] **Step 3: Spot-check each service's health endpoint / status one more time** (reuse the verification commands from each task above).

- [ ] **Step 4: Update the design doc's "Open questions for implementation planning" section** in `docs/plans/2026-08-10-homelab-service-deploy-design.md`, marking the now-resolved items (1Password service-account mechanics, deploy execution model, section 1/2/3 implementation) as done, with a pointer back to this plan.

- [ ] **Step 5: Commit the design-doc update.**

  ```bash
  git add docs/plans/2026-08-10-homelab-service-deploy-design.md
  git commit -m "docs(plans): mark deploy-design sections 1-3 implemented, point to implementation plan"
  ```

---

## Explicitly deferred (not in this plan)

- **Section 3a (Automic Vault on the Mac):** independent of everything above; its own follow-up per the design doc's open questions.
- **Section 4 (sensitive-data hygiene in docs/CONVENTIONS.md):** small, unrelated cleanup; do separately.
- **Section 5 (deploy-script app/host split for brineworks/nikke; pickleclaw's shared config-application step):** the pickleclaw half is blocked on [pickleclaw#4](https://github.com/technicalpickles/pickleclaw/issues/4); the brineworks/nikke half is a further refinement layered *on top of* what this plan produces (this plan gets `compose.yaml` into the app repos; section 5 would additionally move port/UID/health-check logic out of `deploy.sh` itself) — worth its own plan once this one has shipped and proven the op-run model works in production.
