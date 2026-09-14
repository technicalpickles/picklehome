# Homelab service deployment: ownership, execution, secrets

## Context

`homelab/services/` currently mixes three different shapes of service:

1. **Off-the-shelf images** (obsidian-sync, woodpecker, open-webui, github-actions-runner, taskchampion-sync, backup) — no app code, just deploy plumbing. Not in scope for this design.
2. **Split-repo apps** (brineworks-server, brineworks-agent, nikke) — app code lives in a separate repo (`brineworks`, `nikke-roster-scanner`), cloned to the host at deploy time. picklehome duplicates a *production* compose definition alongside the app repo's own dev compose, so the two drift.
3. **picklehome-native builds** (climate-auto-switch, second-brain-agent, `homelab/dev/`) — image built directly from this repo. Of these, only `climate-auto-switch` actually depends on picklehome's own code (`COPY climate/ climate/` in its Dockerfile); second-brain-agent and the dev container are fully standalone and just happen to live here.

Deploy today runs from a Mac: `just dotenv` writes 1Password secrets to a plaintext `.env` on disk, `just deploy-<service>` SSHes into picklelab to `git pull` + `scp` the filtered `.env` + `docker compose up`. This requires a local picklehome checkout on whatever machine you're deploying from, and leaves a materialized secrets file sitting on disk indefinitely.

Separately, picklehome is a public repo. `docs/CONVENTIONS.md` already has a rule that sensitive data (MACs, internal IPs, geolocatable info) goes to 1Password or agent memory, never committed — and `HOME_LAT`/`HOME_LON` already follow this via `.env`. The gap is enforcement: pending taskwarrior task #285 (seapickle site survey: ISP/router model, WiFi SSIDs, arp-scan results) currently targets a committed `README.md`, which would violate the existing rule.

## Goals

- Reduce duplicate service definitions between picklehome and split app repos.
- Deploy without needing a local picklehome checkout.
- Stop materializing secrets as a persistent `.env` file.
- Make the existing sensitive-data convention explicit enough to catch cases like task #285 before they happen.
- Extract standalone (non-coupled) services into their own repos where that reduces picklehome's scope, starting with the clearest candidates.

## Non-goals (deferred)

