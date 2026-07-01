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
- **LLM runs off-box via an Ollama cloud subscription** (the chosen backend). This sidesteps the J3455 entirely — no local inference, which would be unusably slow on a GPU-less Celeron.

  **Correction (verified against the OpenClaw source, `docs/providers/ollama-cloud.md`, tag `v2026.6.10` — see [pickleclaw vendor clone](#verified-against-the-pickleclaw-spike-non-docker)):** the original plan of hand-rolling a custom `models.providers` entry pointed at the OpenAI-compatible `https://ollama.com/v1` endpoint is **wrong and would likely break tool calling**. `ollama-cloud` is a **first-class built-in provider id** — no custom provider config needed at all:

  - Onboard directly: `openclaw onboard --auth-choice ollama-cloud`, or just export `OLLAMA_API_KEY`.
  - Base URL is `https://ollama.com` (no `/v1`) — the provider speaks Ollama's **native `/api/chat`**, not the OpenAI-compatible route. The doc is explicit: *"Do not use the `/v1` OpenAI-compatible URL... This breaks tool calling and models may output raw tool JSON as plain text."* This is exactly the failure mode spike item §4 is most worried about ("does the model do tool calling well") — using the wrong endpoint shape would look like a bad model when it's actually a wrong URL.
  - Model refs look like `ollama-cloud/kimi-k2.6`; list the live hosted catalog with `openclaw models list --provider ollama-cloud`.
  - Still register the chosen model in `agents.defaults.models` and set it as `agents.defaults.model.primary` (or a fallback/heartbeat) — the official `config-tools.md` examples always pair a custom/hosted provider with this registration, and pickleclaw independently hit the failure mode when it's skipped (see below).

  Corrected config sketch:
  ```json5
  {
    agents: {
      defaults: {
        model: { primary: "ollama-cloud/<pick-from-catalog>" },
        models: { "ollama-cloud/<pick-from-catalog>": {} },
      },
    },
  }
  ```
  `OLLAMA_API_KEY` comes from `.env` as a plain env var (the provider reads it directly per the doc's setup step) — no `${VAR}` templating needed in the config for this one. **Caveat (see security section):** the smaller/cheaper the Ollama model, the more susceptible to tool-misuse/prompt-injection — weigh model tier against how much tool access the agent gets.
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

The catch (partly resolved by the official doc): **auth secrets are already in their own dir** (`OPENCLAW_AUTH_PROFILE_SECRET_DIR`=`/home/node/.config/openclaw`), separate from config — good. But declarative config still lives in `/home/node/.openclaw` **alongside** memory + the SQLite index + channel tokens. So we can't cleanly mount "config in git, state on disk" as two dirs.

**Refined plan, backed by a real mechanism (`$include`, verified in source — see below):** don't try to mount the whole root config file read-only; the root `openclaw.json` must stay **writable** (onboarding creates it, and it holds the gateway token / mainKey / session store paths that can't be static). Instead, bind-mount small **committed include files** read-only *inside* the config dir (`$include` targets must resolve inside the config directory), and have the writable root file `$include` specific top-level sections (`tools`, `mcp`, etc.) from them. Non-secret structure lives in git; the live root file is a thin, mostly-onboarding-generated shell that points at it. One caveat: OpenClaw's own `config set`/`config patch` **writes through** to a single-file-include target for that section — so a read-only-mounted include file blocks CLI writes to that section (fine for us: changes flow through git + redeploy, not live `config set`). Not yet exercised hands-on by any spike — flagged in `spike-questions.md` §3 as the next thing to validate.

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
- **Sandbox vs. our "no docker socket" stance — a real tension, now with a third option.** OpenClaw's *tool sandbox* (`sandbox.mode: non-main`/`all`) isolates tool execution, but its default **Docker backend needs `/var/run/docker.sock`** — exactly the privilege `homelab_07` says don't grant. Three options, not two: (a) **no sandbox**, rely on tool allow/deny + exec-deny (day-one default, no socket at all); (b) grant a **scoped/rootless docker socket** like `woodpecker`'s `ci` user does; (c) **the `ssh` sandbox backend — no socket of any kind**, real isolation via a dedicated low-privilege SSH target instead of a Docker daemon. Full comparison, including why Docker-in-Docker doesn't earn its complexity here, in [Sandboxing deep dive](#sandboxing-deep-dive) below.
- **Bind-mount safety for our tools/bin dir.** Sandbox bind validation **blocks** `/etc`, `/proc`, `/sys`, `/dev`, the docker socket, and `~/.ssh`/`~/.config`/`~/.aws` etc., with symlink-escape resolution. `/srv/data/openclaw/bin` is well clear of those; mount sensitive paths `:ro`.
- **Prompt injection is "not solved" by prompts — and model strength matters.** The docs warn *"smaller/cheaper models are generally more susceptible to tool misuse and instruction hijacking"* and to use the strongest tier for tool-enabled agents. **This is a direct tension with the cheap-Ollama-cloud plan:** a small Ollama model driving real tools is the riskiest combination. Mitigation: keep the tool surface tiny + `exec: ask: always` while on a small model, or use a stronger model for any tool-enabled profile. Flag for the design doc.
- **Built-in hardening audit:** `openclaw security audit [--fix]` — run it post-deploy as the smoke-test/validation step (fits `homelab_07`'s "verify after mutation"). Credentials live under `~/.openclaw/credentials/` (perms 700/600); "assume anything under `~/.openclaw/` may contain secrets" → the whole config dir is sensitive, restic-backed, never committed.
- **Bind mode:** the security doc says **loopback is the safe default and to "prefer Tailscale Serve over LAN binds"** (the docker quickstart's `lan` default is for convenience). → exactly our Tailscale Services pattern; force `127.0.0.1:18789`.

## Verified against the pickleclaw spike (non-docker)

This is the same "spike already running on the laptop" that [`spike-questions.md`](spike-questions.md) was written to interrogate — [`pickleclaw`](https://github.com/technicalpickles/pickleclaw) (sibling repo, not in this tree), running since 2026-06-25. It diverged from that checklist's assumptions in two ways: OpenClaw installed via `npm install -g` (not Docker) in an OrbStack Ubuntu VM, backed by **OpenRouter** (not Ollama cloud), with Telegram wired up. So it does **not** validate the docker-image, Ollama-provider, or NUC-hardware items (spike-questions §1, §4, §7) — those still need their own pass — but it's hands-on confirmation of the **application-level mechanics** (config format, secrets, channel auth, tool plugins, UI auth) that transfer regardless of how/where OpenClaw runs.

- **Config file + editing:** `~/.openclaw/openclaw.json` (json5). Safe edits via `openclaw config get|set|patch|validate` (validated writes), or hand-edit + `openclaw config validate`. **Hot-reloads confirmed** for `agents.defaults.*` (model/heartbeat changes take effect with no gateway restart).
- **First-run setup, precisely:** `openclaw onboard` is interactive by default but fully scriptable non-interactively (`--non-interactive --accept-risk --auth-choice openrouter-api-key --gateway-bind loopback --install-daemon --skip-channels`), reading the API key from an env var so it never hits argv/shell history. So the deploy story for day one is **"scripted onboarding flags + scripted `config set/patch` calls afterward,"** not literally "drop in a committed json file and start" — onboarding writes the file, our automation patches it from there.
- **SecretRefs solve the "config intermingled with state" problem more cleanly than the mount-split plan above.** OpenClaw has a `secrets.providers` system: any config value can be `{ source: "exec"|"file", ... }` instead of a literal, resolved at runtime. That means the *declarative config itself* can be fully committable with **zero plaintext secrets**, not just "auth secrets live in a separate mount" — no secret material needs to touch the json file at all. Verified both source types:
  - `exec` — runs a command (must be owned by the running user, not world/other-readable) that prints a secret via a small stdin/stdout JSON protocol; in pickleclaw's case it re-reads the OpenRouter key already stored in OpenClaw's own sqlite auth-profile store, so zero duplication.
  - `file` — reads a secret from a `0600` file path, piped straight from 1Password on the host, never passing through chat or git.
  - This directly answers the open catch in [What can be version-controlled](#what-can-be-version-controlled): write the committed config with SecretRef placeholders, keep actual secret values as `file`-ref `0600` files under `/srv/data` (restic-backed, never committed) — the same "secret in 1Password, resolved at runtime" shape as the rest of the homelab, just OpenClaw's own mechanism doing the resolving instead of `.env`.
  - `openclaw secrets audit` (`--allow-exec` to probe exec refs) reports `unresolved=0` when refs resolve, and separately flags any literal secrets still present as `PLAINTEXT_FOUND` — a ready-made post-deploy check alongside `openclaw security audit`.
- **Model registration trap (will recur with Ollama cloud):** any model referenced anywhere in the fallback chain (`model.primary`, `model.fallbacks`, `heartbeat.model`) must also be a key in `agents.defaults.models`, or it silently resolves to the provider's default/auto model instead. On OpenRouter this meant a misconfigured heartbeat quietly routed to `openrouter/auto` and paid frontier-model rates per heartbeat tick. The same requirement almost certainly applies to an Ollama-cloud model used as fallback/heartbeat — register every model explicitly, don't assume "set primary" is enough.
- **Channel front door, in practice:** Telegram long-polling confirmed — no inbound port, the bot polls outward, matching the "no public ingress" assumption. The policy actually exercised was `dmPolicy: "pairing"` (the *default*, not Allowlist): an unknown sender's first message auto-generates a pairing request instead of a reply; the operator approves with `openclaw pairing approve telegram <code>` (codes expire after 1h), and the first approved sender is auto-set as command owner. This is a legitimate alternative to Allowlist for a single-operator deploy — arguably stronger, since it requires an explicit per-sender approval step rather than a pre-populated ID list. **Still open on both spikes:** the hard-Allowlist rejection behavior (message from a sender not on an actually-configured allowlist) hasn't been exercised.
- **Tool plugins need a restart, MCP servers may not:** installing a ClawHub plugin (e.g. `@openclaw/brave-plugin`, the built-in `google` plugin) **requires a gateway restart to load**. This refines the "hot-add is real but partial" MCP claim above — that claim is specifically about *MCP servers* via `openclaw mcp add/configure/reload`, not *plugins* in general. Don't assume plugin installs are restart-free.
- **ClawHub** — a previously-undocumented piece worth knowing about when scoping the tool surface (the open question below): OpenClaw's own package registry (`openclaw plugins search/install`, `openclaw skills search/install`), separate from npm. Plugins add tools/providers/channels (official vs. community-tagged, vet community ones before installing); skills are instruction packs. There may be a ready-made plugin instead of hand-rolling an MCP server for a given capability.
- **Loopback bind, the actual mechanism:** `--gateway-bind loopback` at onboarding time — confirmed via `ss -ltnp` showing only `127.0.0.1:18789` / `[::1]:18789`, no LAN exposure. It's an onboarding flag (and presumably a `gateway.bind` config key for changing post-hoc), not something to discover by trial and error.
- **UI/API auth, end-to-end:** `gateway.auth.mode: "token"`, token stored at `gateway.auth.token` in the config file, and the Control UI's connect form genuinely requires both the WebSocket URL *and* that token — no anonymous access observed. Matches the official doc's claim.

## Verified against OpenClaw source (`pickleclaw`'s vendor clone, tag `v2026.6.10`)

`pickleclaw` keeps a gitignored clone of the OpenClaw repo at the exact tag matching its installed CLI (`vendor/openclaw`, per its `CLAUDE.md`). That clone answers several questions neither the pickleclaw runtime spike (different provider) nor the raw-GitHub docs fetch (main branch, docs-only) could pin down precisely — this is a straight source read, not docs summary or inference:

- **The plan's `OPENCLAW_BIND: loopback` env var is wrong on two counts.** The real var is `OPENCLAW_GATEWAY_BIND`, and for the **docker** deploy the value should be `lan`, not `loopback`. Reason (from `docs/install/docker.md`): Docker's default bridge networking means traffic from a published port (`-p 18789:18789`) arrives on the container's `eth0`, not its loopback interface — a `loopback`-bound gateway *inside* a bridged container is unreachable even from the host. `scripts/docker/setup.sh` defaults to `OPENCLAW_GATEWAY_BIND=lan` specifically so host access works. **The security boundary is the compose port mapping** (`127.0.0.1:18789:18789`, host-side), not the app's internal bind mode — setting `gateway.bind: loopback` inside the container would break the deploy, not make it safer.
- **Channel DM policy is per-channel, not a global `session.*` key.** Source (`src/config/types.channel-messaging-common.ts`, `types.base.ts`): `dmPolicy: "pairing" | "allowlist" | "open" | "disabled"` and `allowFrom: Array<string | number>` are both **per-channel** fields (e.g. `channels.telegram.dmPolicy` / `channels.telegram.allowFrom`), matching pickleclaw's actual working Telegram config. `session.dmScope` is a real but *different* setting (session isolation scope: `"main"` vs `"per-account-channel-peer"`, etc.) — don't confuse the two.
- **`${VAR}` env-secret templating is real**, confirmed in source (`src/config/types.secrets.ts`: `ENV_SECRET_TEMPLATE_RE`, a third `"env"` SecretRef source alongside the `exec`/`file` forms pickleclaw exercised hands-on). So the plan's `apiKey: "${OLLAMA_API_KEY}"`-style shorthand is legitimate for provider config it just isn't the mechanism pickleclaw itself tested.
- **The model-registration pairing (provider entry + `agents.defaults.models` + `model.primary`) is the *official documented pattern***, not just our inference from a cost incident. Every custom-provider example in `docs/gateway/config-tools.md` (Cerebras, Kimi, etc.) pairs `models.providers.<id>` with both `agents.defaults.model.primary` *and* an `agents.defaults.models` registration entry. Skipping the registration is what caused pickleclaw's silent-fallback-to-expensive-model incident — the docs don't call this failure mode out explicitly, but they never show the registration as optional either.
- **`$include` is a real, documented config mechanism** (`docs/gateway/configuration-reference.md`): a config value can be `{ $include: "./file.json5" }` (or an array of files, deep-merged), and OpenClaw resolves it into the containing key. Constraints: include paths must resolve **inside** the top-level config directory; a single-file include **replaces** the whole containing key (so one include file can't back two differently-shaped sections); `openclaw`-owned writes (`config set`, `plugins install`, etc.) write through to a single-file include target, so a read-only-mounted include blocks CLI writes to that section. This is the real mechanism to resolve the version-control catch above.
- **Fresh bring-up needs onboarding to run at least once — `OPENCLAW_SKIP_ONBOARDING` is for re-runs, not initial setup.** Confirmed via the docker setup script's own test suite (`src/docker-setup.e2e.test.ts`): with `OPENCLAW_SKIP_ONBOARDING=1`, the script still runs `config set --batch-json` for `gateway.mode`/`gateway.bind` — implying a config file must already exist to patch. The **manual flow** in `docs/install/docker.md` confirms the real sequence: `onboard --mode local --no-install-daemon` (with docker-specific flags: `--gateway-auth token --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN --skip-ui --suppress-gateway-token-output`) → `config set --batch-json [...]` → `docker compose up -d`. This is the same shape as pickleclaw's own bare-metal approach (scripted onboarding flags, then `config set`/`patch` calls) — **not** "skip onboarding entirely and boot from a static mounted file."

## Sandboxing deep dive

Sandboxing wasn't exercised on the `pickleclaw` spike (it's off — see below), so this section is a source read (`docs/gateway/sandboxing.md`, `docs/gateway/sandbox-vs-tool-policy-vs-elevated.md`, and the `src/agents/sandbox/` implementation, all tag `v2026.6.10`) plus one live check against the running instance. Treat the mechanics as source-verified, but "how it behaves in practice at scale" as untested.

### What it functionally is

Tool policy (`tools.allow`/`tools.deny`) decides *which tools exist*; sandboxing is a separate control that decides *where a tool runs* when it does. With sandboxing off — today's `pickleclaw` state, and the deploy plan's day-one default — `exec`/`read`/`write`/`edit`/`process` all run directly inside the OpenClaw gateway's own process/container. Turning sandboxing on for the Docker backend doesn't add a restricted view of that same environment (the way a filesystem/network allowlist would) — it spins up a **genuinely separate container** per agent/session/shared scope, with its own filesystem root, process/PID namespace, and network namespace, reused across calls until `openclaw sandbox recreate`.

Defaults for that container: filesystem starts from `openclaw-sandbox:bookworm-slim` (bash/curl/git/jq/python3/ripgrep, non-root `sandbox` user, no Node) with nothing of the host or gateway visible unless granted; network is `--network none` (zero egress, not a proxy allowlist — nothing to reach at all until widened); it does **not** inherit the host/gateway's `process.env` (only `sandbox.docker.env` passes through); `--security-opt no-new-privileges` is always applied. Capability drops, seccomp/AppArmor profiles, and resource limits (`memory`, `cpus`, `pidsLimit`, `ulimits`) all exist in the config schema (`src/config/types.sandbox.ts`) but are **opt-in with no default** — out of the box there's no memory/CPU/process-count cap on a sandboxed container.

### The filesystem bridge — reads and writes are handled differently (`src/agents/sandbox/fs-bridge.ts`, `fs-paths.ts`)

`workspaceAccess` (`none`/`ro`/`rw`) controls whether the real agent workspace is bind-mounted into the sandbox container at all (`/agent` ro, `/workspace` rw); `"none"` — the default — mounts nothing, resolving instead to an isolated scratch dir (`~/.openclaw/sandboxes/...`), so reads/edits only ever touch that copy unless something is explicitly staged in (skills are mirrored in; inbound media is copied to `media/inbound/*`).

When a real workspace *is* bind-mounted, reads and mutations route differently:
- **Reads bypass the container entirely.** The gateway process (outside the sandbox container) resolves the sandboxed container path back to the real host-side path underneath the bind mount, and opens it directly with `fs.readFileSync` — no `docker exec`, no round-trip into the container. Boundary/symlink safety checks happen at open time.
- **Writes/edits/mkdir/remove/rename/stat genuinely run inside the container.** Each becomes a small "pinned" shell script executed via `docker exec` in the sandbox container's own process/permission context, with path-safety checks re-run immediately before execution to close the TOCTOU gap. A sandboxed edit is not a host-side write in disguise — it actually executes from inside that container.

The SSH/OpenShell backends can't bind-mount over a network at all: the workspace is **seeded once** (copied) into the remote target, and reads/writes act on that remote copy over SSH afterward — OpenShell's `mirror` mode re-syncs before/after every exec to fake continuity; `remote` mode (and the plain `ssh` backend) just lets the remote copy drift from local after the initial seed.

### Backend comparison, including why Docker-in-Docker doesn't help here

| | Docker (root socket) | Docker (rootless host daemon, `woodpecker` pattern) | Docker-in-Docker (nested daemon) | `ssh` backend |
|---|---|---|---|---|
| Needs a Docker socket at all | Yes, host root | Yes, but a scoped rootless one | No (self-contained) | **No** |
| OpenClaw-documented | Yes | Yes (just a socket path) | **Not mentioned anywhere in the docs** | Yes |
| DooD path-mapping complexity (host-absolute config paths, gateway needs an identical volume map) | Yes | Still yes — still sibling-container spawning via a socket | No — nested daemon shares the gateway's own filesystem | N/A |
| New host infra | None | A dedicated rootless-dockerd system user | None, but untested/privileged territory | None (or one small dedicated sandbox container) |
| Sandboxed browser support | Yes | Yes | Yes | **No** |

`woodpecker` already solved "Docker backend without the root socket" on this exact box: a second, **rootless** `dockerd` runs on picklelab as a dedicated low-value `ci` user (uid 2000) that owns nothing sensitive; the agent container only ever mounts that user's socket, never root's. That's the pattern to reuse if the Docker sandbox backend is ever wanted — not Docker-in-Docker, which would need the gateway container to run privileged (or a rootless-in-container setup) and is unsupported/untested by OpenClaw's own docs, for a benefit (sandboxed browser) that's moot since the plan keeps the browser off. The **`ssh` backend remains the cleanest fit for this deploy**: no socket, no new host daemon, no DooD path-mapping dance — point it at one small dedicated low-privilege sandbox container/VM on picklelab.

### Current `pickleclaw` state, and the "non-main" gotcha

Live check (`openclaw sandbox explain`): `mode: off` — nothing has ever run sandboxed on `pickleclaw`; all 13 sessions to date (Telegram DMs, seven separate Control UI dashboard connections, cron heartbeats, a standalone heartbeat session, three explicit test sessions) ran directly on the VM.

Worth knowing before choosing `mode: "non-main"`: the classification (`src/agents/sandbox/runtime-status.ts`) is a literal string comparison, `sessionKey !== mainSessionKey`, where `mainSessionKey` is always exactly `"agent:main:main"`. On the running instance, **every Control UI dashboard connection gets its own random-UUID session key** (`agent:main:dashboard:<uuid>`) — never the literal main key — so `"non-main"` mode would sandbox the operator's own browser sessions right alongside Telegram, not just the channel traffic. It even sandboxes the heartbeat, whose session key (`agent:main:main:heartbeat`) fails the exact-string match by one suffix. In other words, `"non-main"` means "everything except one specific CLI-driven session," not "channels vs. me" — getting "Telegram sandboxed, my own dashboard use not" requires a per-agent/per-channel override (`agents.list[].sandbox`) instead of the built-in mode heuristic.

## Open questions to resolve before a plan

- **Why / use case?** What do you actually want it to *do* (ops assistant? notifications? home-automation glue calling the existing `just` CLIs?). The use case decides how much host access it needs — which decides whether it's safe here at all.
- **Which channel(s)?** Telegram (outbound-only, no public ingress) is the lowest-surface starting point. WhatsApp/Discord-webhook needs Funnel.
- **Which Ollama cloud model + plan tier?** Backend is decided (Ollama cloud subscription). Remaining: pick the model from Ollama's catalog and confirm the subscription tier covers an always-on agent's request volume.
- **Tool surface?** Default OpenClaw can run shell + browse + filesystem. Decide the minimum set; disable the browser unless needed (saves ~4 GB RAM and a big chunk of attack surface).
- **Exact image facts:** pin the real default port, the in-container home/user, and the canonical volume paths from the official image before writing compose — public guides disagree.

## Suggested next step

A short spike: pull the official image, confirm the real port / volume paths / default user, and stand it up **locally (not on picklelab)** wired to Telegram with a single allowlisted chat ID, the browser tool **off**, and the Ollama cloud subscription as the backend. That validates the mechanics, the channel-auth front door, and the Ollama provider wiring before committing to an on-host deploy and writing a `docs/plans/` design doc.

## Sources

- **`pickleclaw`** (sibling repo, `~/github.com/technicalpickles/pickleclaw`) — the running spike referenced throughout [`spike-questions.md`](spike-questions.md), diverged to npm/OrbStack/OpenRouter instead of docker/Ollama. See `docs/setup-notes.md` and `CLAUDE.md` there for the full log; this doc only pulls the facts that transfer to the docker/Ollama/picklelab deploy.
- **OpenClaw source** — `pickleclaw`'s gitignored `vendor/openclaw` clone, pinned to tag `v2026.6.10` (matching its installed CLI version). Used to verify config schema/mechanism questions the runtime spike and docs summaries couldn't settle: `src/config/types.*.ts` (dmPolicy/allowFrom shape), `src/config/types.secrets.ts` (SecretRef `env` source), `docs/install/docker.md` + `src/docker-setup.e2e.test.ts` (bind-mode env var, onboarding-vs-skip sequencing), `docs/providers/ollama-cloud.md` (built-in provider, native-API-vs-`/v1` warning), `docs/gateway/configuration-reference.md` (`$include`).
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
