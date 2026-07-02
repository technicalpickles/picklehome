# OpenClaw on picklelab — deployment design

Deploy OpenClaw (self-hosted AI gateway: chat → agent that can act) as a homelab service, following the standard Compose + systemd + Tailscale Services + 1Password pattern.

**Status:** ready to implement. The spike phase — see [`docs/research/openclaw-homelab/spike-questions.md`](../research/openclaw-homelab/spike-questions.md) — is done: §1–§10 resolved or substantially live-tested, most directly on picklelab itself, not just the laptop spike. One item is accepted as a residual unknown rather than a pre-deploy blocker (RAM/CPU under real agentic load — see [Open questions](#open-questions)). Research backing this doc: [`docs/research/openclaw-homelab/findings.md`](../research/openclaw-homelab/findings.md).

## Goals

- A phone-reachable agent surface (chat → OpenClaw), a sibling to `brineworks-agent` / `second-brain-agent`: trusted-but-shaped, deployed on purpose.
- Zero new infra patterns: reuse Compose + `compose.picklelab.yaml`, systemd oneshot, Tailscale Services, `service-env`/1Password.
- **Off-box inference** via an Ollama cloud subscription (no local model on the GPU-less J3455).
- A tool-iteration loop that does **not** require rebuilding the image (drop-in CLIs like `gogcli`; MCP for structured tools).
- Minimal day-one blast radius; widen tool access deliberately (trust-grows-with-capability, per `homelab_07`).

## Non-goals

- Public ingress. Telegram long-polls outbound; the UI is Tailscale-only. No Funnel (unlike `woodpecker`). WhatsApp/Discord-webhook channels are a later, separate decision.
- Local LLM inference. Not viable on the J3455; the cloud subscription is the backend.
- OpenClaw's Docker **tool-sandbox** on day one — it needs `/var/run/docker.sock`, which `homelab_07` says don't grant. We rely on the gateway already being containerized + default-deny tool policy instead (see [Security decisions](#security-decisions)).
- Wiring the agent into climate/locks/vault tools on day one. Start with notifications + a couple of read-only `just` checks.

## Architecture

```
Phone / desktop (Telegram)            You (browser, control UI)
        |                                     |
        | bot API (outbound long-poll)        | https://openclaw.tail2023b7.ts.net
        v                                     v
  api.telegram.org                  Tailscale Services (TLS terminate)
        ^                                     |
        |  outbound only, no ingress          v
        |                          picklelab tailscaled → 127.0.0.1:18789
        +----------------------------------+  |
                                           v  v
                                docker container (ghcr.io/openclaw/openclaw)
                            user node (uid 1000), gateway.bind=lan internally,
                              published to the host only as 127.0.0.1:18789
                                           |
                  +------------------------+------------------------+------------------+
                  v            v             v                      v                  v
        /srv/data/openclaw/  config/     workspace/   auth/      bin/  (tools on PATH)  includes/*.json5 (from private pickleclaw repo, ro)
                  |            |             |          |
              restic-backed  (config + memory + tokens, credentials/, sessions/)
                                           |
                          Ollama cloud  ──>  https://ollama.com  (native /api/chat, outbound, ${OLLAMA_API_KEY})
                          OpenRouter    ──>  https://openrouter.ai  (embeddings only, outbound, ${OPENROUTER_API_KEY})
```

Two independent trust boundaries, both locked down:

- **Network reach** ("who can open the UI") — Tailscale Services. The control UI is additionally gated by a **gateway token**.
- **Logical access** ("who can drive the agent") — the **channel allowlist**: only our Telegram chat ID(s) may message the bot. This is the equivalent of the SSH key that gates the other agent containers.

## Service layout

`homelab/services/openclaw/`, per [`homelab/services/README.md`](../../homelab/services/README.md):

| File | Purpose |
|------|---------|
| `compose.yaml` | Local dev compose (named volumes) |
| `compose.picklelab.yaml` | Prod overrides: bind mounts to `/srv/data/openclaw/{config,workspace,auth,bin}` |
| `deploy.sh` | scp + `mkdir -p`/`chown` data dirs + onboard-if-needed + `config set --batch-json` + systemd install + `tailscale serve` |
| `.env.vars` | Var names this service needs (filtered from master `.env`) |
| `openclaw.tools.json5` | `$include` target for the `tools` section (profile, allow/deny, exec policy). **Not committed here** — symlinked from the private `pickleclaw` repo, see [Where the include files actually live](#where-the-include-files-actually-live) |
| `openclaw.mcp.json5` | `$include` target for the `mcp.servers` section. **Not committed here** — same as above; this one would otherwise leak MCP server names/commands into a public repo |
| `openclaw.service` | systemd unit (long-lived oneshot + `RemainAfterExit`) |
| `README.md` | Service-specific setup |

### compose.yaml

```yaml
services:
  openclaw:
    image: ${OPENCLAW_IMAGE:?pin a version, e.g. ghcr.io/openclaw/openclaw:2026.6.11}   # full ref incl. tag
    # No `build:` key on purpose: pairing `image:` with `build:` makes `docker compose pull`
    # ambiguous about whether to pull or build. We don't ship a Dockerfile, so omitting `build:`
    # keeps `docker compose pull` unambiguous — it only ever pulls the named image.
    restart: unless-stopped
    user: "1000:1000"                      # image default (node); data dir isn't shared, so 1000 is fine
    environment:
      OPENCLAW_GATEWAY_BIND: lan            # NOT loopback — see "Port & bind topology" below for why
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:?required}
      OLLAMA_API_KEY: ${OLLAMA_API_KEY:?required}          # ollama-cloud is a built-in provider, no custom config needed
      OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:?required}  # embeddings only — Ollama Cloud doesn't support them
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:?required}
      OPENCLAW_ALLOWED_CHAT_IDS: ${OPENCLAW_ALLOWED_CHAT_IDS:?required}
      OPENCLAW_EXTRA_MOUNTS: "/srv/data/openclaw/bin:/opt/tools:ro"   # tools dir, read-only
      PATH: "/opt/tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"  # live-tested (spike §6): PATH additions picked up with no gateway restart
    ports:
      - "127.0.0.1:18789:18789"
    volumes:
      - config:/home/node/.openclaw                                            # writable — onboarding creates openclaw.json here
      - workspace:/home/node/.openclaw/workspace
      - auth:/home/node/.config/openclaw
      - ./openclaw.tools.json5:/home/node/.openclaw/includes/tools.json5:ro     # symlinked from pickleclaw (private repo), not committed here — $include mechanism exercised hands-on, spike §3
      - ./openclaw.mcp.json5:/home/node/.openclaw/includes/mcp.json5:ro         # symlinked from pickleclaw (private repo), not committed here — see "Where the include files actually live"

volumes:
  config:
  workspace:
  auth:
```

**Onboarding still runs — this is not a skip-onboarding-and-boot-from-a-static-file deploy** (see [Declarative config](#declarative-config) below for why `OPENCLAW_SKIP_ONBOARDING` doesn't mean that).

### compose.picklelab.yaml

```yaml
services:
  openclaw:
    volumes:
      - /srv/data/openclaw/config:/home/node/.openclaw
      - /srv/data/openclaw/workspace:/home/node/.openclaw/workspace
      - /srv/data/openclaw/auth:/home/node/.config/openclaw
      - /srv/data/openclaw/bin:/opt/tools:ro
      - ./openclaw.tools.json5:/home/node/.openclaw/includes/tools.json5:ro
      - ./openclaw.mcp.json5:/home/node/.openclaw/includes/mcp.json5:ro
```

### Port & bind topology

Single HTTP port **`18789`** (UI + REST + webhooks), mapped to `127.0.0.1:18789`.

**The app-internal bind mode is `lan`, not `loopback`** (`docs/install/docker.md` + `src/config/gateway-control-ui-origins.ts`). Docker's default bridge networking means traffic from a published port (`-p 18789:18789`) arrives on the container's `eth0`, not its loopback interface — a gateway bound to `loopback` *inside* the container is unreachable even from the host. `scripts/docker/setup.sh` defaults to `OPENCLAW_GATEWAY_BIND=lan` for exactly this reason (host access still works because Docker's port-publish only routes `eth0` traffic, and Docker doesn't publish `lo`). This isn't a security regression: **the real loopback restriction is the compose port mapping** (`127.0.0.1:18789:18789`, host-side) — the app can bind `0.0.0.0` internally and still be unreachable from outside picklelab, because nothing besides the host's own `127.0.0.1` is ever published. `tailscaled`'s local proxy reaches it via that same host-side loopback binding; `tailscale serve` fronts it as `https://openclaw.tail2023b7.ts.net`.

## Declarative config

Config isn't a single file we can mount read-only wholesale; the architecture rests on two facts:

1. **The root config file (`openclaw.json`) must stay writable.** It's created by `openclaw onboard` (which must actually run, at least once — see below) and holds things that can't be static: the gateway token, session-store paths, the auth-profile pointers. `OPENCLAW_SKIP_ONBOARDING=1` does **not** mean "boot from a mounted file instead" — source-confirmed (`src/docker-setup.e2e.test.ts`): even with it set, the setup script still runs `config set --batch-json` against an *existing* config, implying that flag is for **re-running setup against an already-onboarded persistent volume**, not a from-scratch bring-up.
2. **`$include` is the real mechanism for "config in git, state on disk."** A config value can be `{ $include: "./relative/path.json5" }` — resolved from **inside** the config directory, single-file includes replace the whole containing key. So instead of mounting one big file over the whole config, mount small **version-controlled include files** at `/home/node/.openclaw/includes/*.json5` (read-only) and have the writable root file `$include` specific sections from them. "Version-controlled" here means the private `pickleclaw` repo, not this one — see [Where the include files actually live](#where-the-include-files-actually-live) below.

### Bootstrap sequence (per service, mirrors the official Docker manual flow)

```bash
# 1. Onboard once — creates the writable root config, auth store, gateway token
docker compose run --rm --no-deps --entrypoint node openclaw \
  dist/index.js onboard --mode local --no-install-daemon \
    --gateway-auth token --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN \
    --skip-ui --suppress-gateway-token-output

# 2. Wire the includes + provider/channel settings that aren't onboarding flags.
#    Model chain and channel policy are pickleclaw's already-validated values, not fresh
#    picks — see "Migration from pickleclaw". channels.telegram.enabled stays false until
#    the Telegram bot cutover.
docker compose run --rm --no-deps --entrypoint node openclaw \
  dist/index.js config set --batch-json '[
    {"path":"gateway.bind","value":"lan"},
    {"path":"tools","value":{"$include":"./includes/tools.json5"}},
    {"path":"mcp","value":{"$include":"./includes/mcp.json5"}},
    {"path":"channels.telegram.enabled","value":false},
    {"path":"channels.telegram.dmPolicy","value":"allowlist"},
    {"path":"channels.telegram.allowFrom","value":["<chat-id>"]},
    {"path":"agents.defaults.model.primary","value":"ollama-cloud/glm-5.2"},
    {"path":"agents.defaults.model.fallbacks","value":["ollama-cloud/glm-4.7"]},
    {"path":"agents.defaults.heartbeat.model","value":"ollama-cloud/gpt-oss:20b"},
    {"path":"agents.defaults.heartbeat.isolatedSession","value":true},
    {"path":"agents.defaults.heartbeat.lightContext","value":true},
    {"path":"agents.defaults.models","value":{
      "ollama-cloud/glm-5.2":{},
      "ollama-cloud/glm-4.7":{},
      "ollama-cloud/gpt-oss:20b":{}
    }}
  ]'

# 3. Bring the service up for real (channel still disabled — see Telegram bot cutover)
docker compose up -d
```

`deploy.sh` makes step 1 idempotent (skip if the root config already exists on the persisted volume, and clones the migrated workspace repo before it — see [Migration from pickleclaw](#migration-from-pickleclaw)) and re-runs step 2 on every deploy so config drift self-heals from the version-controlled source (partly `picklehome`, partly the private `pickleclaw` repo — see [Where the include files actually live](#where-the-include-files-actually-live)).

### Where the include files actually live

`picklehome` is a **public** GitHub repo. `openclaw.tools.json5` is generic policy (profile name, a deny list) and is harmless to publish, but `openclaw.mcp.json5` would list actual MCP server names/commands/URLs — real information about what's wired into the homelab, not something to put in a public repo.

Both files instead live in the **private** `pickleclaw` repo (`~/github.com/technicalpickles/pickleclaw`), which already holds the config layer "above" the workspace — setup notes, `provision.sh` — as distinct from `openclaw-workspace` (the agent's own memory/identity repo, migrated separately, see [Migration from pickleclaw](#migration-from-pickleclaw)). Suggested location: `pickleclaw/openclaw-config/{tools,mcp}.json5`.

`homelab/services/openclaw/openclaw.tools.json5` and `openclaw.mcp.json5` are **gitignored** in `picklehome` (see `.gitignore`) and symlinked from the `pickleclaw` checkout as a one-time local setup step:

```bash
ln -sf ~/github.com/technicalpickles/pickleclaw/openclaw-config/tools.json5 \
  homelab/services/openclaw/openclaw.tools.json5
ln -sf ~/github.com/technicalpickles/pickleclaw/openclaw-config/mcp.json5 \
  homelab/services/openclaw/openclaw.mcp.json5
```

That keeps the compose files' `./openclaw.tools.json5` / `./openclaw.mcp.json5` relative paths unchanged for both local dev and `deploy.sh`'s scp step — they just resolve through the symlink to the real, private, version-controlled source. `deploy.sh` doesn't need its own deploy key for `pickleclaw`: it runs from the Mac, where the repo is already cloned with the operator's own GitHub access — `git pull` it before deploying, same as keeping any dependency current.

`openclaw.tools.json5` content:

```json5
// Minimal blast radius: deny runtime/fs by default, ask on exec, no browser
{
  profile: "minimal",
  deny: ["browser", "canvas", "group:automation"],
  exec: { security: "deny", ask: "always" },
}
```

`openclaw.mcp.json5` content (day one — see [Future](#future) for what widens this):

```json5
{
  servers: {
    // none day one; add per docs/cli/mcp as tool needs are decided
  },
}
```

### Ollama cloud

`ollama-cloud` is a **first-class built-in provider** (`docs/providers/ollama-cloud.md`) — there's no custom `models.providers` entry to write at all:

- Auth: `OLLAMA_API_KEY` env var (already in `.env`) — no `baseUrl`/`api` config needed.
- **Do not point anything at `https://ollama.com/v1`.** The provider uses Ollama's native `/api/chat`, base URL `https://ollama.com` (no `/v1`). The docs are explicit: *"Do not use the `/v1` OpenAI-compatible URL... This breaks tool calling and models may output raw tool JSON as plain text."*
- Model refs: `ollama-cloud/<id>` (e.g. `ollama-cloud/kimi-k2.6`); list the live hosted catalog with `openclaw models list --provider ollama-cloud`.
- Register the model in **both** `agents.defaults.model.primary` and `agents.defaults.models` (see the bootstrap `config set` above) — every official custom-provider example in `config-tools.md` pairs these; an unregistered fallback/heartbeat model silently falls through to an expensive default alias instead.

### Embeddings — a second provider, OpenRouter

Ollama Cloud only serves chat; OpenClaw's memory-search feature (`agents.defaults.memorySearch`) needs its own embedding model, which Ollama Cloud doesn't offer. Keep **OpenRouter** configured as a second provider for embeddings only (`qwen/qwen3-embedding-8b`, 4096-dim, ~$0.01/M) — chat and heartbeat stay on `ollama-cloud`. `OPENROUTER_API_KEY` resolves through an `exec` SecretRef that reads OpenClaw's own stored auth-profile key, the same pattern the auth-profile store already uses elsewhere. This means the deploy carries two model-provider secrets, not one.

### Channel front door

The DM policy config path is **per-channel** (`src/config/types.channel-messaging-common.ts`/`types.base.ts`): `channels.telegram.dmPolicy: "allowlist"` + `channels.telegram.allowFrom: [...]` — see the bootstrap `config set` above. `session.dmScope` is a real but unrelated setting (session isolation, not the allow/deny policy).

Notes:
- **Gateway token** and **bot token** stay in env (`.env`), never in a committed file.
- The config dir intermingles the writable root file with memory/tokens/credentials, so the *whole* `/srv/data/openclaw/config` is sensitive and restic-backed regardless.
- `$include` is now exercised hands-on (spike §3): `config get` correctly resolves an included file's contents. The two gotchas found there — default `config patch` merging rather than replacing an already-populated key, and `--replace-path` refusing to flatten a `$include`-owned key — only bite when *retrofitting* `$include` onto an already-configured section. This deploy's bootstrap sequence above targets brand-new keys on a fresh onboard, so neither gotcha applies here.

## Tools / extension model

Two paths, neither requires rebuilding the image (full rationale in [findings.md](../research/openclaw-homelab/findings.md#mounts-version-control-and-adding-tools)):

1. **Drop-in CLIs (`gogcli`, etc.)** — `/srv/data/openclaw/bin` is bind-mounted to `/opt/tools` (`OPENCLAW_EXTRA_MOUNTS`, official) and prepended to `PATH`. Add a tool = copy the binary in; the agent's next shell call picks it up, no restart. Base is Debian/glibc so static/Go binaries run as-is. A committed `homelab/services/openclaw/tools/manifest` (name → source URL/version) documents what should be there; `deploy.sh` fetches them onto the host. Binaries themselves stay out of git.
2. **MCP servers (structured tools)** — declared in `mcp.servers` via the `openclaw.mcp.json5` include, version-controlled in the private `pickleclaw` repo (see [Where the include files actually live](#where-the-include-files-actually-live)) rather than this public one. stdio servers run in-process; HTTP/SSE servers run as **sidecar containers**. Iterating a sidecar restarts only the sidecar; registering a *new* server needs a gateway **reload** (`openclaw mcp reload`), not an image rebuild.
3. **ClawHub plugins** — before hand-writing an MCP server, check OpenClaw's own package registry (`openclaw plugins search "<capability>"`) for a ready-made one; pickleclaw found this covers web search (Brave, Gemini) with zero custom code. Installing a plugin **needs a gateway restart to load** (not hot-add like MCP) — budget for that when adding one.

Stable system packages only (e.g. `git`) go via `OPENCLAW_IMAGE_APT_PACKAGES` at build time — not the iteration path.

## Security decisions

Maps the [official security model](../research/openclaw-homelab/findings.md#security--sandbox-model-from-the-official-gatewaysecurity--gatewaysandboxing-docs) onto `homelab_07`:

| Concern | Decision |
|---|---|
| Who can reach the UI | Tailscale Services (host-side loopback port mapping; app binds `lan` internally, see [Port & bind topology](#port--bind-topology)) + **gateway token** |
| Who can drive the agent | Channel **allowlist** (our chat IDs); default Pairing is already not-open |
| Shell/fs access | Default-deny (`group:runtime`/`group:fs` off, `exec: deny/ask:always`); widen per use case |
| Tool sandbox vs. docker.sock | **No socket.** Gateway is containerized; rely on tool policy, not the in-container Docker sandbox. Revisit a rootless socket (woodpecker-style) only if a real need appears. For *reaching the host or other boxes*, an **exec node** (not the sandbox) is the aligned mechanism — see [findings §Sandbox vs nodes](../research/openclaw-homelab/findings.md#sandbox-vs-nodes-different-tools-small-overlap) |
| Browser tool | Off (saves ~4 GB RAM, removes the biggest passive surface) |
| Prompt injection × cheap model | Small Ollama model + tools is the riskiest combo; keep tools tiny + `ask:always` while on a small model, or use a stronger tier for any tool-enabled profile |
| Egress | Outbound to `api.telegram.org` + `ollama.com` + `openrouter.ai` (embeddings only) (+ MCP endpoints). Note in README; tighten later if warranted |

## Secrets

### 1Password item: `picklehome/OpenClaw`

| field | value |
|-------|-------|
| `host` | `openclaw.tail2023b7.ts.net` |
| `gateway_token` | `openssl rand -hex 32` — picklelab's own, not shared with `pickleclaw` |
| `ollama_api_key` | reuse `pickleclaw`'s existing key (see [Migration from pickleclaw](#migration-from-pickleclaw)), not a new one from `ollama.com/settings/keys` |
| `openrouter_api_key` | reuse `pickleclaw`'s existing key — embeddings only, chat/heartbeat stay on Ollama Cloud |
| `telegram_bot_token` | `pickleclaw`'s existing bot token — not a new @BotFather bot |
| `allowed_chat_ids` | same numeric Telegram chat ID(s) `pickleclaw` already allowlists, comma-separated |

### `.env.template` additions

```
# OPENCLAW_HOST: Tailscale Services hostname
OPENCLAW_HOST={{ op://picklehome/OpenClaw/host }}
# OPENCLAW_GATEWAY_TOKEN: control-UI/API bearer token
OPENCLAW_GATEWAY_TOKEN={{ op://picklehome/OpenClaw/gateway_token }}
# OLLAMA_API_KEY: Ollama cloud subscription key (chat/heartbeat)
OLLAMA_API_KEY={{ op://picklehome/OpenClaw/ollama_api_key }}
# OPENROUTER_API_KEY: embeddings only — Ollama Cloud doesn't support them
OPENROUTER_API_KEY={{ op://picklehome/OpenClaw/openrouter_api_key }}
# TELEGRAM_BOT_TOKEN: bot identity
TELEGRAM_BOT_TOKEN={{ op://picklehome/OpenClaw/telegram_bot_token }}
# OPENCLAW_ALLOWED_CHAT_IDS: chat-id allowlist (the front door)
OPENCLAW_ALLOWED_CHAT_IDS={{ op://picklehome/OpenClaw/allowed_chat_ids }}
```

### `.env.vars`

```
OPENCLAW_HOST
OPENCLAW_GATEWAY_TOKEN
OLLAMA_API_KEY
OPENROUTER_API_KEY
TELEGRAM_BOT_TOKEN
OPENCLAW_ALLOWED_CHAT_IDS
OPENCLAW_IMAGE
```

`service-env` filters these from the master `.env` so picklelab gets only what OpenClaw needs — the master secret set never reaches a container that can run tools.

## Migration from pickleclaw

`pickleclaw` (sibling repo, OrbStack VM on the Mac, running since 2026-06-25) isn't left behind wholesale — it's the source of the agent's accumulated identity/memory, its Telegram bot identity, and its validated model chain. This deploy is a **migration + cutover**, not a from-scratch bring-up that merely reuses lessons learned. Decided: bring over workspace/memory, the Telegram bot, and the model/provider config; leave behind session transcripts, the auth-profile store, the paired node, and the web-search plugins (fast-follow, not day one); decommission `pickleclaw` once picklelab is confirmed stable.

### What carries over

- **Workspace / memory.** `pickleclaw`'s workspace is already its own private repo — `github.com/technicalpickles/openclaw-workspace` (`AGENTS.md`, `SOUL.md`, `USER.md`, `IDENTITY.md`, `TOOLS.md`, `HEARTBEAT.md`, `memory/*.md`, `MEMORY.md`, `projects/`, `skills/`). Clone that repo directly into `/srv/data/openclaw/workspace/` as the *initial* content instead of letting OpenClaw auto-init an empty one — this resolves the open question in [findings.md](../research/openclaw-homelab/findings.md#workspace-git-backup): the picklelab workspace doesn't get a *new* repo, it continues *this* one.
- **Telegram bot identity.** Same @BotFather bot/token as `pickleclaw` — continuity in the user's Telegram app, no re-adding a bot. Same `dmPolicy: allowlist` + chat-ID allowlist `pickleclaw` already runs (already this plan's day-one default — see [Channel front door](#channel-front-door)).
- **Model / provider chain.** The validated pin from `pickleclaw`'s `CLAUDE.md`: primary `ollama-cloud/glm-5.2`, fallback `ollama-cloud/glm-4.7`, heartbeat `ollama-cloud/gpt-oss:20b` (`isolatedSession: true`, `lightContext: true`), all three registered in `agents.defaults.models` per the registration trap ([findings.md](../research/openclaw-homelab/findings.md#verified-against-the-pickleclaw-spike-non-docker)). No catalog re-pick needed — this exact chain already has real tool-calling mileage (spike §4). Same two provider subscriptions (Ollama Cloud, OpenRouter for embeddings): pull the live key values from `pickleclaw`'s existing storage into the `picklehome` 1Password vault rather than minting new keys.

### What does NOT carry over

- **Session transcripts.** Ephemeral per-run state; npm and Docker installs don't share a session store, and there's nothing worth replaying.
- **Auth-profile store / credentials dir.** `pickleclaw`'s OpenRouter key lives in OpenClaw's own sqlite auth-profile store (the bare-metal `exec`-SecretRef mechanism). The Docker deploy re-provisions secrets fresh through its own `file` SecretRefs sourced from `/srv/data/openclaw/auth/`, not a copy of that store.
- **Memory-search SQLite index.** Regenerable from the migrated workspace markdown; don't copy the index file itself — it lives in the config dir and is tied to the old install's paths.
- **Paired node** (the Mac; canvas/screen/location capabilities — spike-questions.md §6). Spike-specific pairing to a laptop that isn't part of this deploy. Re-pair a device fresh later if node capabilities are wanted — nothing to migrate here.
- **Web search (Brave + Gemini/`google` plugin)**, both wired up on `pickleclaw`. Beyond this plan's day-one `minimal` tool profile (browser/canvas/automation denied — see [Security decisions](#security-decisions)). "Bring everything over" shouldn't silently widen the attack surface; treat it as a fast-follow once the deploy is stable (see [Future](#future)), provisioned the same way `pickleclaw` did it (`file` SecretRefs, ClawHub plugin install + gateway restart for Brave).

### Workspace migration steps

1. Generate a **new** repo-scoped SSH deploy key (write access) for `github.com/technicalpickles/openclaw-workspace`, scoped to picklelab — don't reuse `pickleclaw`'s Mac-side private key material across hosts, same as every other per-service credential in this repo.
2. `deploy.sh` clones the repo into `/srv/data/openclaw/workspace/` (using that key) before the first `docker compose up -d`, then `chown -R` to the container's uid — instead of leaving OpenClaw to auto-init a fresh empty workspace repo.
3. Confirm nothing secret landed in the workspace files (`openclaw secrets audit` post-boot) — belt-and-suspenders, since [findings.md](../research/openclaw-homelab/findings.md#workspace-git-backup) already establishes structurally that the workspace can't hold auth material.
4. Ongoing backup is unchanged from `pickleclaw`'s pattern: `git add . && git commit && git push` from inside the workspace mount, now against the same repo from the new host.

### Include-file setup

`openclaw.tools.json5` and `openclaw.mcp.json5` aren't migrated *from* `pickleclaw` (it never had a Docker deploy to source them from) — they're authored fresh, but deliberately kept in the private `pickleclaw` repo rather than the public `picklehome` one. See [Where the include files actually live](#where-the-include-files-actually-live) for the full rationale and the symlink setup.

### Telegram bot cutover

Telegram allows only **one** active long-poller per bot token — running `pickleclaw`'s gateway and the picklelab deploy against the same token at once causes `409 Conflict` on both sides, not a graceful handoff. Sequence:

1. Stand up picklelab's OpenClaw fully (onboard, config, workspace clone, real secrets already in place) with `channels.telegram.enabled: false`, *before* touching the live bot.
2. Verify `just openclaw-status` (healthz/readyz + security audit) clean on that state.
3. In one short window: stop `pickleclaw`'s gateway (`systemctl --user stop openclaw-gateway` inside the OrbStack VM) → flip picklelab to `channels.telegram.enabled: true` via `config set` → confirm `openclaw channels status` on picklelab shows `running, connected, mode:polling`. Hot-reload is confirmed for `agents.defaults.*` config, not independently confirmed for channel enablement — budget for a `docker compose restart openclaw` in this window if the flip doesn't take effect live.
4. Message the bot from the allowlisted chat; confirm it responds. Only after this is confirmed working, move to decommissioning.

### Decommissioning `pickleclaw`

Once picklelab's OpenClaw is confirmed stable under real Telegram traffic (not just the cutover smoke test — give it a day or two):

- Stop and remove the OrbStack VM, retire the `openclaw-gateway` systemd user unit.
- `github.com/technicalpickles/openclaw-workspace` stays — it's picklelab's backup target now, not `pickleclaw`'s. Revoke `pickleclaw`'s old deploy key from that repo (`gh repo deploy-key delete`), leaving only picklelab's.
- The `pickleclaw` repo itself is **not just historical after this** — it keeps an active role as the private home of `openclaw.tools.json5`/`openclaw.mcp.json5` (see [Where the include files actually live](#where-the-include-files-actually-live)). Its setup notes, `provision.sh`, and vendor clone stay too, as research history — only the VM/spike instance gets torn down, not the repo.

## Justfile recipes

```just
deploy-openclaw host="picklelab":
    # service-env filter -> scp compose + includes + .env -> mkdir/chown /srv/data/openclaw ->
    # onboard-if-needed -> config set --batch-json (includes + channel + model registration) ->
    # systemd install + restart

# Status doubles as a self-test: systemd, loopback health, tailscale routing, security audit
openclaw-status host="picklelab":
    #!/usr/bin/env bash
    set -uo pipefail
    echo "==> systemd unit on {{host}}"
    ssh {{host}} "sudo systemctl status openclaw.service --no-pager" || true
    echo "==> loopback health on {{host}}"
    ssh {{host}} "curl -fsS http://127.0.0.1:18789/healthz -o /dev/null -w 'healthz HTTP %{http_code}\n'" || echo "loopback FAILED"
    ssh {{host}} "curl -fsS http://127.0.0.1:18789/readyz  -o /dev/null -w 'readyz  HTTP %{http_code}\n'" || true
    echo "==> tailscale routing (from this machine)"
    curl -fsS "https://${OPENCLAW_HOST:?}/healthz" -o /dev/null -w "HTTP %{http_code}\n" || echo "tailscale routing FAILED"
    echo "==> openclaw security audit"
    ssh {{host}} "docker exec openclaw openclaw security audit" || true

openclaw-logs host="picklelab" lines="50":
    ssh {{host}} "sudo journalctl -u openclaw.service --no-pager -n {{lines}}"

openclaw-logs-follow host="picklelab":
    ssh {{host}} "sudo journalctl -u openclaw.service -f"
```

`/healthz` localizes failures to systemd vs. tailscale vs. the image without manual diagnosis; `openclaw security audit` is the `homelab_07` "verify after mutation" step.

## Bootstrap order

1. Generate a new SSH deploy key (write access) for `github.com/technicalpickles/openclaw-workspace`, scoped to picklelab — see [Migration from pickleclaw](#migration-from-pickleclaw).
2. Author `openclaw.tools.json5` / `openclaw.mcp.json5` in the private `pickleclaw` repo and symlink them into `homelab/services/openclaw/` — see [Where the include files actually live](#where-the-include-files-actually-live).
3. Create the `OpenClaw` item in 1Password (`picklehome` vault) with the fields above — pull `ollama_api_key`, `openrouter_api_key`, and `telegram_bot_token` from `pickleclaw`'s existing values (no new bot, no new subscription keys) and reuse its existing chat-ID allowlist for `allowed_chat_ids`.
4. Add `OPENCLAW_*` / `OLLAMA_API_KEY` / `OPENROUTER_API_KEY` / `TELEGRAM_BOT_TOKEN` lines to `.env.template`; `just dotenv`.
5. Fill the pinned, already-validated model chain (`ollama-cloud/glm-5.2` primary, `glm-4.7` fallback, `gpt-oss:20b` heartbeat) into the bootstrap `config set --batch-json` step (see [Declarative config](#declarative-config)) — no catalog re-pick needed, this chain is already proven on `pickleclaw`.
6. Tailscale admin prereqs (same as other HTTPS services): HTTPS enabled, `tag:server` on picklelab, `openclaw` Service defined.
7. `just deploy-openclaw` — clones the workspace repo, runs onboarding once (idempotent, skipped on redeploy if the root config already exists), applies the `config set --batch-json` patch with `channels.telegram.enabled: false`, then `docker compose up -d`.
8. `just openclaw-status`: expect healthz/readyz OK + clean security audit, with the channel still not live.
9. Run the [Telegram bot cutover](#telegram-bot-cutover): stop `pickleclaw`'s gateway, flip picklelab to the real bot, confirm polling.
10. Message the bot from your allowlisted account; confirm a non-allowlisted account is rejected.
11. Smoke-test a multi-step task to confirm Ollama-cloud tool-calling on the new deploy (already proven on `pickleclaw` — this is a deploy-specific confirmation, not a fresh quality check).
12. Add the service to `homelab/services/README.md` + the project `CLAUDE.md` Homelab Services table.
13. After a day or two of stable real traffic, [decommission `pickleclaw`](#decommissioning-pickleclaw).

## Backups

`/srv/data/openclaw/` is picked up by the existing nightly restic job — covers config, memory/SQLite, channel credentials, and the auth-secret dir. Restore = stop service, restore dir, start. The `bin/` dir is reproducible from the committed `tools/manifest`, so it's restic-covered but not load-bearing.

## Update path

The image is pinned via **`OPENCLAW_IMAGE`** (the full image reference, e.g. `ghcr.io/openclaw/openclaw:2026.6.11`). To update: bump it in `.env`, `docker compose pull`, `docker compose up -d` to recreate. This depends on our `compose.yaml` declaring no `build:` key (see the compose sketch above) — pairing `image:` with `build:` makes `docker compose pull` ambiguous, which is why the official `scripts/docker/setup.sh` instead runs a plain `docker pull <full-ref>` before `docker compose up -d`. ClawDock's update flow doesn't apply here, since this deploy pulls a pre-built image rather than building from source. Add a `docker compose run --rm openclaw-cli doctor` step after recreate, for config-schema migrations — not just "confirm state intact." Full detail in [findings.md](../research/openclaw-homelab/findings.md#update-path-moving-image-versions).

**Now live-tested directly on picklelab (2026-07-01, throwaway instance, cleaned up after).** Built a real compose stack matching this exact shape (`image: ${OPENCLAW_IMAGE}`, no `build:` key, real bind mounts), brought it up on `2026.6.10`, set a distinctive config marker, bumped to `latest` (`2026.6.11`), ran `docker compose pull && docker compose up -d`. Confirmed: genuine container recreate, marker survived, `/healthz` 200 on the new version, `doctor` ran clean with no migration errors. The recipe works exactly as documented. Not covered: a real deployed instance with actual channel/session state (this used a throwaway dev config), and swap-window timing specifically on the J3455's weaker CPU.

The adjacent npm-install `update`→`doctor`→`gateway restart` flow *was also* live-tested on `pickleclaw` (2026-07-01, a real patch bump): config/memory/sessions/channel auth all survived, and a manual-recovery path (needed after an `EACCES` on that box's npm install) skipped an automatic "plugin sync" step that then had to be caught via `gateway status --deep`. That's a real gotcha for any install kind doing a manual recovery.

## Open questions

**Spike phase called done (2026-07-01).** One item is accepted as a residual unknown rather than pursued further:

- **RAM/CPU under real agentic load, with the browser tool actually invoked** *(spike §7)* — idle numbers are measured directly on the J3455 (see below); honestly testing under real load needs a working provider key, a live channel, and a sustained multi-step task — that's really "deploy it and watch," not another spike. Idle numbers already fit comfortably in the ~13 GB available headroom, and even the community's own worst-case estimate (~8 GB while browsing) fits; treat the real number as something to confirm after deploy, not a pre-deploy blocker.

**Live-tested on pickleclaw / locally / directly on picklelab (2026-07-01), substantially answered:**

- **Ollama-cloud tool-calling quality, latency, rate limits** *(spike §4)* — 3 agent turns exercising real `exec` tool calls against `ollama-cloud/glm-5.2`: 0 failures, correct results reported accurately. Latency 22–73s/turn; no throttling in a light back-to-back sample. Remaining gap: sustained always-on load and more complex multi-step tasks than simple shell commands.
- **`$include` exercised hands-on** *(spike §3)* — confirmed `config get` resolves an included file's contents correctly. Two new gotchas: default `config patch` merges rather than replaces an already-populated key (so retrofitting `$include` onto a live section needs the include file written first, or the key nulled/cleared, not a bare patch); OpenClaw explicitly blocks flattening a `$include`-owned key via `--replace-path` once one exists. Neither blocks the deploy's fresh-onboard architecture, since target keys start empty.
- **PATH override + live pickup** *(spike §6)* — confirmed on pickleclaw's real exec-tool `PATH` (not just the SSH shell's): dropped a new executable into an already-on-`PATH` dir while the gateway service stayed running, no restart, asked the agent to run it by name — worked first try. Answers the risky part of the tier-1 drop-in-bin-dir question (no OpenClaw-side restart or caching to fight); the narrower Docker-specific nuance (does a live `-v` bind-mount write propagate the same way) is unconfirmed but low-risk, since it's standard bind-mount behavior, not an OpenClaw quirk.
- **Image facts** *(spike §1)* — pulled and ran the real `ghcr.io/openclaw/openclaw` image locally (Docker Desktop on the Mac, not picklelab). Port `18789`, `/healthz`, uid 1000/`node`, `/home/node`, and the `node:24-bookworm-slim` base all confirmed directly from the image, not just the docs. Real image size **1.53 GB**, correcting the community "~20 GB" claim.
- **RAM budget and idle footprint, measured directly on picklelab** *(spike §7, mostly resolved)* — SSH'd into picklelab: 15Gi total RAM, **13Gi available** (not just "free"), existing ~9 services summing to ~1 GB via `docker stats`. Pulled and ran the real image directly on picklelab too (throwaway `--dev` container, cleaned up after, no disruption to real services): idle **~492 MiB RAM, ~1.35% CPU** (comparable to a Mac-based test's ~573 MiB), but **startup took ~2.3s vs. ~243ms on the Mac** — the weak Celeron actually showing up, though still fine for a service that boots once and stays up. Budget is comfortable; only remaining gap is under-real-agentic-load numbers (folded into the bullet above).
- **Allowlist policy** *(spike §5)* — live-tested with a real second sender: flipped `pickleclaw` to `dmPolicy: "allowlist"` with the owner's chat ID preserved (confirmed still working), then a friend's non-allowlisted account messaged the bot — hard reject confirmed, complete silence on the sender's end. Notable finding: the reject leaves **zero trace** on the operator's side either — no log line, no `channels status` counter change, nothing in `pairing list` — unlike Pairing's visibly-listable pairing requests. `pickleclaw` is staying on Allowlist going forward.
- **Docker pull/recreate mechanism** *(spike §9)* — live-tested directly on picklelab: real compose stack (this deploy's exact shape), version-bumped `2026.6.10` → `2026.6.11` via `docker compose pull && up -d`. Genuine recreate confirmed, a config marker survived, `doctor` ran clean post-swap. The documented recipe works exactly as described.

## Future

- **More tools / use cases.** Widen the tool profile as trust grows: read-only `just` checks → notifications → richer automation. Each widening is a config change, not a redeploy. First candidate: bring over `pickleclaw`'s web-search wiring (Gemini/`google` plugin as primary, Brave installed as standby) — left out of the day-one migration on purpose (see [Migration from pickleclaw](#migration-from-pickleclaw)), provisioned the same way (`file` SecretRefs, ClawHub install + gateway restart for Brave).
- **Other channels.** WhatsApp/Discord-webhook would add public ingress (Funnel, like `woodpecker`) — a separate design.
- **Rootless docker socket** for the real tool-sandbox, if a use case needs isolated execution — model on `woodpecker`'s `ci` user (uid 2000) rather than granting the root socket.
- **Exec node on picklelab (or another box)** as the "trust grows with capability" path for letting the agent act *outside* its container — on the host itself, or a machine with tools/network the container lacks. A node host's own `exec-approvals.json` is the host-side "narrow interface" `homelab_07` prefers (no `docker.sock`, authority audited host-side). Distinct from sandboxing, which contains rather than extends — see [findings §Sandbox vs nodes](../research/openclaw-homelab/findings.md#sandbox-vs-nodes-different-tools-small-overlap).
