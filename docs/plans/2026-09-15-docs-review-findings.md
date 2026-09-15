# Documentation review: findings and fix plan

**Status:** findings complete 2026-09-15. Done same day: `root-claude-reshape`, `sensitive-data-redaction`. The remaining slugs in Part 6 are filed as taskwarrior tasks under `project:picklehome.docs` (and `picklehome.homelab` for the latent bugs).

Deep review of every CLAUDE.md, README, plan doc, and research doc against the
code at `bd21dbe`, plus mining of the 40 Claude Code sessions indexed for this
repo (2026-08-03 to 2026-09-15) via `cq`. Goal: find where docs still describe
the initial design rather than what shipped, and make CLAUDE.md files steer
implementation correctly.

Every finding below was verified against the filesystem or git. Session-mined
findings cite the session id prefix and date.

## Verdict

The concern is confirmed, but the rot is concentrated, not diffuse.

**What's healthy.** Every command table in every module README matches the
Justfile and argparse exactly (climate, blueair, hisense, network, locks,
garage, nest, sonos, birdfeeder, lg, water, lighting). Config YAML schemas
match their loaders. `climate/spec/hvac-spec.md` matches the code rule for
rule. The 2026-04-09 documentation-gaps fixes all stuck. Physical/household
facts the user corrected in sessions (brick vs block, ductwork, Porch AC
intentionally off) all landed in `network/TOPOLOGY.md` or the HVAC spec.

**Where it rotted.** Three places:

