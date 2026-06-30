# OpenClaw on picklelab — initial deployment research

**Status:** initial research only. No decision made, nothing deployed. Captures what OpenClaw is, how a deploy would map onto picklehome conventions, the hard constraints, and the open questions to resolve before writing a plan.

**Date:** 2026-06-30

---

## What OpenClaw is

OpenClaw is a self-hosted **AI gateway**: it bridges messaging apps (WhatsApp, Telegram, Discord) to an AI agent that can *act* — run shell commands, manage files, browse the web, and send alerts. You message a bot; it runs an agentic loop against an LLM and does things on the box it's running on.

The right framing for *this* homelab: **OpenClaw is a deliberate agent surface, a sibling to `brineworks-agent` and `second-brain-agent`** — not a hostile workload to cage. The difference is that OpenClaw provides the agent loop and a chat front-end *out of the box*, where the existing two are Claude Code sessions you SSH into over Tailscale. So the model is the same as those: trusted-but-shaped, deployed on purpose. The one boundary that genuinely differs is the **front door** (chat channel vs. SSH key) — see [Where it fits the agent model](#where-it-fits-the-agent-model).

## How it runs (Docker)

Public guides converge on a simple shape, though they disagree on specifics (OpenClaw is young and the guides are partly SEO content — treat exact numbers as *verify before relying*):

| Aspect | What the sources say | Confidence |
|---|---|---|
| **Image** | `ghcr.io/openclaw/openclaw` (mirror `openclaw/openclaw` on Docker Hub); tags `latest`/`main`/`<version>`. Base **`node:24-bookworm-slim` + tini** init → Debian/glibc, `apt-get`, so glibc/Go binaries (e.g. `gogcli`) just run; no musl gotchas. | **High (official)** |
| **Port** | **`18789`** — one HTTP port for web UI + REST API + webhooks. Confirmed from the official docker doc; the `3000`/`47981` figures in third-party guides are wrong/stale. | **High (official)** |
| **User** | non-root **`node`, uid 1000**, home `/home/node`. (The `/root/.bun` PATH seen earlier was a stale Alpine-era artifact.) uid 1000 is the homelab's common non-sharing default and OpenClaw's data dir isn't shared, so we can keep 1000. | **High (official)** |
| **Mounts (3 dirs)** | `OPENCLAW_CONFIG_DIR`=`/home/node/.openclaw` (agent config, **memory**, SQLite index, **channel tokens**); `OPENCLAW_WORKSPACE_DIR`=`/home/node/.openclaw/workspace` (agent's files); **separate** `OPENCLAW_AUTH_PROFILE_SECRET_DIR`=`/home/node/.config/openclaw` (auth secrets). All survive container replacement. | **High (official)** |
| **Extension model** | **MCP-native** ([docs](https://docs.openclaw.ai/cli/mcp)) — MCP servers register as plugin-owned tools under `bundle-mcp`. Plus declarative tool/provider config ([config-tools](https://docs.openclaw.ai/gateway/config-tools)), an `OPENCLAW_EXTRA_MOUNTS` hook for extra bind mounts, and `OPENCLAW_IMAGE_APT_PACKAGES` / `OPENCLAW_IMAGE_PIP_PACKAGES` build args for baked-in packages. | **High (official)** |
| **LLM backends** | Anthropic, OpenAI, and Ollama (OpenClaw ships a [native Ollama provider](https://docs.openclaw.ai/providers/ollama)). The docker doc's Ollama example is for a **local** server (`host.docker.internal:11434`); for the **cloud subscription** we point the base URL at `https://ollama.com/v1` instead. | High |
| **Auth secret** | An LLM API key via env; secrets in `.env`, referenced as `${VAR}`, never hardcoded | High |
| **Resources** | Official doc states only **~2 GB RAM for image *builds*** (1 GB risks OOM/exit 137). Runtime footprint isn't given officially; community figures are ~4 GB, **~8 GB with the browser tool**. Disk ~20 GB for image + state + growing memory. | Mixed (build = official, runtime = community → spike §7) |

Other official facts from the docker doc worth recording:
- **Health endpoints:** `/healthz` (liveness), `/readyz` (readiness) — drop-in for a goss smoke check.
- **UI auth:** the setup script writes a **gateway token** to `.env`; the control UI at `127.0.0.1:18789/` is gated by it (so the UI is *not* a second open surface — there's a token).
- **Default bind is `lan` mode** for host-browser access — it binds beyond loopback by default, so for the Tailscale Services pattern we must **force `127.0.0.1`** (compose port bind and/or an OpenClaw bind-mode setting).
- **Docker socket override exists** (`OPENCLAW_DOCKER_SOCKET`) — a capability we deliberately **do not** grant (keeps it off the ops path; see the agent-model section).
- **Onboarding is interactive by default**, skippable via `OPENCLAW_SKIP_ONBOARDING` — bears on how declarative the deploy can be.
- **Env precedence footgun:** provider env vars set in the shell (documented for the `ANTHROPIC_*` family; same applies to Ollama/OpenAI vars) **override** config files. Since we inject via `.env`, config-file values won't win over an env var of the same name.

## Fit with picklelab hardware

NUC is a Celeron **J3455 (4 weak cores, no GPU), 16 GB RAM**.

- **RAM:** 16 GB total, already running ~9 services. A 4 GB agent fits; an 8 GB browser-enabled agent is tight alongside everything else. Budget this explicitly.
- **LLM runs off-box via an Ollama cloud subscription** (the chosen backend). This sidesteps the J3455 entirely — no local inference, which would be unusably slow on a GPU-less Celeron. Mechanically it's an [Ollama API key](https://ollama.com/settings/keys) pointed at the OpenAI-compatible endpoint `https://ollama.com/v1`. Per the official [`config-tools`](https://docs.openclaw.ai/gateway/config-tools) page, this is a `models.providers` entry (secret as `${ENV}` ref, committable):

  ```json5
  { models: { providers: { "ollama-cloud": {
      baseUrl: "https://ollama.com/v1",
      apiKey: "${OLLAMA_API_KEY}",
      api: "openai-completions",
      models: [{ id: "<pick-from-catalog>", contextWindow: 128000, maxTokens: 32000 }]
  } } } }
  ```

  Setting `baseUrl` is, in OpenClaw's words, "the narrow network trust decision for model HTTP requests" — it allowlists that exact origin through the guarded fetch path. The key lives in 1Password → `.env` like every other secret. **Caveat (see security section):** the smaller/cheaper the Ollama model, the more susceptible to tool-misuse/prompt-injection — weigh model tier against how much tool access the agent gets.
- **Disk:** 20 GB on the local SSD is fine; `/srv/data` is the home for state.

## How it maps onto homelab conventions

This part is the *good* news — the mechanics fit the existing pattern almost exactly:

- **Service layout:** `homelab/services/openclaw/` with `compose.yaml`, `compose.picklelab.yaml`, `deploy.sh`, `.env.vars`, `openclaw.service` (long-lived `oneshot`+`RemainAfterExit`). Data at `/srv/data/openclaw/`, compose at `/srv/containers/openclaw/`.
- **Secrets:** the Ollama API key (and any channel tokens) into 1Password → `.env.template` → filtered into the service `.env` via `scripts/service-env`. Channel tokens (Telegram bot token, etc.) are per-service secrets in the `picklehome` vault.
- **uid/bind-mount:** the container writes `/srv/data/openclaw/` so it **must not run as root**. Pick a uid (next free, e.g. `3000`), set `user: "uid:gid"` in compose, `chown -R` in `deploy.sh` after `mkdir -p`. Mind which internal home the image uses (`/home/node` vs `/root`) when mapping the state dir.
- **Access / ingress — two paths depending on channel transport:**
  - **Outbound-only channels (Telegram long-polling):** no public ingress needed. The bot polls out; you reach the **web UI/REST over Tailscale Services** (`https://openclaw.<tailnet>.ts.net`, loopback bind `127.0.0.1:18789`). This is the clean, no-public-exposure path and matches the default homelab pattern.
  - **Webhook-driven channels (WhatsApp Cloud API, some Discord setups):** need inbound HTTPS, i.e. **Tailscale Funnel** like `woodpecker` does — the homelab's only deliberate public-ingress pattern. More surface, more care.

## Mounts, version control, and adding tools

### What's mounted vs. baked into the image

The image is the *runtime* (Bun, the OpenClaw app, base Debian tools). Everything that's instance-specific lives in **bind mounts**, so it survives `docker compose down/up` and image upgrades:

| Mount | Contents | Lives in | In git? |
|---|---|---|---|
| **Config dir** (`/home/node/.openclaw`) | agent config **+** memory, SQLite index, channel session tokens | `/srv/data/openclaw/config/` | **No** — config intermingled with runtime state + tokens; restic-backed |
| **Workspace dir** (`/home/node/.openclaw/workspace`) | files the agent reads/writes | `/srv/data/openclaw/workspace/` | **No** — churning agent data |
| **Auth-secret dir** (`/home/node/.config/openclaw`) | auth/profile secrets (separate dir, official) | `/srv/data/openclaw/auth/` | **No** — secrets |
| **Tools/bin dir** (our addition, via `OPENCLAW_EXTRA_MOUNTS`) | extra CLIs we want the agent to call (see below) | `/srv/data/openclaw/bin/` on PATH | Manifest yes, binaries no |

### What can be version-controlled

The split mirrors every other homelab service: **declarative config → repo, runtime state → `/srv/data`, secrets → 1Password.** Specifically committable:

- The **declarative tool/provider/channel config** (the [`config-tools`](https://docs.openclaw.ai/gateway/config-tools) layer + MCP server definitions), with secrets written as `${ENV}` refs, never literals. Ship it as a committed config file the container reads, or template it like `.env`.
- compose files, `.env.vars`, `deploy.sh` — same as every service.

The catch (partly resolved by the official doc): **auth secrets are already in their own dir** (`OPENCLAW_AUTH_PROFILE_SECRET_DIR`=`/home/node/.config/openclaw`), separate from config — good. But declarative config still lives in `/home/node/.openclaw` **alongside** memory + the SQLite index + channel tokens. So we can't cleanly mount "config in git, state on disk" as two dirs. Working plan: mount the whole config dir to `/srv/data` (restic-backed) and keep a **committed copy of just the config file** as source-of-truth, re-applied on deploy. Spike §3 confirms the exact config filename and whether it's fully env-overridable (which would let us skip the committed-file dance).

### Adding tools without rebuilding/restarting (the `gogcli` question)

**Provenance note:** the three-tier framing below is **our synthesis** to answer "how do I add tools without rebuilds," *not* a workflow OpenClaw's docs prescribe; the ranking ("fastest-iteration first") is editorial judgment. The underlying mechanisms are now backed by a **direct read of the official docker doc** (fetched via the raw GitHub markdown after the rendered docs site 403'd), tagged inline. The goal is to **never rebuild the OpenClaw image just to try a tool**:

1. **Extra bind-mounted bin dir on PATH — best for spiking arbitrary CLIs like `gogcli`.** Mount a host dir via the official `OPENCLAW_EXTRA_MOUNTS` hook, prepend it to `PATH`. Adding/updating a tool = copy the binary in; the agent's **next shell invocation re-reads PATH**, so no rebuild and no restart. Because the base is **`node:24-bookworm-slim` (Debian/glibc)**, static/Go binaries like `gogcli` run as-is. Keep a committed `tools/` manifest or fetch-script in the repo (binaries themselves stay out of git, fetched on deploy).
   - *Provenance:* the **mount mechanism is now official** (`OPENCLAW_EXTRA_MOUNTS` in the docker doc), and the Debian/glibc base is official (`node:24-bookworm-slim`). The remaining unverified bit is narrow: that PATH is overridable and a dropped binary is picked up **live without restart** — *our reasoning* about PATH + shell-spawn → spike §6 confirms.
2. **MCP server — best for structured/stateful ecosystem tools.** OpenClaw is MCP-native, so run a tool as an MCP server (stdio, or an HTTP/SSE **sidecar container**). Iterating that tool restarts only the sidecar, **never the OpenClaw container**, and the agent gets it as a first-class schema'd tool. MCP server list is declarative → committed. This is the most decoupled option and inherits the 200+ existing community MCP servers.
   - *Provenance:* now a **direct read** of [cli/mcp](https://docs.openclaw.ai/cli/mcp) + [config-tools](https://docs.openclaw.ai/gateway/config-tools). Confirmed: MCP servers live in the `mcp.servers` config block (stdio = `command`/`args`/`env`/`cwd`; remote = `url` + `transport: streamable-http|sse`, with OAuth/TLS/mTLS, `toolFilter.include/exclude`, `enabled:false`); exposed via `bundle-mcp` in the `coding`/`messaging` profiles. **Hot-add is real but partial:** `openclaw mcp add|configure|reload` adds/probes/reloads *in-process* runtimes, but the docs caveat that "gateway or agent processes in another process still need their own reload or restart path." So: restart the sidecar freely; registering a *new* server needs at least a gateway **reload** (not a full image rebuild). Better than my earlier "never touch OpenClaw" claim — adjust expectations to "reload, not rebuild."
3. **`OPENCLAW_IMAGE_APT_PACKAGES` / `OPENCLAW_IMAGE_PIP_PACKAGES` (image rebuild) — only for stable system deps.** Bakes apt/pip packages in at build time (persists across container deletes). Reserve for the rarely-changing base (`git`, runtime libs); *don't* use it for tools under active iteration — that's the rebuild loop you want to avoid.
   - *Provenance:* **official docker doc** (both vars listed; earlier `OPENCLAW_DOCKER_APT_PACKAGES` from a third-party guide was the wrong name).

**Recommendation (our judgment):** tier 1 for CLIs you're spiking (`gogcli`), tier 2 (MCP) for anything worth exposing as a structured tool, tier 3 only for stable system packages. This keeps the image stable, the tool-iteration loop instant, and the tool list version-controlled (manifest + MCP config in the repo).

Note the two senses of "tool": for the agent to *use* `gogcli` it only needs it on `PATH` with the shell tool enabled — the LLM shells out to it. Registering it as a first-class OpenClaw tool (schema, profiles) is the MCP/`config-tools` path. For a CLI you're experimenting with, PATH + shell is enough and simplest.

## Where it fits the agent model

OpenClaw is a **deliberate agent surface**, the same category as `brineworks-agent` and `second-brain-agent`. We do **not** treat it as a hostile workload to be caged — the heavy containment in the community guides (Gluetun VPN egress, kill-switch, zero host mounts, fully dropped caps) exists to *grant an untrusted thing some access*; OpenClaw's whole purpose is to *be* the agent with access, so caging it to zero reach defeats the point. Model it on the two existing agent containers: trusted-but-shaped, deployed on purpose.

What that means concretely:

1. **The front door is the real boundary.** `brineworks-agent`/`second-brain-agent` are gated by an SSH key over Tailscale (you, authenticated). OpenClaw's gate is *whoever can message the bot*. So the **chat-channel allowlist is the equivalent of the SSH key** — lock the bot to your own chat IDs, never leave a channel open. This is the one genuinely new thing vs. the existing agents, and it's the thing to get right.
2. **Give it the tools you want it to have, deliberately.** Like `second-brain-agent` mounting the vault read-write on purpose, decide OpenClaw's tool surface intentionally (shell? the existing `just` CLIs? a workspace dir?) rather than either caging it to nothing or handing it the whole host by default. The browser tool is the one to default *off* unless wanted — it's ~4 GB RAM and the biggest passive attack surface.
3. **Standard service hygiene, same as everything else** (this is `homelab_07`'s actual ask — auditable, recoverable, repo-driven, not "no agents"):
   - non-root uid + `chown` in `deploy.sh` (every service does this).
   - State (`/srv/data/openclaw`) into the nightly restic job — it holds memory + channel tokens.
   - Compose version-controlled; no docker socket, no sudo (it's an agent surface, not an ops agent on the `/opt/homelab` control path).

The remaining judgment call: OpenClaw shares the box with climate control, locks, and the obsidian vaults. That argues for a deliberate, *minimal* tool surface to start (notifications + a couple of read-only `just` checks) and widening later — same trust-grows-with-capability path `homelab_07` describes — rather than wiring it to everything on day one.

## Security & sandbox model (from the official `gateway/security` + `gateway/sandboxing` docs)

These pages were read directly via raw GitHub. The headline: **OpenClaw's own threat model matches the framing above** — "a personal assistant model: one trusted operator per gateway… not a hostile multi-tenant security boundary." Its guiding line is *"Access control before intelligence. Decide who can talk to your bot, where it acts, and what it touches — then trust the model within those guardrails."* That's the same trusted-but-shaped posture as the existing agents, now vendor-endorsed.

Concrete controls, mapped to our deploy:

- **Gateway auth is on by default** — token mode (recommended; a bearer token the setup script writes to `.env`), password, or trusted-proxy. → route the token through `.env.vars`.
- **Channel access policy** (`session`/DM gating) has four modes: **Pairing** (default — unknown senders get time-limited approval codes), **Allowlist** (explicit senders only), **Open** (requires explicit `"*"`), **Disabled**. → we use **Allowlist** with our own chat IDs. Default is already *not* open, which is reassuring. `session.dmScope: "per-channel-peer"` isolates senders if ever shared.
- **Tools default-deny, which tempers the "shell-runner out of the box" worry.** The secure baseline **denies `group:runtime`, `group:fs`, `group:automation`** and sets `exec: { security: "deny", ask: "always" }`. So a default agent can't run shell/fs until you opt in via `tools.elevated`. Profiles: `minimal`/`coding`/`messaging`/`full` (onboarding defaults to `coding`); fine-grained `tools.allow`/`tools.deny` where **deny wins**. → start `minimal`/curated, widen deliberately.
- **Sandbox vs. our "no docker socket" stance — a real tension to decide.** OpenClaw's *tool sandbox* (`sandbox.mode: non-main`/`all`) isolates tool execution in containers, but its Docker backend needs **`/var/run/docker.sock`** — exactly the privilege `homelab_07` says don't grant. Two clean resolutions: (a) **run the whole gateway containerized** (full-isolation model) and rely on **tool allow/deny + exec-deny** rather than the in-container Docker sandbox — no socket needed; or (b) grant a **scoped/rootless docker socket** like `woodpecker`'s `ci` user does. Default to (a) for the first deploy. Sandbox default network is `"none"` (no egress), and `workspaceAccess` is `none`/`ro`/`rw`.
- **Bind-mount safety for our tools/bin dir.** Sandbox bind validation **blocks** `/etc`, `/proc`, `/sys`, `/dev`, the docker socket, and `~/.ssh`/`~/.config`/`~/.aws` etc., with symlink-escape resolution. `/srv/data/openclaw/bin` is well clear of those; mount sensitive paths `:ro`.
- **Prompt injection is "not solved" by prompts — and model strength matters.** The docs warn *"smaller/cheaper models are generally more susceptible to tool misuse and instruction hijacking"* and to use the strongest tier for tool-enabled agents. **This is a direct tension with the cheap-Ollama-cloud plan:** a small Ollama model driving real tools is the riskiest combination. Mitigation: keep the tool surface tiny + `exec: ask: always` while on a small model, or use a stronger model for any tool-enabled profile. Flag for the design doc.
- **Built-in hardening audit:** `openclaw security audit [--fix]` — run it post-deploy as the smoke-test/validation step (fits `homelab_07`'s "verify after mutation"). Credentials live under `~/.openclaw/credentials/` (perms 700/600); "assume anything under `~/.openclaw/` may contain secrets" → the whole config dir is sensitive, restic-backed, never committed.
- **Bind mode:** the security doc says **loopback is the safe default and to "prefer Tailscale Serve over LAN binds"** (the docker quickstart's `lan` default is for convenience). → exactly our Tailscale Services pattern; force `127.0.0.1:18789`.

## Open questions to resolve before a plan

- **Why / use case?** What do you actually want it to *do* (ops assistant? notifications? home-automation glue calling the existing `just` CLIs?). The use case decides how much host access it needs — which decides whether it's safe here at all.
- **Which channel(s)?** Telegram (outbound-only, no public ingress) is the lowest-surface starting point. WhatsApp/Discord-webhook needs Funnel.
- **Which Ollama cloud model + plan tier?** Backend is decided (Ollama cloud subscription). Remaining: pick the model from Ollama's catalog and confirm the subscription tier covers an always-on agent's request volume.
- **Tool surface?** Default OpenClaw can run shell + browse + filesystem. Decide the minimum set; disable the browser unless needed (saves ~4 GB RAM and a big chunk of attack surface).
- **Exact image facts:** pin the real default port, the in-container home/user, and the canonical volume paths from the official image before writing compose — public guides disagree.

## Suggested next step

A short spike: pull the official image, confirm the real port / volume paths / default user, and stand it up **locally (not on picklelab)** wired to Telegram with a single allowlisted chat ID, the browser tool **off**, and the Ollama cloud subscription as the backend. That validates the mechanics, the channel-auth front door, and the Ollama provider wiring before committing to an on-host deploy and writing a `docs/plans/` design doc.

## Sources

- **Official docs, all read directly via raw GitHub markdown** (the rendered `docs.openclaw.ai` site 403'd automated fetches):
  - [`docs/install/docker.md`](https://raw.githubusercontent.com/openclaw/openclaw/main/docs/install/docker.md) → port/user/mounts/image/health/bind facts
  - [`docs/cli/mcp.md`](https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/mcp.md) → `mcp.servers` config, transports, hot-add commands
  - [`docs/gateway/config-tools.md`](https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/config-tools.md) → tool profiles, allow/deny, `models.providers` (the Ollama-cloud snippet)
  - [`docs/gateway/security/index.md`](https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/security/index.md) → trust model, channel policies, auth, default-deny tools, audit
  - [`docs/gateway/sandboxing.md`](https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/sandboxing.md) → sandbox modes, Docker backend + `docker.sock`, bind validation, `workspaceAccess`
- [Self-Host OpenClaw on Docker — Complete 2026 Guide (provision.ai)](https://provision.ai/openclaw-docker)
- [Running OpenClaw in Docker — Simon Willison's TILs](https://til.simonwillison.net/llms/openclaw-docker)
- [deepmehtait/openclaw-docker-secure (GitHub)](https://github.com/deepmehtait/openclaw-docker-secure) — Gluetun VPN egress, no-new-privileges, no public ports, LAN-only
- [OpenClaw on a Synology NAS, hardened for always-on homelab use — David Christiansen](https://davidchristiansen.com/blog/openclaw-docker-hardened-homelab/) — Squid egress allowlist, Docker secrets, read-only rootfs
- [Deploy OpenClaw with Docker & Docker Compose (2026) — openclaw-ai.net](https://openclaw-ai.net/en/guide/docker)
- [coollabsio/openclaw — automated OpenClaw docker images](https://github.com/coollabsio/openclaw)
- [Ollama provider · OpenClaw docs](https://docs.openclaw.ai/providers/ollama)
- [Cloud models · Ollama Blog](https://ollama.com/blog/cloud-models) and [OpenAI compatibility · Ollama](https://docs.ollama.com/api/openai-compatibility) — cloud subscription, API key at `ollama.com/settings/keys`, OpenAI-compatible endpoint `https://ollama.com/v1`