- **CI-driven auto-deploy** (push-to-deploy via the self-hosted GH Actions runner). Blocked on two things worth solving separately: personal (non-org) GitHub accounts only support per-repo runner registration, not pooled across repos, so this needs either N runner containers (more moving parts) or an org migration; and a self-hosted runner with `docker.sock` wired to a public repo's workflows is a known high-risk pattern (arbitrary code execution on the host via a workflow trigger) that needs careful trigger restrictions (push-to-main only, never `pull_request`, ideally required-reviewer gating). Revisit once there's appetite for that work.
- **Splitting picklehome into separate home-automation vs. homelab-ops repos.** Investigated: code coupling turned out to be minimal (only `climate-auto-switch` depends on picklehome's own `climate/` package; everything else in `homelab/` is either off-the-shelf or already-external). Decided to stay single-repo for now, but this is a live option to revisit, not a rejected one — particularly since it would let homelab-ops go private independent of the home-automation code.

## Design

**Sections 1-3 implemented 2026-09-14** per `docs/superpowers/plans/2026-09-13-homelab-service-deploy-redesign.md` — see that plan and its ledger for the concrete task-by-task history, findings, and rulings. Sections 3a, 4, and 5 remain deferred (see "Explicitly deferred" at the bottom of that plan).

### 1. Compose/app-repo ownership

For services with a split app repo (brineworks-server, brineworks-agent, nikke), the app repo becomes the single source of truth for its *portable* production compose definition (`compose.yaml`), not just a dev one. picklehome's `homelab/services/<name>/` shrinks to: systemd unit, `deploy.sh` (clone/pull the app repo, `docker compose -f <path-in-app-repo>` up), `.env.vars` filter list, and a README pointing at the app repo's own docs. No more parallel `compose.yaml` re-deriving the same service definition that has to be hand-synced.

**Exception: picklelab-specific overlays stay in picklehome.** `compose.picklelab.yaml` for brineworks-server encodes a security invariant tied to *this deploy environment*, not to the app: the loopback-only port binding is load-bearing for Tailscale Serve identity auth (anything reaching the port without going through Serve can spoof the identity header), confirmed live 2026-08-16 and documented in commits 6c4c952/ccc5203. That's picklelab topology knowledge the portable `compose.yaml` can't assert, so the overlay file (and its env-var/port bindings) stays in picklehome rather than moving to the app repo. The values in it (`BRINEWORKS_TRUST_TAILSCALE_HEADERS`, `BRINEWORKS_ALLOWED_LOGINS`) are plain config, not secrets, so this doesn't touch section 3.

**New extractions**, following the same pattern, for services confirmed to have no code coupling to picklehome:

- **`second-brain-agent`** → new private repo `technicalpickles/second-brain-agent`. Move `Dockerfile`, `entrypoint.sh`, `tmux.conf`, `tmux-autoattach.sh`, `compose.yaml`, `compose.picklelab.yaml` there. picklehome keeps the systemd unit, `deploy.sh` (clone via SSH deploy key, same as brineworks), `.env.vars`, README pointer.
- **`homelab/dev/`** (dev container) → candidate for its own private repo, same pattern. Whether it's a standalone repo or shares one with second-brain-agent (the two containers have a similar shape: SSH-reachable, bootstrap-installed toolchain, persisted home dir) is an open question — decide at implementation time, default to a separate repo unless a concrete reason to merge surfaces.

`climate-auto-switch` stays in picklehome (genuine code dependency on `climate/`). Off-the-shelf-image services are unaffected.

### 2. Deploy execution model

`/opt/homelab` on picklelab is already a self-updating checkout — every `deploy.sh` starts with a `git pull` there. Move deploy execution onto the host itself: a thin wrapper runs `ssh picklelab "cd /opt/homelab && git pull && just deploy-<service>"`. No local picklehome checkout is needed on whatever machine triggers the deploy. `just deploy-<service>` itself is unchanged, just invoked remotely instead of via local scp.

### 3. Secrets injection

Replace "Mac materializes `.env`, scp's it to host" with 1Password injecting secrets on the host, scoped to the single deploy invocation:

- **Two service account tokens, one per vault**, not one shared token. `.env.template` draws from two vaults that homelab deploys actually touch: `picklehome` (everything except openclaw/open-webui) and `Brent Pickleclaw` (`OLLAMA_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY` — needed by openclaw and open-webui). 1Password service account vault access and permissions are immutable after creation (confirmed via 1Password docs, 2026-08-22), so splitting by vault now avoids ever needing to touch the picklehome-scoped token when the pickleclaw side changes, or vice versa. Each token is read-only, scoped to exactly one vault.
- One-time setup: mint both service account tokens, store them on picklelab as narrow credentials (e.g. `/etc/opt/homelab/op-token-picklehome`, `/etc/opt/homelab/op-token-pickleclaw`, 0600 each) — small long-lived secrets instead of the full integration credential set.
- `deploy.sh` runs `op run --env-file=.env.template -- docker compose ... up -d`, selecting whichever token(s) the service's `.env.vars` filter list requires, so secrets exist only in that process's environment for the duration of the compose invocation — no standalone `.env` persists on the host.
- `.env.template` (already checked in, already the source of truth for which secrets exist) becomes the file actually passed to `op run`.
- The Mac-local `.env`/`just dotenv` workflow stays available for local dev/testing, but deploy no longer depends on it. Note: `.env.template` also has a `Personal`-vault reference (`VICOHOME_*`), but no homelab service's `.env.vars` list draws from it — local-dev-only, out of scope for the service account tokens.

**Refinements from 2026-09-13 review** (nothing in this section was implemented between 2026-08-22 and the 2026-09-13 review; all of it is now implemented, see the pointer at the top of this Design section):

- **`op run` takes one service account token per invocation.** Two consequences for the wiring:
  - `--env-file=.env.template` as-is would fail on any reference to a vault the active token can't read. `deploy.sh` needs a per-service filtered template instead (point `scripts/service-env`'s existing `.env.vars` filtering at the template rather than at `.env`).
  - openclaw and open-webui draw from *both* vaults (`picklehome` too, not only `Brent Pickleclaw`), so they need two chained `op run` invocations, one per token and filtered template. Every other service needs only the `picklehome` token.
