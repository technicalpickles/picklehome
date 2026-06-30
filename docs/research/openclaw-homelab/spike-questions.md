# OpenClaw spike — what to learn from the running instance

A spike is already running on the laptop. This is the list of things to **extract, measure, and decide** from it before writing the `docs/plans/` design doc and the on-host deploy. The point of the spike is to replace the SEO-guide guesses (which disagree on port/user/paths) with observed facts, and to validate the two things that are genuinely new vs. the existing agents: the **Ollama cloud wiring** and the **chat-channel front door**.

Each item: *what to learn → why it matters → how to observe it.*

---

## 1. Image facts (mostly resolved by the official doc — just confirm against the running image)

The official docker doc settled the disagreements: port **`18789`**, user **`node`/uid 1000**/`/home/node`, image **`ghcr.io/openclaw/openclaw`** on **`node:24-bookworm-slim`**, three mount dirs (config `/home/node/.openclaw`, workspace `…/workspace`, auth secrets `/home/node/.config/openclaw`). Remaining is just a sanity-check that the *running spike* matches:

- **Exact image ref + digest** being run → pin it in compose, not `latest`. → `docker inspect --format '{{.Config.Image}}' <ctr>`.
- **Confirm port + user + mount paths** match the doc → no surprises before writing compose. → `docker port <ctr>`, `docker exec <ctr> id`, `docker inspect --format '{{json .Mounts}}' <ctr>`.
- **Image size** → disk budget sanity (~20 GB claim). → `docker images`.

## 2. State & persistence

The state dir reportedly holds agent config, **memory**, **credentials**, a **SQLite memory index**, and **channel session tokens**. We need to know exactly what's in there.

- **What files appear in the state/config dir after setup + a few messages** → tells us what restic must back up and what regenerates. → `ls -laR` the mounted dir on the laptop after using it a bit.
- **Where channel tokens + the LLM key actually persist** (state dir? separate secret dir? env only?) → confirms secrets stay in `.env`/1Password and aren't written somewhere unexpected. → grep the state dir for the token/key values.
- **Does it survive a container recreate** with the state dir persisted (down + up, not just restart)? → this is the real test that our `/srv/data` mount is sufficient. → `docker compose down && up`, confirm channels + memory still work without re-auth.
- **Disk growth rate** of memory/SQLite over the spike's lifetime → does "growing memory files" mean MB or GB? Informs the data-dir budget. → `du -sh` the dir now vs. later.

## 3. Config model (can it be repo-driven?)

`homelab_07` strongly prefers source-controlled, declarative config over interactive state. Find out how much of OpenClaw is declarable.

