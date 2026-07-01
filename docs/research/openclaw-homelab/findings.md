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
- **Embeddings need a second provider — Ollama Cloud only serves chat.** OpenClaw's memory-search feature (`agents.defaults.memorySearch`) needs its own embedding model, and Ollama Cloud doesn't offer one: hitting its hosted `/api/embed` returns `401 unauthorized` for every model tried (confirmed against six model names, ruling out a wrong model name or a proxy artifact), and Ollama's own docs list `/v1/embeddings` as "Coming soon." This isn't a key-scope problem to work around, it's a missing capability. Keep OpenRouter configured as a second provider for embeddings only (e.g. `qwen/qwen3-embedding-8b`, 4096-dim, ~$0.01/M) — chat/heartbeat stay on Ollama Cloud, embeddings route through OpenRouter's `exec` SecretRef reading its own stored auth-profile key. That means **two provider secrets** in the deploy (`OLLAMA_API_KEY` and an OpenRouter key), not one. Revisit if Ollama ships embeddings later.
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
| **Config dir** (`/home/node/.openclaw`) | agent config, auth-profiles, channel credentials, session transcripts, the memory-search SQLite index | `/srv/data/openclaw/config/` | **No** — config intermingled with runtime state + tokens; restic-backed |
| **Workspace dir** (`/home/node/.openclaw/workspace`) | agent identity/memory files (`AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `memory/*.md`, etc.) and files the agent reads/writes | `/srv/data/openclaw/workspace/` | **Yes** — OpenClaw's own docs recommend this as its own **private git repo**, separate from restic. See [Workspace git backup](#workspace-git-backup) below. |
| **Auth-secret dir** (`/home/node/.config/openclaw`) | auth/profile secrets (separate dir, official) | `/srv/data/openclaw/auth/` | **No** — secrets |
| **Tools/bin dir** (our addition, via `OPENCLAW_EXTRA_MOUNTS`) | extra CLIs we want the agent to call (see below) | `/srv/data/openclaw/bin/` on PATH | Manifest yes, binaries no |

### Update path (moving image versions)

Source: `docs/install/docker.md`, `docs/install/docker-vm-runtime.md`, `docs/install/updating.md`, `docs/install/hetzner.md`, `docs/install/gcp.md`, `docs/install/migrating.md`, `docker-compose.yml`, `scripts/docker/setup.sh`, `scripts/clawdock/clawdock-helpers.sh` (`clawdock-update`), tag `v2026.6.11`.

This deploy pulls a **pre-built image** — no local Dockerfile build, matching the plan's tier-1/tier-2 no-rebuild tool model above. The image is pinned via **`OPENCLAW_IMAGE`**, which holds the *full* image reference including tag (e.g. `ghcr.io/openclaw/openclaw:2026.6.11`) — confirmed in the bundled `docker-compose.yml` (`image: ${OPENCLAW_IMAGE:-openclaw:local}`), `scripts/docker/setup.sh`, and the `hetzner.md`/`gcp.md` VM-deploy guides.

- **ClawDock's `clawdock-update` doesn't apply.** It runs a full `docker compose build` against a source checkout — the pattern for VMs baking custom binaries into their own Dockerfile (the `gogcli`/`goplaces`/`wacli` example), and the same default pattern every official VM-deployment guide uses (`hetzner.md`, `gcp.md`, `docker-vm-runtime.md`'s own "Updates" section: `git pull && docker compose build && docker compose up -d`). None of them walk through a pinned-image-tag-bump workflow directly — it's a valid pattern the tooling supports, just not the one any guide documents end to end.
- **The mechanism for this deploy:** bump `OPENCLAW_IMAGE` in `.env` → `docker compose pull` → `docker compose up -d` to recreate the container with the new image. This only works cleanly because our own `compose.yaml` (see the plan's compose sketch) declares no `build:` key. A service that pairs `image:` with `build:` — as the upstream bundled `docker-compose.yml` does — makes `docker compose pull` ambiguous (`docker compose pull --help` documents an `--ignore-buildable` flag specifically for this case), which is why `scripts/docker/setup.sh` instead runs a plain `docker pull <full-ref>` before `docker compose up -d`. Leaving `build:` out of our own compose file avoids that ambiguity, so `docker compose pull` there is safe to use directly.
- **State survives, confirmed twice over.** `docker.md`'s "Storage and persistence" section and `docker-vm-runtime.md`'s "What persists where" table agree: `openclaw.json`, `.env`, `agents/<id>/agent/auth-profiles.json`, the auth-profile secret key dir, the workspace, and installed-plugin package roots are all host bind-mounts. The Docker container itself is explicitly documented as disposable ("Docker container | Ephemeral | Restartable | Safe to destroy").
- **Run `doctor` after the swap** — `updating.md` says `openclaw doctor` "migrates config, audits DM policies, and checks gateway health," and `migrating.md`'s machine-move flow runs it for the same reason (apply config-schema migrations after a version change). For this Docker deploy that's the CLI sidecar form, `docker compose run --rm openclaw-cli doctor`, following the same pattern as every other post-start CLI command in `docker.md`. A version bump can carry a config migration the running container's old code never applied; skipping `doctor` risks the new image reading a config shape it expects `doctor` to have already migrated.
- **The auto-updater is a non-issue here.** It exists (`update.auto.enabled` in `openclaw.json`) but only drives npm/git self-managed installs re-running their own updater; it has no mechanism to bump a Docker Compose image tag, so it's simply inert for this deploy shape rather than something to disable.

**Confidence:** the persistence claims are source-confirmed (two independent docs agree, same volume architecture picklelab already assumes). The pull/recreate recipe above is derived directly from `scripts/docker/setup.sh`'s pull/build logic — no doc states it as a named workflow — and is **not yet live-tested**: `pickleclaw` runs the npm/OrbStack install, not Docker, so there's no hands-on image-bump test yet. Flagged in `spike-questions.md` §9 as the next thing to validate on picklelab.

**Live test of the adjacent npm-install update flow (2026-07-01, on `pickleclaw`):** a real update (`2026.6.10` → `2026.6.11`, a registry patch bump) ran end-to-end via `openclaw update` → recovery → `openclaw doctor` → `openclaw gateway restart`. This confirms the *general* update/doctor/config-migration mechanics both install types share — command sequence, doctor-driven config migration, config/memory/sessions/channel auth surviving an update — but not the Docker-specific pull/recreate mechanism, since npm self-updates via `openclaw update` while Docker has no such self-updater.

Findings from that run:
- A **root-owned global npm install** (package installed via `sudo npm install -g`) blocks `openclaw update` with `EACCES`, since the CLI runs as a normal user and the update stages into a temp dir under the package root it can't write to. Recovery: `openclaw gateway stop` → `sudo npm i -g openclaw@latest` → `openclaw gateway install --force` → `openclaw gateway restart`.
- **Failure handling is clean.** OpenClaw stops the gateway before attempting the package swap and automatically restarts it back to the working pre-update state on failure, with no state loss.
- **A manual recovery (sudo npm install directly, rather than a clean `openclaw update` run) skips the "plugin update sync" step `update` normally runs automatically.** Check `openclaw gateway status --deep` after any manual recovery — it reports plugin version drift (an installed plugin still pinned to the old gateway version), fixed with `openclaw plugins update <name> && openclaw gateway restart`.
- **The version bump carried a real, if minor, state migration**, not a no-op patch bump: `doctor`/`gateway restart` auto-migrated legacy `update-check` state into shared SQLite, archiving the old JSON file.
- **Config, memory, sessions, and channel auth all survived unchanged:** all 13 pre-update sessions were still listed post-update; memory index unchanged (6/6 files, 12 chunks, not dirty); Telegram channel still `installed, configured, enabled`; a live chat smoke test (`openclaw agent --agent main -m "..."`) worked before and after, replying correctly via the same `ollama-cloud/glm-5.2` model pin.

### What can be version-controlled

The split mirrors every other homelab service: **declarative config → repo, runtime state → `/srv/data`, secrets → 1Password.** Specifically committable:

- The **declarative tool/provider/channel config** (the [`config-tools`](https://docs.openclaw.ai/gateway/config-tools) layer + MCP server definitions), with secrets written as `${ENV}` refs, never literals. Ship it as a committed config file the container reads, or template it like `.env`.
- compose files, `.env.vars`, `deploy.sh` — same as every service.

The catch (partly resolved by the official doc): **auth secrets are already in their own dir** (`OPENCLAW_AUTH_PROFILE_SECRET_DIR`=`/home/node/.config/openclaw`), separate from config — good. But declarative config still lives in `/home/node/.openclaw` **alongside** session transcripts, auth-profiles, and the memory-search SQLite index (the workspace itself, including memory files, is a separate mount — see [Workspace git backup](#workspace-git-backup) below). So we can't cleanly mount "config in git, state on disk" as two dirs.

**Refined plan, backed by a real mechanism (`$include`, verified in source — see below):** don't try to mount the whole root config file read-only; the root `openclaw.json` must stay **writable** (onboarding creates it, and it holds the gateway token / mainKey / session store paths that can't be static). Instead, bind-mount small **committed include files** read-only *inside* the config dir (`$include` targets must resolve inside the config directory), and have the writable root file `$include` specific top-level sections (`tools`, `mcp`, etc.) from them. Non-secret structure lives in git; the live root file is a thin, mostly-onboarding-generated shell that points at it. One caveat: OpenClaw's own `config set`/`config patch` **writes through** to a single-file-include target for that section — so a read-only-mounted include file blocks CLI writes to that section (fine for us: changes flow through git + redeploy, not live `config set`). Not yet exercised hands-on by any spike — flagged in `spike-questions.md` §3 as the next thing to validate.

### Workspace git backup

The workspace is a **separate** version-control story from the declarative config above — a different mount, a different reason to be in git. Source: `docs/concepts/agent-workspace.md`, tag `v2026.6.11`; live-tested on `pickleclaw` 2026-07-01.

OpenClaw's own docs recommend git-backing the workspace **as its own private repo**, independent of whatever repo holds the deploy's declarative config. It's auto-initialized as a local git repo on first run (if git is installed), and `openclaw doctor` prints a backup nudge if it detects the workspace isn't under git yet.

- **In the workspace (git-trackable):** `AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `TOOLS.md`, `HEARTBEAT.md`, `BOOT.md`, `BOOTSTRAP.md`, `memory/YYYY-MM-DD.md`, `MEMORY.md`, workspace-level `skills/`, `canvas/`.
- **Never in the workspace, never git-trackable even in a private repo** (the official doc is explicit about this list): `openclaw.json` (config), `agents/<id>/agent/auth-profiles.json`, `agents/<id>/agent/codex-home/`, `credentials/` (channel/provider state), `agents/<id>/sessions/` (transcripts), the managed `~/.openclaw/skills/`. All of that lives under the config-dir mount, not the workspace mount, so it's structurally separate — but worth stating explicitly since "memory" is easy to conflate: the *raw* memory markdown files live in the workspace (trackable); the *SQLite vector index* built from them for memory search lives in the config dir (not trackable, regenerable).
- **Live-tested on `pickleclaw`:** the workspace already existed as an uncommitted local repo (zero commits, no remote). Backed it with a new private repo, authenticated via a repo-scoped SSH deploy key (write access, not a personal token) so the VM can push on its own. Initial commit + push succeeded with no secrets present (checked before committing).

**For the picklelab Docker deploy:** this is an open design question, not yet resolved in the plan — `/srv/data/openclaw/workspace/` is already restic-backed, but restic and "clone it to a new machine / branch history" are different recovery properties. Worth deciding whether the picklelab workspace also gets its own private git repo (mirroring this pattern) or whether restic-only is sufficient given it's a single always-on deploy, not something regularly moved between machines.

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

This is the same "spike already running on the laptop" that [`spike-questions.md`](spike-questions.md) was written to interrogate — [`pickleclaw`](https://github.com/technicalpickles/pickleclaw) (sibling repo, not in this tree), running since 2026-06-25. It diverged from that checklist's assumptions in two ways: OpenClaw installed via `npm install -g` (not Docker) in an OrbStack Ubuntu VM, and originally backed by OpenRouter — **since switched to Ollama Cloud for chat/heartbeat on 2026-07-01** (OpenRouter kept for embeddings only, which Ollama Cloud doesn't yet support), with Telegram wired up. So it does **not** validate the docker-image or NUC-hardware items (spike-questions §1, §7) — those still need their own pass — and while the Ollama-provider item (§4) now has a live wiring + basic-chat confirmation, its actual load-bearing question (tool-calling quality/latency/rate-limits) is still untested. This section is hands-on confirmation of the **application-level mechanics** (config format, secrets, channel auth, tool plugins, UI auth) that transfer regardless of how/where OpenClaw runs.

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

### Sandbox vs nodes (different tools, small overlap)

Sandboxing and OpenClaw **nodes** feel adjacent (both "isolate where code runs") but solve different
problems, and only overlap on one narrow axis. Source: `docs/nodes/index.md`, `docs/cli/nodes.md`,
`docs/gateway/sandboxing.md`, tag `v2026.6.11`; the peripheral-capability side of nodes is live-tested
on `pickleclaw` (a paired Mac), the exec/host-reach side is not (see below).

A **node** is a separate paired device (macOS/iOS/Android/**headless** `openclaw node run`) that
connects to the gateway WS with `role: "node"` and exposes a command surface; an **exec node**
(`tools.exec.host=node`) forwards `system.run` to a node host that enforces its **own**
`~/.openclaw/exec-approvals.json` and holds its **own** tool credentials. The gateway runs the
model and routes the call; the node executes it and owns the authority.

The single overlap: **both can make a tool call run off the gateway.** Sandbox's `ssh` backend runs
the agent's own tools on a remote host; an exec node forwards `system.run` to a paired host. Squint
at "the command ran on box B" and they match. Everything else diverges:

| | **Sandbox** | **Node** |
|---|---|---|
| Purpose | **Contain** the agent's own tools | **Delegate/reach** to another machine |
| Trust direction | Subtract power (protect host *from* agent) | Relocate + isolate power (protect creds, extend reach) |
| What runs there | Agent's tools, seeded from image + workspace copy | Whatever that machine has installed |
| Authority | Gateway creates and controls the box | Node owns its exec-approvals + creds; gateway **cannot** override them |
| Identity | Cattle: per-agent/session/shared, disposable | Pet: durable paired device, persistent fs |
| Trigger | Automatic (`mode: non-main`/`all`) | Explicit routing (`host=node`) |

The distinction in one line: **sandbox = "run this somewhere with *less* power"; node = "run this
somewhere with *different, self-owned* power."** Credential isolation (a node-side CLI's token never
reaching the gateway) is a **node** property a sandbox can't give — a sandbox is still the gateway's
agent running the gateway's tools, just boxed. Even the `ssh` backend is containment (seeded
workspace, agent's own tools), not a peer with independent authority.

**Fit with `homelab_07`:** this maps cleanly onto the access model.

- **Sandbox is the demoted control** `homelab_07` already says it is ("useful for the agent runtime,
  not the primary control mechanism"; "the main risk is not kernel escape, it is incorrect but fully
  authorized changes to real system state"). The deploy plan's containment already comes from *the
  gateway container itself* + default-deny tool policy, so the OpenClaw Docker sandbox is a redundant
  second cage whose price (`/var/run/docker.sock`) the plan correctly declines.
- **A node is the better-aligned tool for reach.** A node host's per-machine `exec-approvals.json` is
  literally the "narrow operational interface" `homelab_07` wants: a human-editable, target-owned
  allowlist of specific commands, no `docker.sock`, no privileged gateway. If the agent ever needs to
  act on picklelab-the-host (not inside the container) or on another box, a node host there is a
  tighter fit than widening the container's own tool policy, because the authority sits host-side
  where a human audits it. That matches evolution-path steps 3-4 (wrapper commands, limited deploy
  sudo).

**Where they meet in config:** if sandboxing is ever turned on, `tools.elevated` with a `node` target
is the documented escape hatch — sandbox-by-default, break out to one named node for one vetted
operation. Useful pattern for the cheap-model-with-tools tension: caged agent, one auditable door.

### Nodes, live-tested on `pickleclaw` — peripheral capabilities, not exec/host reach

A **device** is the identity + pairing + role grant (`devices/paired.json`); a **node** is just a
device whose granted roles include `node` — it's a role, not a separate object. `openclaw devices
list` is the full auth table; `openclaw nodes list` is the `node`-role slice of it. One device can
hold both `node` and `operator` roles (e.g. a paired Mac is both a peripheral the agent can reach
and a dashboard operator), so it shows up in both lists. Duplicate entries accumulate as each new
enrollment (browser tab, incognito session, CLI token, reinstall) mints a fresh record; since each
`operator` device is a live admin credential, pruning stale ones is security hygiene, not tidying.

Every node command must pass **two gates** before it runs: the node's own declared capability
(its WS `connect.commands` list) and the gateway's `gateway.nodes` allow/deny policy. `system.run`
specifically has a **third** gate on the node itself — its own `~/.openclaw/exec-approvals.json`
(or the equivalent app setting) — frozen before the command crosses the wire, so nothing between
approval and execution can change what runs.

**A capability can be gated by an app-level setting distinct from the OS permission behind it.**
On the live test, `openclaw nodes location get` failed with "node does not support location.get"
even though the OS Location Services permission was already granted. The node only advertises
`location.get` when the macOS app's own **Location Access** setting (Off/While Using/Always,
defaulting to **Off**) is not Off — the OS grant is necessary but not sufficient. Fixed by setting
it to While Using in the app; the node re-advertised the capability on its next connect handshake.
Worth knowing generically: when a node "doesn't support" a command it plausibly should, check the
node-side capability toggle before assuming a missing feature.

**What this does and doesn't validate for this deploy:** the live test covers nodes as
peripheral-capability delegation (a companion device exposing canvas/screen/location/etc. to the
agent) — a different use case from the **exec node** (`tools.exec.host=node`) this deploy is
interested in for reaching picklelab-the-host or another box. `pickleclaw`'s node is paired for
capabilities only; `tools.exec` is unset there, so nothing routes shell execution to a node yet.
The device/node role model, the two/three-gate authorization flow, and the capability-vs-permission
distinction all transfer conceptually, but exec-forwarding itself remains source-derived only.

**Bottom line for this deploy:** sandboxing and nodes are not substitutes. Don't enable OpenClaw
sandboxing (containment is already covered, and its cost is the socket we won't grant). Keep an
**exec node** in reserve as the "trust grows with capability" mechanism for letting the agent act
on the host or other boxes later — the node role model above is confirmed live, but exec-forwarding
through it specifically still needs its own test.

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
- **OpenClaw source** — `pickleclaw`'s gitignored `vendor/openclaw` clone, pinned to tag `v2026.6.10` (matching its installed CLI version). Used to verify config schema/mechanism questions the runtime spike and docs summaries couldn't settle: `src/config/types.*.ts` (dmPolicy/allowFrom shape), `src/config/types.secrets.ts` (SecretRef `env` source), `docs/install/docker.md` + `src/docker-setup.e2e.test.ts` (bind-mode env var, onboarding-vs-skip sequencing), `docs/providers/ollama-cloud.md` (built-in provider, native-API-vs-`/v1` warning), `docs/gateway/configuration-reference.md` (`$include`), `docs/install/docker-vm-runtime.md` + `docs/install/updating.md` + `docs/install/migrating.md` + `scripts/clawdock/clawdock-helpers.sh` (update path, persistence table, `doctor` post-migration step).
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
