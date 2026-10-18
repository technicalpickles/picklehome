# Woodpecker Agent Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send Woodpecker CI work to the laptop VM agent while it is online, and to picklelab's agent when it is not, with no manual toggling.

**Architecture:** A stdlib-only Python reconcile script runs as a profile-gated service in the existing woodpecker compose (`profiles: [switch]`, `network_mode: service:ts-woodpecker`, so it reaches the API on `localhost:8000`). A systemd timer (about every minute) runs it with `docker compose run --rm --no-deps`. Each run reads `GET /api/agents`, decides the desired state from the laptop agent's `last_contact`, and `PATCH`es `no_schedule` and `filters` on the two agents. It is stateless: every tick converges on the desired state, so a missed tick or restart costs nothing.

**Tech Stack:** Python 3.12 stdlib (`urllib`, `json`, `argparse`), pytest, docker compose, systemd timer, 1Password `op run`.

**Spec:** taskwarrior task `4855467a-b27c-4cd2-9368-8f5f0e678c1b` (description holds the design and the upstream findings). There is no separate spec doc.

## Global Constraints

- Python stdlib only in the script; image is `python:3.12-slim`; no `uv`, no third-party deps.
- The two Woodpecker agent names come from env, never hardcoded: `LAPTOP_AGENT_NAME`, `PICKLELAB_AGENT_NAME`.
- Laptop agent default filters: `{"!host": "laptop"}` (key `!host`, value `laptop`; see `homelab/services/woodpecker/README.md` "Remote agents").
- Staleness: laptop is "up" when `now - last_contact <= stale_after` (seconds, env `STALE_AFTER_SECONDS`, default `300`). The default is a guess until `verify-api-fields` measures `last_contact` cadence.
- Safety invariant: at no point may both agents be unschedulable. PATCH order enforces it (enable the target agent before disabling the other).
- Fail open: when the laptop agent is missing, never connected (`last_contact == 0`) or stale, the desired state is picklelab schedulable and laptop filters at default.
- Secrets reach the container only via compose `environment: ${VAR:?required}` under `op run`; never `env_file:`, never baked into the image (see `homelab/services/CLAUDE.md`).
- Do not commit geolocatable identifiers; do not write a literal `op://` scheme in prose in `.env.template` (see root `CLAUDE.md`).
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Create the worktree with `wt switch --create woodpecker/agent-switch --yes --no-cd --format=json`.
- Step slugs, not ordinals, in commit messages and cross-references.

## Review Focus

- Laptop agent absent from `GET /api/agents` entirely (never registered, deleted): must be treated as stale, not crash.
- `last_contact == 0` (registered, never connected): stale.
- A run that dies between its two PATCHes (API error, timeout): the next tick must converge, and the invariant above must still hold in the half-applied state.
- Picklelab agent name matches zero or more than one agent: raise with a message naming the agent and what was found; never guess.
- Revoked or wrong token (401/403) while in "laptop preferred" state, with the laptop since gone: CI would be stuck. Needs a loud failure (non-zero exit, unit goes `failed`) and a documented manual reset (`--reset`).
- An operator who sets `no_schedule` on picklelab by hand for maintenance gets overridden on the next tick. Accept and document; do not build an override flag (YAGNI).

---

### Task verify-api-fields

Gate for everything else. Manual, needs the user's API token. Nothing is written to the repo.

**Files:** none (findings go into the task annotation and, if they differ, into the later tasks before starting them).