1. **Homelab deploy docs still describe the retired secrets model.** The
   `op run` redesign (PR #107, 2026-09-14) rewrote `homelab/services/README.md`
   but left `homelab/README.md` and 9 of 13 per-service READMEs on the old
   "Mac materializes `.env`, scp's it to picklelab" flow. Two READMEs say
   compose uses `env_file:` when the code comments say that's inert under
   `op run`. Root CLAUDE.md's Secrets section never mentions `op run` at all.
2. **Plan-doc status is systemically unreliable.** Six design docs carry a
   "not implemented" header for work that shipped. All 11 checkbox-style
   impl plans have zero ticked boxes regardless of completion. Three docs
   would actively mislead an agent into rebuilding an abandoned design.
3. **CLAUDE.md files are the wrong shape.** Root CLAUDE.md is reference-heavy
   and is the only CLAUDE.md that doesn't `@import` its README, which is why
   its tables drifted. `network/CLAUDE.md` is 76% command reference.
   `homelab/services/CLAUDE.md` says nothing about secrets or deploys.

Plus a fourth thing that isn't drift but needs a decision: **geolocatable
data is committed** (a full home street address in four files, MACs and
internal IPs in several more), against the repo's own convention.

## Part 1: What an agent gets wrong today

These are the rules an agent reading only the current CLAUDE.md files would
violate. Each is motivated by a verified doc gap or a session where it
actually happened.

### Root CLAUDE.md

- **Deploys need no `.env` and no `just dotenv`.** Secrets section
  (CLAUDE.md:42-69) describes only Mac-side `op inject`. Reality: deploys
  resolve secrets host-side via `op run` against
  `/etc/opt/homelab/op-token-picklehome`; `just dotenv` is local-dev only
  (Justfile:134-136). Session 328ef352 (09-15) re-derived this.
- **`set dotenv-load` walks up parent directories.** A worktree deliberately
  created without `.env` still gets the main checkout's real `.env` for
  anything run via `just`. Found 09-10 (session e3483ecd), filed as task
  `f6948c15`, still open, documented nowhere. "No `.env` means no live
  device access" is false.
- **New worktrees need their own `.env`** for direct `uv run` invocations
  (`ECOBEE_API_KEY not set` in sessions 73c04558, cd836def).
- **`git push` over SSH to github.com fails once with `Operation not
  permitted` then succeeds on retry** (session c21d67cf). The dotfiles rule
  defers to "the repo's CLAUDE.md," which only covers the homelab relay.
- **The sudoers allowlist has tooling.** The sudo section says "confirm with
  the user first" but never names `homelab/config/sudoers-deploy-ops` or
  `homelab/scripts/setup-deploy-access.sh`. User asked "don't we have a way
  to manage sudoers?" (09-15).
- Homelab Services table (CLAUDE.md:205-217) is missing `nikke`,
  `disk-hygiene`, `disk_monitor`. Auth Patterns table omits Moen Flo.
  `picklehome/locations.py` consumers are climate, locks, **and nest**
  (nest/nest_cli.py:18), not just "climate and locks."

### homelab/services/CLAUDE.md (23 lines, zero words on secrets or deploys)

An agent building a new service from `homelab/README.md:13-16` (the only
"adding a service" checklist in the repo) wires the old model end to end:
compose `env_file: .env`, unit `EnvironmentFile=.../<svc>/.env`, an scp
step. It fails at container start with an empty environment. Rules to add:

- Never write a resolved secret to disk on picklelab. What lands is
  `.env.op.template` (`op://` refs only, e.g. climate-auto-switch/deploy.sh:14);
  resolution happens in the unit's `ExecStart`. Exception: `backup`, tracked
  as task `4ea7fee5`.
- `op run` is inert against compose `env_file:`. Use
  `environment: ${VAR:?required}`. Currently only in five scattered code
  comments (brineworks-agent/compose.picklelab.yaml:9-11,68-71,
  brineworks-agent.service:12-15, github-actions-runner/compose.yaml:7,
  woodpecker/compose.yaml:4) while two READMEs say the opposite.
- Wrap `ExecStop` in `op run` too; compose interpolates `${VAR:?}` on every
  subcommand including `down` (commit 1096850). `brineworks-server.service:17`
  and `second-brain-agent.service:22` currently don't. Latent bug.
- Any unwrapped `docker compose` call needs placeholder env derived from
  `.env.vars` (the `sed s/$/=build-placeholder/` trick at Justfile:219,222,251,255).
  `just second-brain-agent-logs` (Justfile:262-267) lacks it. Latent bug.
- The token files `/etc/opt/homelab/op-token-{picklehome,pickleclaw}` are the
  real prerequisite. Nine units reference them; no README lists them.
- `deploy.sh` can only `sudo` what `homelab/config/sudoers-deploy-ops` allows.
- Four services deliberately don't use `_deploy-remote`: `openclaw` (scp's
  private includes first), `backup` (still scp's a real `.env`). Don't
  "fix" them. `disk-hygiene` and `obsidian-sync` also inline the ssh with
  no documented reason and could be collapsed.
- Four services' compose lives in another repo: brineworks-{server,agent}
  in `/opt/brineworks`, second-brain-agent in `/opt/second-brain-agent`,
  nikke in `/opt/nikke-roster-scanner`. Only `compose.picklelab.yaml` is
  here.
- When a fix is a pattern (e.g. "this function reads the root-only token
  before dropping to docker"), audit the whole file for the same pattern
  before shipping. Session 328ef352 (09-15) hit the same bug three times in
  three functions of `openclaw/deploy.sh`, three commits (4a7ecd9, daa68c5,
  bd21dbe).

### climate/CLAUDE.md

- **The picklelab timer runs a Docker image with `climate/config/*.yaml`
  baked in** (Dockerfile:12 `COPY climate/ climate/`). Editing `weather.yaml`
  or `schedule.yaml` and running `just climate-sync` changes the thermostat
  now, but the unattended timer keeps stale config until `just deploy-climate`.
  Stated only in the 2026-09-10 design doc's Rollout section. Nothing in
  climate/CLAUDE.md, climate/README.md, or docs/climate-setup.md.
- Spec-first rule names only `schedule.yaml`/`comforts.yaml`; the spec also
  governs `weather.yaml` thresholds and `thermostats.yaml` `hold_action`.
- `climate-comforts-sync --dry-run` cannot detect live setpoint drift
  (Ecobee silently widens too-narrow pairs; caused a months-long bug per
  the spec's setpoints preamble).
- Sensor names are static labels, not physical locations. The "Tracy
  Office" sensor was moved to the living room and media room for
  diagnostics while `climate-history` kept its name (sessions cd836def,
  73c04558). Belongs in climate/README.md "Room sensors."
- Task `3f72e752` notes the README claims sensor enrollment is app-only;
  it's API-writable via `climates[].sensors[]`.
- "Spec-first workflow" is verbatim-duplicated between climate/CLAUDE.md:5-13
  and climate/README.md:148-157.

### network/CLAUDE.md

- **Re-sample before contradicting a live complaint.** Session b108dc20
  (08-21): agent declared reported flakiness stale from one UniFi snapshot;
  user: "spend some time grounding yourself in the current state and history
  of the network before telling me about my current experience being
  incorrect." Turned out to be a stale-timestamp tool bug plus a live roam.
- **Read TOPOLOGY.md, CHANGELOG.md, and investigations/ before diagnosing
  hardware.** Same session, agent flagged Porch AC LR offline as "the main
  issue"; it's intentionally disabled and documented.
- `network/CHANGELOG.md:4,12,15` (header and two live unchecked follow-ups)
  use `just unifi-wifi ...`, a recipe that no longer exists. Correct spelling
  is `just unifi wifi ...`. CLAUDE.md:211-215 points agents at these
  follow-ups with no caveat.
- Lines 34-209 (the Scripts section, 76% of the file) are command reference
  and belong in network/README.md, which currently punts back to CLAUDE.md
  (README:21). Keep lines 1-32 and 211-231; result is a ~60-line CLAUDE.md.
- `network/floorplan_dxf_to_geojson.py` (472 lines, 5 commits since 09-02)
  is undocumented, has no `just` recipe. Its GeoJSON output and
  `climate/floorplan/` are gitignored and symlinked to the vault; the
  symlink target lives only in `.claude/second-brain.local.md` (excluded via
  `.git/info/exclude`), so a fresh worktree has no pointer to the
  `second-brain:link-project` skill that recreates it.

## Part 2: Stale claims by file

### homelab/ (highest volume)

**Tier 1, would steer an agent into the old model:**

| File | Claim | Reality |
|---|---|---|
| homelab/README.md:9-16 | Secrets section + "adding a new service" checklist: filter master `.env`, scp to host | `service-env --template` runs on picklelab, emits `.env.op.template`; nothing is scp'd except backup |
| homelab/README.md:49-51 | "`just dotenv` to refresh secrets, then `just deploy-<service>`" | Justfile:134-136 says the opposite |
| homelab/services/README.md:9-11 | "no local picklehome checkout needed" | `_deploy-remote` (Justfile:143-160) runs local git status/push first; the design doc's *goal* copied as fact |
| brineworks-agent/README.md:110 | compose.picklelab.yaml adds the filtered `env_file` | compose.picklelab.yaml:67-76 uses `environment:` with a comment saying env_file would be inert |
| github-actions-runner/README.md:29 | interpolation "from the auto-loaded project `.env`" | compose.yaml:5-9 says otherwise |
| taskchampion-sync/README.md:119 | `/srv/containers/taskchampion-sync/.env` | dead path; real artifacts are `.env.op.template` and `.env.build` |

**Tier 2, `just dotenv` as First-time Setup step 1** (not required): brineworks-server:19, brineworks-agent:56 (+19,27,45), second-brain-agent:32 (+25), taskchampion-sync:27, openclaw:116 (+93-94), woodpecker:65 (+51), github-actions-runner:39-40,72,104, open-webui:15. backup/README.md:43 is correct (backup really is still scp-based).

**Tier 3, "only its filtered `.env`, never the master `/opt/homelab/.env`"** (obsolete at both ends): brineworks-agent/README.md:112,117,127-130; second-brain-agent/README.md:88,97; brineworks-server/README.md:76; taskchampion-sync/README.md:99,101; openclaw/README.md:152,157-169. Also the `.env.vars` file headers: brineworks-agent, openclaw, second-brain-agent line 3, and six files whose line 2 says "extract a minimal `.env` for deployment".

**Tier 4, homelab/services/README.md internal:** :23 "via `_deploy-remote`" true for 9/13; :19-27 file table omits `.env.build`, `op-run-dual.sh`, `openclaw.image.env`; :96 `TS_AUTHKEY` "in the filtered `.env`"; :134 climate vars list `HOME_ZIP_CODE` (not in `.env.vars`) and omit `GOOGLE_POLLEN_API_KEY`; :236 brineworks-agent 2 vars (has 4); :282 taskchampion lists `_HOST` (only `_CLIENT_ID`); :346 openclaw lists `OPENCLAW_IMAGE` (not in `.env.vars`).

**Tier 5, scripts/service-env:** :2,13-14 still say "extract a subset of `.env` to copy to a remote host"; :3 documents `--strip-mustache`, which the parser rejects (`Unknown argument`); stripping is implied by `--template`.

**Tier 6, per-service:**
- brineworks-agent/README.md:21-27,45-49 and second-brain-agent/README.md:19-25 say to *add* `op://` refs, "skipped silently until then"; all exist (.env.template:90,99,104).
- brineworks-agent/README.md:60, second-brain-agent/README.md:36: deploy.sh "builds the image"; build is in the unit's `ExecStart`, output in journalctl.
- second-brain-agent/README.md:15-27 and nikke/README.md omit the host ssh-alias + deploy-key prerequisite (deploy.sh:25-29 and :29-34); fresh host fails at clone.
- brineworks-agent/README.md:129 lumps `WORKSPACE_DEPLOY_KEY_B64` with compose secrets; deploy.sh:69-74 resolves it via `op run --no-masking -- printenv`.
- brineworks-server/README.md:69,83 refer to `compose.yaml` as local; it's `/opt/brineworks/server/compose.yaml`.
- climate-auto-switch/README.md:53 `just climate-log lines=50` binds `lines=50` to `host` (verified with `--dry-run`); correct is `just climate-log picklelab 50`. :15 entrypoint is `uv run python -m climate.sync` (Dockerfile:20).
- taskchampion-sync/README.md:104 puts `TASKCHAMPION_SYNC_PORT` in "From `.env`"; it's `.env.build` (deploy.sh:13,23).
- openclaw/README.md:148 "no `build:` key" (compose.yaml:63-65,86-88 build two images); "deploy.sh runs `up -d`" (deploy.sh:654-662 goes through systemd). :158,181-182 `OPENCLAW_WIDGETS_HOST` as `.env`-sourced; actually deploy.sh:588 via `resolve_picklehome_var`. Nothing says why openclaw needs sudo (host script sources root-only token before docker), re-derived 09-15.
- open-webui/README.md:29-30 names `WEBUI_*` while pointing at `.env.vars` which has `OPEN_WEBUI_*` (compose.yaml:22-27 maps).
- backup/README.md:7 exclusions omit `open-terminal` (backup.sh:70); :9-13 "what's backed up" lists only climate-auto-switch; reapply-acls.sh grants eight paths.
- nikke/README.md:56-58,62-65 Gotchas reference `--db` flags and a Dockerfile `USER` now in `/opt/nikke-roster-scanner` (deleted here in 6839a88).
- disk-hygiene/README.md has no escalation note for genuine `/srv` growth (09-09 incident fix was manual `lvextend`+`resize2fs`, not in passwordless sudoers).
- disk_monitor/README.md: not a service (no unit/deploy.sh/compose) and nothing says so. Claims a 2-hourly schedule (:6) and "Hermes cron job" (:21) that exist nowhere; calls `disk-monitor-check` a "dry-run" (:18) but `main()` writes history (:250); "current trend" (:19) is `tail -20` of a CSV. disk_monitor.py:22 hardcodes `PICKLELAB_USER = "kenny"`, and returns 0 on ssh failure.
- homelab/dev/ is an orphan: post-ca5ad68 holds only deploy.sh; no recipe, README, unit, or mention anywhere.
- `.env.build` is never defined anywhere (closest: brineworks-server/deploy.sh:34-41 comment).
- homelab/README.md:37-47 table lists 9 services; missing openclaw, open-webui, nikke, disk-hygiene, disk_monitor.
- Justfile:493-494 unconditionally scp's `workspace-git-sync.sh`, which is gitignored (.gitignore:22) and absent; preflight at :475 doesn't check it. Fresh clone hard-fails. Latent bug.
- Session-mined, undocumented: the Mac vault at `~/Vaults/pickled-knowledge` is the source and picklelab's copy is a mirror (ae6cb22e, 09-11); `mise`-managed npm skips `postinstall` under `sudo -u <user> mise exec`; a failed `openclaw doctor --fix` has no rollback (zero repo mentions of "rollback").

### Root

- CLAUDE.md:42-69 Secrets: no `op run`. CLAUDE.md:205-217 missing nikke/disk-hygiene/disk_monitor. CLAUDE.md:104-111 missing Moen Flo. CLAUDE.md:175 scripts/ omits `locations-filter.jq`, `secret_entry.py`. Directories omits `homelab/config/`, `homelab/dev/`, `homelab/scripts/`, `docs/superpowers/plans/`, `docs/research/`, floor plan.
- README.md:87 homelab blurb ("a couple of small APIs") vs 14 services incl. two always-on Claude agents, CI, openclaw, open-webui. "What's Here" omits nest (predates README's last edit 2026-07-11), lg, birdfeeder, water.
- docs/CONVENTIONS.md: zero mentions of `docs/research/`, `docs/superpowers/`, `.parkinglot/`. Naming rule violated by `docs/plans/kenny-deploy-options.md`.

### climate/, network/, small modules

- docs/plans/2026-03-26-climate-auto-switch-docker.md says the entrypoint runs `--clear-holds`; Dockerfile entrypoint doesn't (removed by the 09-10 redesign, hvac-spec.md:68-70).
- climate/README.md:34 location fields omit `nest_structures`.
- network/README.md:21 punts UniFi reference to CLAUDE.md (backwards).
- docs/plans/2026-03-18-outdoor-wifi-coverage.md: stalled, Porch AC LR still offline (TOPOLOGY.md:78, CHANGELOG.md:19-22), no marker.
- `wifi-diag.py --no-scan` (:347) undocumented.
- lighting/README.md says aiohue has "self-signed SSL cert handling built in"; it's hand-rolled in lighting/hue.py:46-50. No `tests/lighting/` exists.
- water/README.md "Module structure" omits `flo/scrub.py`.
- lg/README.md command block omits `[--json]` on `status` (lg_cli.py:353).
- birdfeeder: `VICOHOME_REGION` documented (README:56) and read (auth.py:12) but not in `.env.template`.
- Undocumented `*_TOKEN_PATH` overrides: `YALE_TOKEN_PATH` (locks/yale/auth.py:28), `ALADDIN_TOKEN_PATH` (garage/aladdin/auth.py:21), `NEST_TOKEN_PATH` (nest/sdm/auth.py:30).
- garage `DEVICE_STATUS` dict (client.py:49-52) has no README table.
- sonos: `tests/sonos/test_config.py` tests `roster.py`.

## Part 3: Plan-doc ledger

Checkbox state is a dead signal: all 11 checkbox-style impl plans have zero
ticked boxes, implemented or not. Do not read checkboxes as status.

**Actively misleading (would cause an agent to rebuild or diverge):**

| Doc | Problem |
|---|---|
| docs/plans/2026-07-04-workspace-git-sync-picklelab-rollout.md:3 | "Status: design, not yet implemented"; proposes LLM conflict-escalation as to-build. It shipped as an hourly cron, and the LLM escalation was built then **removed 2026-09-12** as unsafe (openclaw/README.md:215). |
| docs/plans/2026-03-28-garage-aladdin-design.md + -impl.md | Mandates `genie-partner-sdk` + OAuth (design:5,40; impl:26-34,265-268,305-338). Code uses direct AWS Cognito + `api.smartgarage.systems` (garage/aladdin/auth.py:12-17). Zero "genie" in code. Deliberate pivot, never noted. |
| docs/plans/2026-09-04-moen-flo-plan.md:538-545 | Says `FLO_USE_SSO` defaults True; shipped water/flo/auth.py:53-61 defaults False after live testing. Also missing: `--sink av` Automic Vault mode added to `scripts/secret_entry.py`. |
| docs/plans/2026-07-21-open-terminal-plan.md:15 | Pins `open-terminal:0.11.34`, "bump deliberately, not `:latest`". open-webui/compose.yaml:48 uses floating `:slim` (commit 984e9fd). Policy change undocumented. |
| docs/superpowers/plans/2026-09-13-homelab-service-deploy-redesign.md:19 | Says backup migration is "(see Task 11)"; the plan's own :620 note admits this is wrong. Line 19 uncorrected. |
| docs/plans/2026-08-10-homelab-service-deploy-design.md | Top marker (:30) is correct. Body never reconciled: :47 says `just` runs on the host (it doesn't; Justfile:161 calls deploy.sh); :47 "no local checkout needed" (false); :55 says deploy.sh runs `op run` (it's in the unit; :108 says so, doc self-contradicts); :55 dynamic token selection (static); :34 says compose.picklelab.yaml goes away (stays for 3); :41 frames homelab/dev extraction as open (shipped ca5ad68); :79 "still builds and scp's a `.env`" (false for 12/13). |

**Stale "not implemented" headers on shipped work:** 2026-03-16 climate-restructure ("Planned"), 2026-05-24 locks-health ("Status: design"; also extended with `is_wedged`, `bridge_offline_reason` not in design), 2026-06-18 woodpecker ("pending implementation plan"), 2026-06-30 openclaw ("ready to implement", 63+ commits since), 2026-07-21 open-terminal-design ("pending implementation plan"), 2026-09-10 climate-seasonal ("design approved, not implemented").

**Superseded without a note:** 2026-03-17 outdoor-temp-comfort-mode (by 2026-09-10 redesign), 2026-03-17 wifi-survey-agent-experiment (by the GeoJSON pipeline), kenny-deploy-options.md (by 2026-04-09 deploy-sudoers; `technicalpickles` user, not `kenny`).

**Accurate marker (the one exception):** 2026-06-13 tracy-office-thermal-comfort "research complete, nothing deployed yet". Still true; task `174ada3d` pending.

**Unlinked research:** `bss-transition-management`, `openclaw-homelab`, `wifi-retry-rates`, `openwebui-extractors` have no inbound link from any README or CLAUDE.md. `lg-thinq` and `hisense-connectlife` are linked.

## Part 4: Committed geolocatable data (needs a decision)

Against docs/CONVENTIONS.md's own rule. Values deliberately not reproduced here.

- **Full home street address:** network/floorplan_dxf_to_geojson.py:2,44; network/TOPOLOGY.md:165; network/docs/floorplan-markup-legend.md:65; docs/plans/2026-05-24-locks-health-aggregation.md:122,139,178,183-184 (two addresses); -impl.md:688.
- **MACs / MAC-shaped ids:** sonos/README.md:32 (RINCON uid, while speakers.example.yaml:19,21 correctly redacts); garage/README.md:81; network/TOPOLOGY.md:384; network/CHANGELOG.md:172,180; network/docs/bgw-reference.md:16; docs/plans/2026-05-24-locks-health-aggregation.md:191 (prefix); tests/birdfeeder/vicohome/test_client.py:41-43,113-115 (serial + LAN IP + MAC, "structurally faithful to a real response").
- **Internal LAN IPs beyond the two gateways in root CLAUDE.md:** network/TOPOLOGY.md:37-39,55-57,63-78,394-398,431; network/docs/bgw-reference.md:3,7,45,98,113; network/investigations/cloudflare-peering-2026-03.md:137; docs/plans/2026-03-21-hue-integration-design.md:11; -plan.md:606,613,614.

TOPOLOGY.md is an inventory by design, so the real question is whether the
convention is wrong (this is a private repo) or the files are. Either way
the address should go; that's a redaction plus, if wanted, a history rewrite,
which is a separate decision.

## Part 5: Why this happened (from session mining)

Planned work sessions record their decisions. Every mid-session design
decision in the two big deploy-redesign sessions (7372e781, b2db642b) is in
the design doc or the plan, often verbatim. The gaps come from **incident
and firefighting sessions** (disk full 10cc3454, backup ACLs be980484,
openclaw sudo fixes 328ef352, vault confusion ae6cb22e) which have no
"close the docs" step, and from **plan docs having no post-ship step**:
the status header gets written at design time and never touched again.

## Part 6: Proposed fix plan

Ordered so each step is independently mergeable. Slugs, not numbers.

- `root-claude-reshape` (done 2026-09-15): root CLAUDE.md gains `@README.md`; Integrations,
  Homelab Services, and Directories tables move to README.md (single source);
  Secrets section rewritten to lead with the `op run` deploy model and
  demote `just dotenv` to local dev; add the dotenv-load, worktree `.env`,
  github.com SSH retry, and sudoers-tooling rules. Fix the three table
  omissions and the locations.py consumer list.
- `homelab-claude-rules`: homelab/services/CLAUDE.md gains the Part 1 rules
  (secrets invariant, env_file inert, ExecStop wrap, placeholder env, token
  files, sudoers constraint, the four deliberate exceptions, the four
  external-compose services, audit-the-whole-file).
- `homelab-readme-sweep`: homelab/README.md Secrets section and service
  table rewritten; the 9 per-service READMEs lose `just dotenv` and the
  filtered-`.env` language and gain the token-file prerequisite; use
  climate-auto-switch/README.md:42-46 as the template. Fix `.env.vars`
  headers and `scripts/service-env` self-doc. Add "how to add a service"
  under the current model. Document `.env.build`. Resolve disk_monitor
  (delete, or document as a local tool) and homelab/dev (delete or README).
- `homelab-latent-bugs`: bare `ExecStop` in two units; `second-brain-agent-logs`
  placeholder; unconditional `workspace-git-sync.sh` scp; `disk_monitor.py`
  hardcoded user. Code, not docs, but found here; each is a one-line fix.
- `climate-claude-rules`: deploy-to-take-effect, broadened spec-first rule,
  dry-run caveat, sensor-name caveat, sensor-enrollment correction (task
  `3f72e752`); dedupe the Spec-first section.
- `network-claude-reshape`: move lines 34-209 to network/README.md; add the
  two session-mined rules; fix CHANGELOG.md:4,12,15; document the floor-plan
  pipeline and the vault symlink recreation.
- `plan-status-headers`: docs/CONVENTIONS.md gains a required status header
  (`planned | in-progress | implemented YYYY-MM-DD | superseded by <doc> |
  abandoned`), a "partial implementation names which sections" rule, a
  "checkboxes are not status" note, and descriptions of `docs/research/`,
  `docs/superpowers/plans/`, `.parkinglot/`. Then sweep: fix the six stale
  headers, the four superseded docs, annotate the six divergences in Part 3,
  reconcile the 2026-08-10 design body, rename kenny-deploy-options.md.
  Link the four orphan research docs from their consuming READMEs.
- `sensitive-data-redaction` (done 2026-09-15): kept private LAN IPs and narrowed the CONVENTIONS rule; redacted the address, masked MACs to OUI, synthesized test fixtures, added `tests/test_no_sensitive_identifiers.py`. Current tree only, history untouched.
- `small-module-touchups`: the Part 2 small-module items; all one-liners.