- **Not everything is in the `.env` pipeline.** openclaw also reads `openclaw.image.env` (symlinked from the private `pickleclaw` repo) and files under `~/.openclaw/secrets/` placed with `op read | install -m 600`. `op run` doesn't cover those; they stay manual unless the plan says otherwise.
- **Values entered with `just secret-entry` never reach a deploy.** Once `.env.template` is the only input, a value that exists only in a local `.env` or in Automic Vault (below) is invisible to `op run`. 1Password stays the single source of truth for anything a homelab service needs.
- **Service account tokens also fix agent-side `op` on the Mac.** Agent shells have repeatedly failed to reach the 1Password desktop integration (2026-07-26 remote-control session; 2026-09-11, where `op whoami` worked in a human terminal but not from the agent's shell even with the sandbox disabled, apparently a macOS process-trust boundary). A token-authenticated `op` doesn't go through the desktop app at all. The tradeoff is a long-lived secret on disk; read-only, single-vault scoping is the mitigation.
- **Validate before writing the plan:** mint the `picklehome` token, place it on picklelab, and run `op run` against a one-variable filtered template. Confirm (a) a bad or revoked token aborts loudly rather than starting a container with empty env, and (b) the Linux `op` install path on picklelab.

### 3a. Dev side: Automic Vault on the Mac

Section 3 covers picklelab. On the Mac, where `just dotenv` materializes a plaintext `.env` per checkout, [Automic Vault](https://github.com/automic-vault/automic-vault) (macOS-only) can hold dev copies of the same secrets instead:

- **Project Values at the main checkout root.** A value saved with `av save --project-directory=<picklehome root>` is selected for any working directory beneath it, so one save covers every worktree under `.claude/worktrees/`. Commands run as `av inject +KEY... -- <command>`.
- **1Password remains the source of truth; Automic Vault is a mirror.** Two ways in: `op read 'op://…' | av save --stdin --project-directory=<root> KEY` from a terminal where `op` works, or `just secret-entry --sink av KEY...` from a phone, approved with Automic Vault's iPhone Approval. Nothing keeps the mirror in sync, so rotation means re-mirroring.
- **Verified 2026-09-13** with `FLO_USERNAME`/`FLO_PASSWORD`: entered from a phone, approved per key, then `av inject +FLO_USERNAME +FLO_PASSWORD -- uv run python water/water_cli.py status` succeeded with no `.env` reachable. Test by calling the module directly, not through `just`: `set dotenv-load` walks parent directories and will load the main checkout's `.env`, masking whether injection worked.
- **Per-invocation approval is by design, not a cost to mitigate.** Every `av inject` (and every `av save`) prompts on-screen and pushes to the phone for a fresh human approval, no reuse across distinct commands. That's Automic Vault's actual security model, not friction to engineer around with Blessed Scripts or a read-only launcher policy.
- **Target shape: no materialized `.env` at all, once this is fully adopted.** Writing `.env` alongside `av`-injected secrets would defeat the point (two secrets-at-rest paths instead of zero). Getting there means `av inject +KEY...` fully replaces dotenv loading, not sitting alongside it.
- **Unsolved for dev use:** modules load everything from `.env` implicitly, but `av inject` names keys explicitly, and outside `homelab/services/*/.env.vars` there's no per-module list of which keys a command needs. This is the actual blocker to the target shape above, not the approval prompts.
- **Doesn't change deploys yet.** Deploying from the Mac still builds and scp's a `.env`; only section 3's host-side `op run` removes that.

### 4. Sensitive-data hygiene in docs

- Tighten `docs/CONVENTIONS.md`'s sensitivity table: currently reads "MAC, internal IP, geolocatable." Make explicit that WAN/public IPs, lat/lng, WiFi SSIDs, router admin credentials, and physical addresses are covered too, so it's unambiguous this applies to `homelab/` and `network/` docs, not just device MACs.
- Give freeform sensitive notes (e.g. a filled-in site survey) a home that isn't a committed README: agent memory, or a gitignored `<name>.local.md` beside a checked-in template that has the structure but no real values.
- Retarget taskwarrior task #285 (seapickle site survey) away from `README.md` to whichever of the above fits.

### 5. Deploy-script ownership split (app vs. host knowledge)

Section 1 moves `compose.yaml` to the app repo but leaves `deploy.sh` itself in picklehome. Looking at the actual scripts (2026-09-13 review) shows `deploy.sh` already carries a lot of app-specific knowledge that has to change every time the app does: `brineworks-server`/`brineworks-agent` hardcode port defaults and a `CONTAINER_UID` that must match the app's own Dockerfile, plus health-check endpoints and env-var names like `WORKSPACE_DEPLOY_KEY_B64`. That's the "changes in two places" problem in miniature — an app-side port or env-var change needs a matching picklehome PR to keep working.

**Boundary rule:** if a fact changes when the app changes (Dockerfile, config schema, entrypoint, ports), it belongs in the app repo. If it changes when the host/environment changes (different machine, different systemd/tailscale conventions), it stays in picklehome.

**Calling convention:** split each service's deploy into two scripts with a narrow, rarely-changing interface between them. The app repo owns a `deploy/picklelab.sh` (or similar) responsible for port/UID defaults, health-check polling, data-subdirectory layout + chown, build/onboarding steps, and its own required-env-var contract. picklehome's `deploy.sh` shrinks to: clone/pull the app repo, run `op run` against the filtered `.env.vars` template (section 3), call the app's script with `DATA_DIR` and the populated environment, then handle systemd unit link/enable/restart and `tailscale serve` registration — genuinely host-topology facts, consistent with the existing `compose.picklelab.yaml` precedent (section 1's overlay exception).

**brineworks-server, brineworks-agent, nikke** fit this cleanly: port defaults, container UID, health-check loops, and deploy-key installation move into each app's own repo (`brineworks`, `nikke-roster-scanner`). picklehome keeps systemd units (including nikke's sync timer), tailscale serve, and the generic clone/secrets/invoke wrapper.