- [ ] **Step 1: User creates the token.** In the Woodpecker UI (user must be admin), Profile, "Personal Access Token". Save to 1Password, vault `picklehome`, item `Woodpecker API`, field `token`.
- [ ] **Step 2: Read the live agent list.** From picklelab (the API is loopback-only): `ssh picklelab 'cd /opt/homelab/homelab/services/woodpecker && docker compose -f compose.yaml -f compose.picklelab.yaml exec -T ts-woodpecker wget -qO- --header "Authorization: Bearer <token>" http://127.0.0.1:8000/api/agents'`. Expected: JSON array; every agent has `id`, `name`, `last_contact`, `no_schedule`, `filters`.
- [ ] **Step 3: Record the real agent names** (both agents, exact strings) for `LAPTOP_AGENT_NAME` and `PICKLELAB_AGENT_NAME`.
- [ ] **Step 4: Measure `last_contact` cadence** on the connected agents: sample twice, 10 seconds apart, a few times. Set `stale_after` to at least 3x the observed update interval and long enough to ride out a short wifi blip (default 300 stands unless the interval says otherwise).
- [ ] **Step 5: Confirm the PATCH body.** Check upstream `server/api/agent.go` `PatchAgent` for which fields it assigns (`name`? `no_schedule`, `filters`). If `name` is assigned, every PATCH must send the current name. Also read what the handler does when `no_schedule` is set or filters change (the queue-related branch around line 149), so the rollout test expects the right side effect.
- [ ] **Step 5b: Capture a fixture.** Save the real `GET /api/agents` response to `tests/fixtures/woodpecker/agents.json` with every `token` value removed and any other secret-looking field blanked (the agent model has a `token` field; check the real output). Agent names, ids, labels and filters stay: they are not sensitive, and `fake-server-and-scenarios` loads this file so the fake can never drift from the real shape unnoticed.
- [ ] **Step 6: Annotate the task** with the confirmed field names, agent names, cadence, and PATCH behaviour: `task 4855467a-b27c-4cd2-9368-8f5f0e678c1b annotate "..."`.

---

### Task decide-logic

**Files:**
- Create: `homelab/services/woodpecker/agent_switch.py`
- Test: `tests/homelab/test_woodpecker_agent_switch.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Config: laptop_name: str; picklelab_name: str; stale_after: int = 300; laptop_filters: dict[str, str] = field(default_factory=lambda: {"!host": "laptop"})`
  - `@dataclass(frozen=True) class Patch: agent_id: int; body: dict`  where `body` is `{"name": str, "no_schedule": bool, "filters": dict[str, str]}`
  - `def decide(agents: list[dict], now: int, cfg: Config) -> list[Patch]` returns patches in the order they must be applied; empty list when already converged. Raises `ValueError` when the picklelab agent matches zero or several agents.

The test file loads the module by path with `importlib.util.spec_from_file_location` (the service dir name is not an importable package).

- [ ] **Step 1: Write the failing tests** in `tests/homelab/test_woodpecker_agent_switch.py`. Fixture helpers build agent dicts `{"id", "name", "last_contact", "no_schedule", "filters"}`. Tests, each with exact assertions:
  - `test_laptop_fresh_prefers_laptop`: laptop `last_contact = now - 10`, both at defaults. Expect exactly two patches, in order: laptop `filters == {}` and `no_schedule == False`, then picklelab `no_schedule == True`.
  - `test_laptop_stale_restores_defaults_in_safe_order`: state is laptop-preferred (laptop filters `{}`, picklelab `no_schedule=True`), laptop `last_contact = now - 301`. Expect two patches, in order: picklelab `no_schedule == False` first, then laptop `filters == {"!host": "laptop"}`.
  - `test_boundary_is_fresh`: `now - last_contact == stale_after` counts as fresh.
  - `test_never_connected_is_stale`: `last_contact == 0` with defaults, expect `[]`.
  - `test_laptop_missing_is_stale`: no laptop agent in the list, picklelab at `no_schedule=True`, expect one patch re-enabling picklelab; no exception.
  - `test_converged_is_noop`: desired state already in place, expect `[]` (both for fresh and stale cases).
  - `test_picklelab_missing_raises`, `test_picklelab_duplicate_raises`: `pytest.raises(ValueError, match=<agent name>)`.
  - `test_patch_body_carries_name`: every patch body has the agent's current `name`.
- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/homelab/test_woodpecker_agent_switch.py -v`. Expected: FAIL (module/file missing).
- [ ] **Step 3: Implement `Config`, `Patch`, `decide`** in `homelab/services/woodpecker/agent_switch.py`. Compute `laptop_up` from the laptop agent (missing or `last_contact == 0` means not up). Build the desired `(no_schedule, filters)` for each agent, emit a patch only for an agent whose current values differ, and order them: when laptop is up, laptop first; when not, picklelab first.
- [ ] **Step 4: Run to verify pass.** Same command. Expected: all PASS.
- [ ] **Step 5: Commit.** `git add homelab/services/woodpecker/agent_switch.py tests/homelab/test_woodpecker_agent_switch.py && git commit -m "feat(woodpecker): decide-logic for the agent switch"`

---

### Task api-client-and-cli

**Files:**
- Modify: `homelab/services/woodpecker/agent_switch.py`
- Test: `tests/homelab/test_woodpecker_agent_switch.py`

**Interfaces:**
- Consumes: `Config`, `Patch`, `decide` from `decide-logic`.
- Produces:
  - `def list_agents(base_url: str, token: str, opener=urllib.request.urlopen) -> list[dict]`
  - `def patch_agent(base_url: str, token: str, patch: Patch, opener=urllib.request.urlopen) -> None`
  - `def run(cfg: Config, base_url: str, token: str, *, dry_run: bool, reset: bool, now: int, opener=urllib.request.urlopen) -> list[Patch]` returns the patches it applied (or would have, under `dry_run`).
  - `def main(argv: list[str] | None = None) -> int` reads env `WOODPECKER_API_TOKEN` (required), `WOODPECKER_URL` (default `http://127.0.0.1:8000`), `LAPTOP_AGENT_NAME`, `PICKLELAB_AGENT_NAME`, `STALE_AFTER_SECONDS`; flags `--dry-run`, `--reset`. Exit `0` on success, `1` on any error, with the error on stderr.

`reset=True` ignores the laptop state and decides as if it were stale (picklelab schedulable, laptop filters default). Dry run prints one line per patch (`would PATCH <name>: no_schedule=<b> filters=<dict>`) and sends nothing. Errors (HTTP status, URL error, timeout) raise with the endpoint, status and body so a `401` is distinguishable from a `500` (per root `CLAUDE.md`: no swallowing). Do not catch inside `run`; catch once in `main`. Use `timeout=10` on every request.