- **Config file format + location** (the `openclaw.json` / config dir) and which settings live there vs. only in the UI → decides how much we can commit vs. configure interactively post-deploy (like `obsidian-sync`'s interactive auth). → inspect the config file the spike wrote.
- **Env-var overrides:** which settings can be set by env (so they flow through `.env.vars`) vs. file-only → shapes `.env.vars`. → check docs + try overriding one.
- **Is first-run setup interactive** (web wizard) or can it boot fully configured from a committed file? → determines whether deploy is one-shot or needs a manual setup step documented in the README.

## 4. Ollama cloud provider wiring (the chosen backend)

This is new and load-bearing — validate it actually works end to end before committing.

- **How to point OpenClaw at Ollama cloud:** base URL (`https://ollama.com/v1`), model name, and which API-key env var → the exact `.env`/config we'll ship. → get it working in the spike and record the config.
- **Does the chosen model do tool/function calling well?** The agent loop *depends* on tool calls — a model that's weak at them makes OpenClaw useless. This is the single most important thing to validate. → give the bot a multi-step task and watch whether it correctly invokes tools.
- **Latency per turn** against Ollama cloud → is the chat responsive enough to be worth running? → eyeball round-trip on a few messages.
- **Request volume / rate-limit feel** for an always-on agent → informs which Ollama subscription tier. → note any throttling during normal use.

## 5. Channel / front-door auth (the real security boundary)

This replaces the SSH key that gates the existing agents — get it exactly right.

- **How to allowlist** specific chat IDs / users, and the exact mechanism (config field? per-channel setting?) → this is *the* lockdown control. → set it, then confirm.
- **What happens to a message from a non-allowlisted sender** (ignored? error? silently processed?) → confirms the door is actually closed. → message the bot from a second account / have someone else try.
- **Telegram long-poll vs webhook** for the chosen channel → decides whether we need *zero* ingress (Tailscale Services for the UI only) or Funnel-style public ingress. → check how the spike's channel connects (outbound poll = no ingress).
- **Does the bot require any inbound ports at all** in long-poll mode? → confirms the no-public-exposure path. → observe with `docker port` / netstat.

## 6. Tool surface / capabilities

Decide the minimum viable tool set; we widen later (trust-grows-with-capability).

- **What tools are enabled by default** (shell, filesystem, browser, etc.) → the day-one blast radius. → inspect config / ask the bot what it can do.
- **Can the browser tool be turned off** (and does that drop the RAM need from ~8 GB to ~4 GB)? → directly affects the 16 GB box budget. → disable it, watch RAM.
- **Can shell/filesystem be scoped** to a workspace dir vs. the whole container? → shapes how much we trust it on the shared box. → test.
- **Can it call external commands we'd want** — e.g. the existing `just` CLIs (climate/locks/etc.)? Is there a custom-tool / function mechanism? → this is the actual *use case* question: what do we want it to *do*. → try wiring one read-only command.
- **Is `PATH` env-overridable, and does a binary dropped into a mounted dir get picked up live** (no restart)? → validates the tier-1 bind-mounted-bin pattern for spiking CLIs like `gogcli`. → mount a dir, prepend to PATH, drop a binary in *while running*, ask the bot to run it.
- **Does an MCP server (stdio or HTTP/SSE sidecar) attach without rebuilding/restarting the OpenClaw container**, and is its config declarative/committable? → validates the tier-2 decoupled-tools path. → wire one MCP server per the `bundle-mcp` docs and confirm hot-add behavior.
- **Are config and runtime state separable, or intermingled in one `~/.openclaw` dir?** → decides whether we can commit a clean config file or must treat a file inside the state mount as source-of-truth. → inspect the dir layout after setup (this is the §3 catch).

## 7. Resource footprint (does it fit the 16 GB NUC?)

- **Idle RAM/CPU** and **under-load RAM/CPU** (during an agentic task), **with and without the browser** → the explicit budget against ~9 existing services. → `docker stats` at idle and during a task.
- **Startup time + CPU on boot** → matters on the weak J3455. → time a cold `up`.

## 8. Networking / binding

- **Force loopback bind.** Official: gateway defaults to **`lan` mode** (binds beyond loopback). For Tailscale Services it must be `127.0.0.1:18789` → find the bind-mode setting and/or pin the compose port mapping. → set it, confirm with `docker port` + `ss`.
- **Any second port / outbound connections we didn't expect** → egress awareness (it browses + calls an LLM; know where it talks). → watch connections during use.

## 9. Operations (deploy/monitor/update)

- **Logging:** does it log to stdout cleanly (journald/`docker logs` friendly)? Any secrets leaked into logs? → confirms standard logging works and nothing sensitive is printed. → `docker logs`.
- **Health endpoints confirmed** (`/healthz`, `/readyz`) — just wire them into the goss smoke check; nothing to discover. → curl both.
- **Update path:** how do you move image versions, and does state survive it? → the `just deploy-openclaw` upgrade story. → pull a newer tag, recreate, confirm state intact.
- **Crash/restart behavior** → confirms `restart: unless-stopped` + the oneshot systemd unit is the right shape. → kill it, watch recovery.

## 10. Web UI / API auth — resolved

Official: the setup script writes a **gateway token** to `.env` and the control UI is gated by it, so the UI is not a second open surface. Just confirm the token is enforced (hitting the UI without it is rejected) and route that token through our `.env.vars`. → curl the UI with and without the token.

---

## What this feeds

- The unknowns in [`findings.md`](findings.md) (§"How it runs" table marked *Medium* confidence) get pinned to observed values.
- Items 4–6 answer the open questions: Ollama model/tier, the channel front door, and the **tool surface = the actual use case**.
- Items 1–3, 7–10 are the raw material for the `docs/plans/YYYY-MM-DD-openclaw-deploy.md` design doc and the service's compose/`.env.vars`/`deploy.sh`.
