# OpenClaw spike — what to learn from the running instance

A spike is already running on the laptop: [`pickleclaw`](https://github.com/technicalpickles/pickleclaw), OpenClaw in an OrbStack VM. This is the list of things to **extract, measure, and decide** from it before writing the `docs/plans/` design doc and the on-host deploy. The point of the spike is to replace the SEO-guide guesses (which disagree on port/user/paths) with observed facts, and to validate the two things that are genuinely new vs. the existing agents: the **Ollama cloud wiring** and the **chat-channel front door**.

**Update (2026-06-30):** the spike diverged from this checklist's assumptions in two ways: it's `npm install -g openclaw` (not Docker), and it's backed by **OpenRouter** (not Ollama cloud). So it answers the *application-level* mechanics below (config, secrets, channels, UI auth, tool plugins) directly, but the **docker-image (§1), Ollama-provider (§4), and NUC-hardware (§7)** items still need their own pass — either by pointing the spike at Ollama/Docker, or with a fresh one.

Each item: *what to learn → why it matters → how to observe it.*

---

## 1. Image facts (mostly resolved by the official doc — just confirm against the running image)

The official docker doc settled the disagreements: port **`18789`**, user **`node`/uid 1000**/`/home/node`, image **`ghcr.io/openclaw/openclaw`** on **`node:24-bookworm-slim`**, three mount dirs (config `/home/node/.openclaw`, workspace `…/workspace`, auth secrets `/home/node/.config/openclaw`). **Not covered by the `pickleclaw` spike** — that one is `npm install -g openclaw` in an OrbStack VM, no Docker at all, so none of the image/container facts transfer (port 18789 itself is consistent across both, for what that's worth). Remaining is just a sanity-check that the *running spike* matches:

- **Exact image ref + digest** being run → pin it in compose, not `latest`. → `docker inspect --format '{{.Config.Image}}' <ctr>`.
- **Confirm port + user + mount paths** match the doc → no surprises before writing compose. → `docker port <ctr>`, `docker exec <ctr> id`, `docker inspect --format '{{json .Mounts}}' <ctr>`.
- **Image size** → disk budget sanity (~20 GB claim). → `docker images`.

## 2. State & persistence

The state dir reportedly holds agent config, **memory**, **credentials**, a **SQLite memory index**, and **channel session tokens**. We need to know exactly what's in there.

**Partially answered by `pickleclaw`** (app-level layout, not the docker-recreate test): the config file (`~/.openclaw/openclaw.json`) holds model/channel config, and — once SecretRefs are wired — no longer holds plaintext secrets; the OpenRouter key lives in OpenClaw's own sqlite `auth_profile_store`, channel tokens and API keys live in `0600` files referenced by `file` SecretRefs. See [`findings.md`](findings.md#verified-against-the-pickleclaw-spike-non-docker). Still open:

- **Does it survive a container recreate** with the state dir persisted (down + up, not just restart)? → this is the real test that our `/srv/data` mount is sufficient. → `docker compose down && up`, confirm channels + memory still work without re-auth. (Not testable in pickleclaw — it's a long-lived VM, never destroyed/recreated.)
- **Disk growth rate** of memory/SQLite over the spike's lifetime → does "growing memory files" mean MB or GB? Informs the data-dir budget. → `du -sh` the dir now vs. later. (Not yet measured in either spike.)

## 3. Config model (can it be repo-driven?) — substantially answered by `pickleclaw`

`homelab_07` strongly prefers source-controlled, declarative config over interactive state. Find out how much of OpenClaw is declarable.

- **Config file format + location:** `openclaw.json` (json5) at `~/.openclaw/`. Edited via `openclaw config get|set|patch|validate` (validated writes) and **hot-reloads live** (confirmed for `agents.defaults.*` — no restart). ✅
- **SecretRefs make it fully committable, not just "mostly":** a `secrets.providers` system resolves `exec`/`file`-sourced values at runtime, so the config file itself never needs a plaintext secret — see [`findings.md`](findings.md#verified-against-the-pickleclaw-spike-non-docker) for the mechanism. This changes the §"What can be version-controlled" answer in `findings.md` from "mount the whole dir, keep a committed copy" to "commit the config with SecretRef placeholders, resolve secrets from `/srv/data` files at runtime." ✅
- **Is first-run setup interactive or file-driven?** Neither purely — `openclaw onboard` is interactive by default but fully scriptable via `--non-interactive --accept-risk` + flags (incl. `--gateway-bind loopback`), reading the API key from an env var. So the deploy shape is **scripted onboarding flags, then scripted `config set/patch` calls**, not "drop in a committed json file and start." ✅
- **Env-var overrides for settings beyond the initial API key** — not yet exercised in either spike (pickleclaw only used `OPENROUTER_API_KEY` at onboarding time; all subsequent config changes went through `openclaw config set/patch`, not env). The official docs' "provider env vars override config files" footgun (noted in `findings.md`) is still unverified hands-on. Still open: which settings, if any, are env-overridable post-onboarding, for `.env.vars` design.

## 4. Ollama cloud provider wiring (the chosen backend) — still open, not covered by `pickleclaw`

This is new and load-bearing — validate it actually works end to end before committing. **`pickleclaw` uses OpenRouter, not Ollama cloud**, so none of these are answered by it directly — but one cross-cutting gotcha transfers: any model used anywhere in the fallback chain (`model.primary`/`model.fallbacks`/`heartbeat.model`) must be registered in `agents.defaults.models` or it silently falls through to the provider's default/auto model (caught OpenRouter routing a misconfigured heartbeat to an expensive frontier model). Expect the same trap with an Ollama-cloud model — register it explicitly. The actual Ollama spike below is still needed.

- **How to point OpenClaw at Ollama cloud:** base URL (`https://ollama.com/v1`), model name, and which API-key env var → the exact `.env`/config we'll ship. → get it working in the spike and record the config.
- **Does the chosen model do tool/function calling well?** The agent loop *depends* on tool calls — a model that's weak at them makes OpenClaw useless. This is the single most important thing to validate. → give the bot a multi-step task and watch whether it correctly invokes tools.
- **Latency per turn** against Ollama cloud → is the chat responsive enough to be worth running? → eyeball round-trip on a few messages.
- **Request volume / rate-limit feel** for an always-on agent → informs which Ollama subscription tier. → note any throttling during normal use.

## 5. Channel / front-door auth (the real security boundary) — Pairing exercised by `pickleclaw`, Allowlist still open

This replaces the SSH key that gates the existing agents — get it exactly right. **Documented:** four DM policies — Pairing (default, time-limited approval codes), **Allowlist** (what we want), Open (`"*"`), Disabled. So the mechanism is known; the spike just exercises it.

`pickleclaw` wired Telegram on the **default Pairing policy** (not Allowlist) and confirmed: an unknown sender's first message auto-generates a pairing request instead of a chat reply; approve with `openclaw pairing approve telegram <code>` (codes expire 1h); the first approved sender is auto-set as command owner. Long-poll confirmed too — no inbound port, `channels status` shows `mode:polling`. So:

- **Telegram long-poll vs webhook** ✅ confirmed no-ingress (outbound poll only, no `docker port`/listening port needed for the channel itself).
- **Does the bot require any inbound ports at all** in long-poll mode? ✅ No — confirmed via the channel itself requiring no listener.
- **Set the Allowlist policy to our own chat IDs and confirm it sticks**, and **what happens to a message from a non-allowlisted sender with Allowlist actually configured** → still open on both spikes (only Pairing has been exercised hands-on). → configure `dmPolicy: "allowlist"`, message from a second account, confirm hard reject (vs. Pairing's softer "request a code" flow).

## 6. Tool surface / capabilities

Decide the minimum viable tool set; we widen later (trust-grows-with-capability). **Documented:** secure baseline already denies `group:runtime`/`group:fs`/`group:automation` + `exec: deny/ask:always`; profiles `minimal`/`coding`/`messaging`/`full` (onboarding → `coding`); `tools.allow`/`tools.deny` with deny-wins. So shaping the surface is a config exercise, not a discovery.

**New from `pickleclaw`, not previously known:** ClawHub is OpenClaw's own package registry (`openclaw plugins search/install`, `openclaw skills search/install`, separate from npm) — worth checking for a ready-made plugin before hand-rolling an MCP server for a given capability. Also: **installing a ClawHub plugin requires a gateway restart to load** (verified for `@openclaw/brave-plugin` and the built-in `google` plugin) — this is a different code path from MCP servers, so don't assume the "MCP hot-add" claim below extends to plugins in general.

- **Confirm the spike's actual profile + effective tool list** (onboarding may have set `coding`, which is broader than we want) → the day-one blast radius. → inspect config / ask the bot what it can do; set to `minimal` + curated.
- **Turn the browser tool off** and measure the RAM delta (claim: ~8 GB → ~4 GB). → `tools.deny: ["browser"]`, watch `docker stats`.
- **Decide the sandbox stance:** tool-sandbox needs `docker.sock` (vs. our no-socket rule) — confirm whether we run gateway-containerized + default-deny instead, and whether `exec`/`fs` work acceptably without the Docker sandbox. → test a curated tool set with `sandbox.mode: off` inside the already-containerized gateway.
- **Can it call external commands we'd want** — e.g. the existing `just` CLIs (climate/locks/etc.)? Is there a custom-tool / function mechanism? → this is the actual *use case* question: what do we want it to *do*. → try wiring one read-only command.
- **Is `PATH` env-overridable, and does a binary dropped into a mounted dir get picked up live** (no restart)? → validates the tier-1 bind-mounted-bin pattern for spiking CLIs like `gogcli`. → mount a dir, prepend to PATH, drop a binary in *while running*, ask the bot to run it.
- **Does an MCP server (stdio or HTTP/SSE sidecar) attach without rebuilding/restarting the OpenClaw container**, and is its config declarative/committable? → validates the tier-2 decoupled-tools path. → wire one MCP server per the `bundle-mcp` docs and confirm hot-add behavior.
- **Are config and runtime state separable, or intermingled in one `~/.openclaw` dir?** → decides whether we can commit a clean config file or must treat a file inside the state mount as source-of-truth. → inspect the dir layout after setup (this is the §3 catch).

## 7. Resource footprint (does it fit the 16 GB NUC?) — not covered by `pickleclaw`

`pickleclaw` runs on a Mac (OrbStack VM), not the J3455 NUC, and isn't measuring `docker stats` (no Docker involved) — none of this transfers. Still needs its own measurement on/near the real hardware:

- **Idle RAM/CPU** and **under-load RAM/CPU** (during an agentic task), **with and without the browser** → the explicit budget against ~9 existing services. → `docker stats` at idle and during a task.
- **Startup time + CPU on boot** → matters on the weak J3455. → time a cold `up`.

## 8. Networking / binding

- **Force loopback bind — mechanism confirmed by `pickleclaw`.** `--gateway-bind loopback` is an `openclaw onboard` flag; verified with `ss -ltnp` showing only `127.0.0.1:18789`/`[::1]:18789`, no LAN exposure. For the docker deploy this still needs the compose-side equivalent (port mapping pinned to `127.0.0.1`) since onboarding flags may not be how the official image's entrypoint is configured — confirm there's an equivalent `gateway.bind`/env knob for the container path. → set it, confirm with `docker port` + `ss`.
- **Any second port / outbound connections we didn't expect** → egress awareness (it browses + calls an LLM; know where it talks). → watch connections during use. (Not yet observed in either spike.)

## 9. Operations (deploy/monitor/update) — still open

`pickleclaw` runs under `systemd --user` (not `docker logs`/compose), so its update/crash-recovery behavior doesn't map cleanly onto the container deploy story. Still to confirm on the docker path:

- **Logging:** does it log to stdout cleanly (journald/`docker logs` friendly)? Any secrets leaked into logs? → confirms standard logging works and nothing sensitive is printed. → `docker logs`.
- **Health endpoints confirmed** (`/healthz`, `/readyz`) — just wire them into the goss smoke check; nothing to discover. → curl both.
- **Update path:** how do you move image versions, and does state survive it? → the `just deploy-openclaw` upgrade story. → pull a newer tag, recreate, confirm state intact.
- **Crash/restart behavior** → confirms `restart: unless-stopped` + the oneshot systemd unit is the right shape. → kill it, watch recovery.

## 10. Web UI / API auth — resolved (twice over)

Official: the setup script writes a **gateway token** to `.env` and the control UI is gated by it, so the UI is not a second open surface. `pickleclaw` confirms this end-to-end on the running app: `gateway.auth.mode: "token"`, token at `gateway.auth.token` in the config file, and the Control UI's connect form requires both the WebSocket URL and that token — no anonymous access observed. Just route the token through our `.env.vars` for the docker deploy. → curl the UI with and without the token.

---

## What this feeds

- The unknowns in [`findings.md`](findings.md) (§"How it runs" table marked *Medium* confidence) get pinned to observed values.
- Items 4–6 answer the open questions: Ollama model/tier, the channel front door, and the **tool surface = the actual use case**.
- Items 1–3, 7–10 are the raw material for the `docs/plans/YYYY-MM-DD-openclaw-deploy.md` design doc and the service's compose/`.env.vars`/`deploy.sh`.

**Status after the `pickleclaw` pass (2026-06-30):** §2 (partial), §3, §8 (partial), §10 — answered. §5 — Pairing flow answered, Allowlist itself still untested. §6 — two new facts (ClawHub, plugin-restart), the rest (profile/browser-RAM/sandbox/PATH/MCP) still open. §1, §4, §7, §9 — still need a docker+Ollama+NUC pass; `pickleclaw`'s stack doesn't cover them. Candidate next step: either point `pickleclaw` at Ollama cloud and re-run the §4 checks, or stand up a docker-based spike for §1/§7/§9.