**openclaw/pickleclaw doesn't fit the same shape.** openclaw is a third-party upstream tool (`ghcr.io/openclaw/openclaw`), not code Josh owns, so there's no single "app repo" to push deploy knowledge into. `pickleclaw` is instead a *configuration + companion-services* layer with **two independent deploy targets**: picklelab (production, via picklehome) and a dev VM (`dev-vm/`, OrbStack, meant as a rehearsal rig before changes reach picklelab). A partial shared-config pattern already exists — `openclaw-config/openclaw.env` (image pin) and `tools.json5`/`mcp.json5` are single-sourced in pickleclaw and applied to both targets (symlinked into picklehome for picklelab, applied via `dev-vm/sync-tools.sh` for the dev VM), with `tools.exec` mode as a documented deliberate divergence between them.

What's *not* unified is the big procedural logic: model chains, Telegram policy, and onboarding are hand-duplicated in `pickleclaw/scripts/provision.sh` (dev VM) and picklehome's `homelab/services/openclaw/deploy.sh` (picklelab), and they've already drifted in production — `provision.sh` and pickleclaw's `CLAUDE.md` still configure the now-retired `ollama-cloud/glm-4.7` as a fallback model, which picklehome's `deploy.sh` already migrated away from to glm-5.1 (pickleclaw taskwarrior `98dee518` tracks the fix). So for openclaw, the fix isn't "move picklehome's deploy logic into pickleclaw" the way it is for brineworks/nikke — it's **pickleclaw owning one shared "apply openclaw config" step that both the dev-VM flow and picklelab's `deploy.sh` call identically**, parameterized only at the known deliberate divergence points (`tools.exec` mode, Telegram enabled/disabled, `gateway.trustedProxies`). Relocating picklehome's config-set block into pickleclaw only helps if it also replaces `provision.sh`'s independent copy — otherwise the duplication just moves.

This is also tangled up with whether `provision.sh` itself still has a job: pickleclaw's `dev-vm/compose.yaml` has run the dev VM's gateway as a pinned Docker image since 2026-09-01, while `provision.sh` still installs openclaw natively via mise/npm — two different mechanisms for the same VM, only one of which is live. Filed as [pickleclaw#4](https://github.com/technicalpickles/pickleclaw/issues/4); resolving it is a prerequisite for designing the shared config-application step, since that step's shape depends on whether the dev VM path is compose-based going forward.

## Open questions for implementation planning

- ~~Exact repo name/visibility settings for `second-brain-agent` and the dev container~~ **Resolved:** `technicalpickles/second-brain-agent` and `technicalpickles/homelab-dev`, both private, each its own repo.
- ~~Whether `homelab/dev/` shares a repo with `second-brain-agent` or gets its own~~ **Resolved:** separate repos, no code or lifecycle coupling between them beyond superficial shape similarity.
- ~~Whether one Service Account can span multiple vaults~~ **Resolved:** yes, but vault access/permissions are immutable after creation, which is why the design uses two single-vault tokens rather than one multi-vault token — see section 3.
- ~~Remaining mechanics of the 1Password Service Account setup on picklelab: exact token provisioning steps, rotation policy, and how `deploy.sh` picks the right token per service~~ **Resolved:** implemented per `docs/superpowers/plans/2026-09-13-homelab-service-deploy-redesign.md` (sections 1-3 of this design). Tokens: two read-only, single-vault service-account tokens at `/etc/opt/homelab/op-token-{picklehome,pickleclaw}` (0600), no scheduled rotation (service-account tokens don't auto-expire; revoke/reissue via `op service-account` if ever needed). Per-service token selection: single-vault services reference their vault's token file directly via systemd `EnvironmentFile=`; the two dual-vault services (`openclaw`, `open-webui`) chain both via a small wrapper script (`op-run-dual.sh`) that overrides `OP_SERVICE_ACCOUNT_TOKEN` for the inner `op run` call.
- Whether section 3a (Automic Vault on the Mac) becomes part of this plan or its own follow-up. It's independent of the picklelab changes and can be adopted module by module.
- Section 5's app/host `deploy.sh` split for brineworks-server, brineworks-agent, and nikke: not yet scoped as an implementation plan, just the boundary rule and calling convention.
- Section 5's pickleclaw shared config-application step is blocked on [pickleclaw#4](https://github.com/technicalpickles/pickleclaw/issues/4) (whether `provision.sh` or `dev-vm/compose.yaml` is the real dev-VM mechanism going forward) — resolve that first.