- [ ] **Step 1: Write failing tests** with a fake `opener` that records requests and returns canned responses:
  - `test_run_applies_patches_in_order`: two PATCH requests, paths `/api/agents/<laptop id>` then `/api/agents/<picklelab id>`, `Authorization: Bearer <token>`, JSON bodies matching the `Patch`.
  - `test_dry_run_sends_no_patch`: only the `GET` was made.
  - `test_reset_forces_defaults_even_when_laptop_fresh`.
  - `test_http_401_raises_with_status_and_body`: message contains `401` and the endpoint.
  - `test_main_exit_code_1_on_error`: `main` returns `1` and writes the message to stderr when the opener raises; returns `0` on success.
  - `test_partial_failure_propagates`: second PATCH raises, `run` raises, first PATCH already sent (convergence on the next tick is `decide`'s job, already tested).
- [ ] **Step 2: Run to verify failure.** Same pytest command. Expected: FAIL.
- [ ] **Step 3: Implement** the four functions above in `agent_switch.py` with `if __name__ == "__main__": raise SystemExit(main())`.
- [ ] **Step 4: Run to verify pass**, then the whole `tests/homelab/` dir to check nothing else moved.
- [ ] **Step 5: Commit.** `git commit -m "feat(woodpecker): api client and cli for the agent switch"`

---

### Task fake-server-and-scenarios

Exercises the script over real HTTP against an in-process fake Woodpecker, with a fake clock, so the whole thing can be tested on the Mac with no docker, no token and no picklelab.

**Files:**
- Create: `tests/homelab/fake_woodpecker.py` (test helper, not a test module)
- Create: `tests/homelab/test_woodpecker_agent_switch_scenarios.py`
- Read: `tests/fixtures/woodpecker/agents.json` (captured in `verify-api-fields`; until it exists, inline a minimal agent list and swap to the fixture afterwards)

**Interfaces:**
- Consumes: `run`, `Config`, `main` from `api-client-and-cli`.
- Produces: `class FakeWoodpecker` with `start() -> str` (returns base URL on `127.0.0.1`, random free port), `stop()`, `agents: dict[int, dict]` (mutable state, seeded from the fixture), `patch_log: list[tuple[int, dict]]` (every accepted PATCH, in order), `fail_next(method: str, status: int)` (next request of that method returns `status`, once), and `require_token: str`. It implements only `GET /api/agents` and `PATCH /api/agents/{id}` (replaces `no_schedule`, `filters`, `name` like upstream), returns `401` on a missing or wrong bearer token, and after every accepted PATCH records whether both agents are `no_schedule` (`invariant_violations: list`).

- [ ] **Step 1: Write the fake server** with `http.server.ThreadingHTTPServer` in a daemon thread. Keep it under ~80 lines; it validates nothing beyond what the script relies on.
- [ ] **Step 2: Write scenario tests** (each runs `run(...)` per tick with an explicit `now`, no sleeping):
  - `test_laptop_wakes_then_sleeps`: ticks at t=0 (laptop `last_contact` fresh), t=60, then the laptop stops updating `last_contact`, ticks continue until `stale_after` passes. Assert the agent states after each tick, that exactly the expected PATCHes were sent (none on steady ticks), and `invariant_violations == []` throughout.
  - `test_converges_within_one_tick_of_a_change`: flip `last_contact` freshness, run one tick, assert desired state reached.
  - `test_no_flap_inside_stale_window`: `last_contact` jittering inside `stale_after` produces zero PATCHes after the first transition.
  - `test_midrun_failure_then_recovery`: `fail_next("PATCH", 500)` on the second PATCH of a transition; the first run raises, the half-applied state still has one schedulable agent, and the next tick completes the transition.
  - `test_bad_token_exits_1_and_changes_nothing`: wrong token, `main(...)` returns `1`, stderr mentions `401`, `patch_log == []`.
  - `test_reset_from_laptop_preferred`: seed laptop-preferred state, `--reset` restores defaults.
  - `test_dry_run_leaves_server_untouched`: `patch_log == []`, stdout has `would PATCH` lines.
  - `test_fixture_roundtrip`: every agent in the fixture parses through `decide` without `KeyError` (this is the check that catches real-shape drift).
- [ ] **Step 3: Run.** `uv run pytest tests/homelab/ -v`. Expected: PASS. The sandbox may refuse binding a local port; if the failure is a bind `PermissionError`, run these tests with the sandbox off (loopback only) and note it in the test module docstring. Do not skip the tests by default.
- [ ] **Step 4: Commit.** `git commit -m "test(woodpecker): fake server and scenario tests for the agent switch"`

---

### Task compose-and-image

**Files:**
- Create: `homelab/services/woodpecker/Dockerfile.agent-switch`
- Modify: `homelab/services/woodpecker/compose.yaml`
- Modify: `homelab/services/woodpecker/.env.vars`
- Modify: `.env.template` (repo root)

**Interfaces:**
- Consumes: `agent_switch.py` `main` (entrypoint).
- Produces: compose service `woodpecker-agent-switch` runnable as `docker compose --profile switch run --rm --no-deps woodpecker-agent-switch [--dry-run|--reset]`.

- [ ] **Step 1: Add the secret to 1Password first** (user, done in `verify-api-fields`), then add `WOODPECKER_API_TOKEN={{ op://picklehome/Woodpecker API/token }}` to `.env.template` next to the other Woodpecker vars, and `WOODPECKER_API_TOKEN` to `.env.vars`. Also add `LAPTOP_AGENT_NAME` and `PICKLELAB_AGENT_NAME` as plain (non-secret) compose `environment:` literals, not 1Password entries. Check `.env.template` for the prose gotcha (no literal scheme in comments).
- [ ] **Step 2: Write `Dockerfile.agent-switch`**: `FROM python:3.12-slim`, `COPY agent_switch.py /app/`, `USER 65534`, `ENTRYPOINT ["python", "/app/agent_switch.py"]`. Build context is the woodpecker service dir.
- [ ] **Step 3: Add the compose service** to `compose.yaml`: `build: {context: ., dockerfile: Dockerfile.agent-switch}`, `profiles: [switch]`, `network_mode: service:ts-woodpecker`, `environment:` with `WOODPECKER_API_TOKEN=${WOODPECKER_API_TOKEN:?required}`, `WOODPECKER_URL=http://127.0.0.1:8000`, the two agent names, `STALE_AFTER_SECONDS`. No `restart:`; no `depends_on` (the timer unit uses `--no-deps`).
- [ ] **Step 4: Verify it parses and builds.** `env WOODPECKER_API_TOKEN=build-placeholder <other vars from .env.vars> docker compose -f compose.yaml -f compose.picklelab.yaml --profile switch config -q` exits 0; `... --profile switch build woodpecker-agent-switch` succeeds. Also confirm `docker compose ... config --services` (no profile) does not list the new service, so `woodpecker.service`'s `up -d` leaves it alone.
- [ ] **Step 4b: Local smoke test of the image.** Start the fake server from `fake_woodpecker.py` on the Mac (a tiny `python -m` entry point or a throwaway snippet), then `docker run --rm --add-host host.docker.internal:host-gateway -e WOODPECKER_URL=http://host.docker.internal:<port> -e WOODPECKER_API_TOKEN=<fake token> -e LAPTOP_AGENT_NAME=... -e PICKLELAB_AGENT_NAME=... <built image> --dry-run`. Expected: exit 0 and `would PATCH` lines. Re-run without `--dry-run` and check the fake's `patch_log`. This proves the image, entrypoint, env wiring and non-root user work, without picklelab. (`network_mode: service:ts-woodpecker` cannot be exercised locally; that part is covered by rollout phase 0.)
- [ ] **Step 5: Commit.** `git commit -m "feat(woodpecker): compose service and image for the agent switch"`

---

### Task timer-units-and-deploy

**Files:**
- Create: `homelab/services/woodpecker/woodpecker-agent-switch.service`
- Create: `homelab/services/woodpecker/woodpecker-agent-switch.timer`
- Modify: `homelab/services/woodpecker/deploy.sh`
- Modify: `Justfile` (recipes next to `woodpecker-status`)

**Interfaces:**
- Consumes: compose service from `compose-and-image`.
- Produces: units `woodpecker-agent-switch.service` (oneshot) and `.timer`; `deploy.sh` installs both; the timer is enabled only when `SWITCH_TIMER_ENABLED=1` is set at the top of `deploy.sh` (ships as `0` so the first deploy changes nothing, per the `TIMER_PAUSED` guard pattern in `climate-auto-switch/deploy.sh`).

- [ ] **Step 1: Write the service unit** modeled on `climate-auto-switch.service`: `Type=oneshot`, `TimeoutStartSec=60`, `After=woodpecker.service`, `WorkingDirectory=/opt/homelab/homelab/services/woodpecker`, `EnvironmentFile=/etc/opt/homelab/op-token-picklehome`, `ExecStart=/usr/bin/op run --env-file=<dir>/.env.op.template -- /usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml --profile switch run --rm --no-deps woodpecker-agent-switch $SWITCH_ARGS` where `SWITCH_ARGS` comes from `EnvironmentFile=-/etc/opt/homelab/woodpecker-agent-switch.env` (holds `--dry-run` during rollout phase 1; absent means live).
- [ ] **Step 2: Write the timer**: `OnCalendar=minutely`, `AccuracySec=10s`, `[Install] WantedBy=timers.target`. No `Persistent=true`.
- [ ] **Step 3: Extend `deploy.sh`**: after `pull`, build with `docker compose ... --profile switch build` using the existing `env_overrides` placeholders; link both units next to the existing `ln -sf` for `woodpecker.service`; after `daemon-reload`, enable and restart the timer only when `SWITCH_TIMER_ENABLED=1`, else print a "timer not enabled" line.
- [ ] **Step 4: Add Justfile recipes** `woodpecker-switch-logs` (journalctl for the unit, via ssh, like `woodpecker-logs`) and `woodpecker-switch-reset` (ssh, runs the compose `run` with `--reset`).
- [ ] **Step 5: Verify locally.** `bash -n homelab/services/woodpecker/deploy.sh` (plus `shellcheck` if installed) and `just --list | grep switch`. For the units, run `systemd-analyze verify` in a throwaway container since the Mac has none: `docker run --rm -v "$PWD/homelab/services/woodpecker:/w:ro" debian:bookworm sh -c 'apt-get update -qq && apt-get install -y -qq systemd >/dev/null && systemd-analyze verify /w/woodpecker-agent-switch.service /w/woodpecker-agent-switch.timer'`. Expected: no syntax or unknown-key errors; warnings that `/usr/bin/op` or the `EnvironmentFile` paths don't exist are fine here. Real verification of the timer itself happens in `rollout` phase 0 and 1.
- [ ] **Step 6: Commit.** `git commit -m "feat(woodpecker): timer, units and deploy wiring for the agent switch"`

---

### Task docs

**Files:**
- Modify: `homelab/services/woodpecker/README.md` (new "Agent switch" subsection under "Remote agents")
- Modify: `homelab/services/README.md` (registry row for the switch)
- Create: `docs/adr/NNNN-woodpecker-agent-switch.md` (next free number; Context / Decision / Consequences)

- [ ] **Step 1: README subsection** covers: what it does, the fail-open default, the PATCH-order invariant, `--dry-run` / `--reset`, the `SWITCH_TIMER_ENABLED` guard, the manual-override caveat, how to read logs, and the arch-drift note with the label fix (see `rollout` phase 3).
- [ ] **Step 2: Registry row and ADR** (decision: stateless timer-driven reconcile over a long-running watcher; why picklelab image can't host it; what we rejected: building into the agent/server images, a sleep-loop sidecar).
- [ ] **Step 3: Commit.** `git commit -m "docs(woodpecker): document the agent switch"`

---

### Task rollout

Phased, each phase has a gate. Phases 1 to 3 are on picklelab and need the user around for `op`/ssh; run deploy with `just deploy-woodpecker`, from a clean `main` that matches `origin/main`, so the PR merges first.

- [ ] **Phase 0, merge with the timer off.** Open the PR from `woodpecker/agent-switch`, merge, `just deploy-woodpecker` with `SWITCH_TIMER_ENABLED=0`. Gate: the stack is healthy (`just woodpecker-status`, health endpoint passes), and `docker compose ... config --services` on the host still omits the switch. Existing CI runs still go to picklelab exactly as before.
- [ ] **Phase 0b, pre-enable gates (from the final review; do before enabling the timer).**
  - **Agent identity:** picklelab's agent keeps no agent config (`/etc/woodpecker` has no volume), so every container recreate may register a new agent record and leave a stale one, which makes the switch raise on duplicate names every tick. Check the live Agents list after a redeploy. If duplicates appear, persist the agent config with a volume and pin `WOODPECKER_HOSTNAME` on `woodpecker-agent`, delete stale records, and set `PICKLELAB_AGENT_NAME` to match. This changes the existing prod agent's compose, so do it deliberately, not as a side effect.
  - **1Password rate limits:** the timer runs `op run` every minute against a template with the four existing secrets plus the token (about 5 reads per tick, about 7k a day). Check `op service-account ratelimit` against the picklehome token. If it is tight, lengthen the interval or give the switch its own template that carries only the token. A tripped limit would break every `op run` on picklelab, not just this one.
- [ ] **Phase 1, dry run.** Create `/etc/opt/homelab/woodpecker-agent-switch.env` with `SWITCH_ARGS=--dry-run`, set `SWITCH_TIMER_ENABLED=1`, redeploy. Run it for at least a few laptop sleep/wake cycles (a day). Gate: `just woodpecker-switch-logs` shows `would PATCH` lines only at real transitions, no flapping (if there is any, raise `STALE_AFTER_SECONDS`), no non-zero exits.
- [ ] **Phase 2, live, supervised.** Remove the `--dry-run` env file. With the laptop agent up and idle: within one tick picklelab shows `no_schedule` true and the laptop filters empty (check in the UI, Settings, Agents). Then trigger a pipeline with no `host` label and confirm it runs on the laptop. Then stop the laptop agent (or sleep the laptop) and wait past `STALE_AFTER_SECONDS` plus one tick: picklelab schedulable again, laptop filters back to `!host=laptop`, a new unlabeled pipeline lands on picklelab. Gate: both directions observed once, and `--reset` verified to restore defaults when run by hand mid-"laptop preferred".
- [ ] **Phase 3, arch audit before leaving it on.** The VM is arm64, picklelab is amd64, and unlabeled pipelines can now land on either. List the repos with Woodpecker pipelines and check which build or pull architecture-specific images. For any that need amd64, add `labels: platform: linux/amd64` to the workflow (verify the label name against the agent's reported labels in the UI first). Gate: no pipeline that needs amd64 can reach the VM.
- [ ] **Phase 4, soak and close.** Leave it live for a week. Check the journal for `failed` unit states and for any CI run that failed with an arch-looking error. Then: `task 4855467a-b27c-4cd2-9368-8f5f0e678c1b done`, and note anything learned in the task or the ADR.
- [ ] **Rollback (any phase):** `sudo systemctl stop woodpecker-agent-switch.timer`, then `just woodpecker-switch-reset` to restore picklelab `no_schedule=false` and the laptop filter. Permanent removal: set `SWITCH_TIMER_ENABLED=0`, `sudo systemctl disable woodpecker-agent-switch.timer`, redeploy.

---

## Self-review

- **Coverage:** design (stateless reconcile, timer, same compose, fail open, PATCH order), API verification gate, token, rollout with dry run and rollback, arch drift, docs/ADR. The open "where the watcher runs" question is answered by the compose placement.
- **Local testability:** logic is a pure function (`decide`, `now` injected); the HTTP layer is tested over real sockets against `FakeWoodpecker`; the image is smoke-tested against the same fake via `host.docker.internal`; units are linted in a debian container. What cannot run locally, and where it is covered instead: the real API shape (fixture captured in `verify-api-fields`, checked by `test_fixture_roundtrip`), `network_mode: service:ts-woodpecker` and `op run` (rollout phase 0), real laptop sleep behaviour (rollout phase 1 dry run).
- **Interfaces:** `Config`, `Patch`, `decide` defined in `decide-logic` and used unchanged in `api-client-and-cli`; compose service name `woodpecker-agent-switch` is the same in compose, units, Justfile and rollback.
- **Known unknowns carried honestly:** field names and PATCH body come from upstream `main` and are checked first in `verify-api-fields`; the `platform` label name in `rollout` phase 3 is also to be verified in the UI before use.
