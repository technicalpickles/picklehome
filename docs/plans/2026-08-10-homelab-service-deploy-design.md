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

### 4. Sensitive-data hygiene in docs

- Tighten `docs/CONVENTIONS.md`'s sensitivity table: currently reads "MAC, internal IP, geolocatable." Make explicit that WAN/public IPs, lat/lng, WiFi SSIDs, router admin credentials, and physical addresses are covered too, so it's unambiguous this applies to `homelab/` and `network/` docs, not just device MACs.
- Give freeform sensitive notes (e.g. a filled-in site survey) a home that isn't a committed README: agent memory, or a gitignored `<name>.local.md` beside a checked-in template that has the structure but no real values.
- Retarget taskwarrior task #285 (seapickle site survey) away from `README.md` to whichever of the above fits.

## Open questions for implementation planning

- ~~Exact repo name/visibility settings for `second-brain-agent` and the dev container~~ **Resolved:** `technicalpickles/second-brain-agent` and `technicalpickles/homelab-dev`, both private, each its own repo.
- ~~Whether `homelab/dev/` shares a repo with `second-brain-agent` or gets its own~~ **Resolved:** separate repos, no code or lifecycle coupling between them beyond superficial shape similarity.
- ~~Whether one Service Account can span multiple vaults~~ **Resolved:** yes, but vault access/permissions are immutable after creation, which is why the design uses two single-vault tokens rather than one multi-vault token — see section 3.
- Remaining mechanics of the 1Password Service Account setup on picklelab: exact token provisioning steps, rotation policy (service account tokens don't auto-expire; default to no scheduled rotation, document revoke/reissue steps inline at the point of use), and how `deploy.sh` picks the right token per service — still open, resolve during plan-writing.
