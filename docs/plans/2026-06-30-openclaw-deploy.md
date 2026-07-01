# OpenClaw on picklelab — deployment design

Deploy OpenClaw (self-hosted AI gateway: chat → agent that can act) as a homelab service, following the standard Compose + systemd + Tailscale Services + 1Password pattern.

**Status:** design, pre-implementation. Depends on the laptop spike to confirm the values tagged *(spike)* below — see [`docs/research/openclaw-homelab/spike-questions.md`](../research/openclaw-homelab/spike-questions.md). Research backing this doc: [`docs/research/openclaw-homelab/findings.md`](../research/openclaw-homelab/findings.md).

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
        /srv/data/openclaw/  config/     workspace/   auth/      bin/  (tools on PATH)  includes/*.json5 (committed, ro)
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
| `openclaw.tools.json5` | **Committed** `$include` target for the `tools` section (profile, allow/deny, exec policy) |
| `openclaw.mcp.json5` | **Committed** `$include` target for the `mcp.servers` section |
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
      PATH: "/opt/tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"  # (spike) confirm PATH override
    ports:
      - "127.0.0.1:18789:18789"
    volumes:
      - config:/home/node/.openclaw                                            # writable — onboarding creates openclaw.json here
      - workspace:/home/node/.openclaw/workspace
      - auth:/home/node/.config/openclaw
      - ./openclaw.tools.json5:/home/node/.openclaw/includes/tools.json5:ro     # committed, $include target (spike: exercise hands-on)
      - ./openclaw.mcp.json5:/home/node/.openclaw/includes/mcp.json5:ro         # committed, $include target

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
2. **`$include` is the real mechanism for "config in git, state on disk."** A config value can be `{ $include: "./relative/path.json5" }` — resolved from **inside** the config directory, single-file includes replace the whole containing key. So instead of mounting one big file over the whole config, mount small **committed include files** at `/home/node/.openclaw/includes/*.json5` (read-only) and have the writable root file `$include` specific sections from them.

### Bootstrap sequence (per service, mirrors the official Docker manual flow)

```bash
# 1. Onboard once — creates the writable root config, auth store, gateway token
docker compose run --rm --no-deps --entrypoint node openclaw \
  dist/index.js onboard --mode local --no-install-daemon \
    --gateway-auth token --gateway-token-ref-env OPENCLAW_GATEWAY_TOKEN \
    --skip-ui --suppress-gateway-token-output

# 2. Wire the includes + provider/channel settings that aren't onboarding flags
docker compose run --rm --no-deps --entrypoint node openclaw \
  dist/index.js config set --batch-json '[
    {"path":"gateway.bind","value":"lan"},
    {"path":"tools","value":{"$include":"./includes/tools.json5"}},
    {"path":"mcp","value":{"$include":"./includes/mcp.json5"}},
    {"path":"channels.telegram.dmPolicy","value":"allowlist"},
    {"path":"channels.telegram.allowFrom","value":["<chat-id>"]},
    {"path":"agents.defaults.model.primary","value":"ollama-cloud/<pick-from-catalog>"},
    {"path":"agents.defaults.models","value":{"ollama-cloud/<pick-from-catalog>":{}}}
  ]'

# 3. Bring the service up for real
docker compose up -d
```

`deploy.sh` makes step 1 idempotent (skip if the root config already exists on the persisted volume) and re-runs step 2 on every deploy so config drift self-heals from the committed source.

### Committed include files

`openclaw.tools.json5` (mounted read-only at `includes/tools.json5`):

```json5
// Minimal blast radius: deny runtime/fs by default, ask on exec, no browser
{
  profile: "minimal",
  deny: ["browser", "canvas", "group:automation"],
  exec: { security: "deny", ask: "always" },
}
```

`openclaw.mcp.json5` (mounted read-only at `includes/mcp.json5`):

```json5
{
  servers: {
    // example: a read-only homelab MCP, or community servers; add per docs/cli/mcp
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
- *(spike)* `$include` and the onboard-then-patch sequence above are source-derived, not yet exercised hands-on by any spike — top candidate for the next validation pass (see `spike-questions.md` §3).

## Tools / extension model

Two paths, neither requires rebuilding the image (full rationale in [findings.md](../research/openclaw-homelab/findings.md#mounts-version-control-and-adding-tools)):

1. **Drop-in CLIs (`gogcli`, etc.)** — `/srv/data/openclaw/bin` is bind-mounted to `/opt/tools` (`OPENCLAW_EXTRA_MOUNTS`, official) and prepended to `PATH`. Add a tool = copy the binary in; the agent's next shell call picks it up, no restart. Base is Debian/glibc so static/Go binaries run as-is. A committed `homelab/services/openclaw/tools/manifest` (name → source URL/version) documents what should be there; `deploy.sh` fetches them onto the host. Binaries themselves stay out of git.
2. **MCP servers (structured tools)** — declared in `mcp.servers` (committed, via the `openclaw.mcp.json5` include). stdio servers run in-process; HTTP/SSE servers run as **sidecar containers**. Iterating a sidecar restarts only the sidecar; registering a *new* server needs a gateway **reload** (`openclaw mcp reload`), not an image rebuild.
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
| `gateway_token` | `openssl rand -hex 32` |
| `ollama_api_key` | from `ollama.com/settings/keys` |
| `openrouter_api_key` | from `openrouter.ai/keys` — embeddings only, chat/heartbeat stay on Ollama Cloud |
| `telegram_bot_token` | from @BotFather |
| `allowed_chat_ids` | your Telegram numeric chat ID(s), comma-separated |

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

1. Create the bot in @BotFather; note the token. Get your numeric chat ID.
2. Create the `OpenClaw` item in 1Password (`picklehome` vault) with the fields above.
3. Add `OPENCLAW_*` / `OLLAMA_API_KEY` / `OPENROUTER_API_KEY` / `TELEGRAM_BOT_TOKEN` lines to `.env.template`; `just dotenv`.
4. Pick the Ollama model from the live catalog (`openclaw models list --provider ollama-cloud`); fill it into the bootstrap `config set --batch-json` step (see [Declarative config](#declarative-config)) and confirm the subscription tier covers expected volume.
5. Tailscale admin prereqs (same as other HTTPS services): HTTPS enabled, `tag:server` on picklelab, `openclaw` Service defined.
6. `just deploy-openclaw` — runs onboarding once (idempotent, skipped on redeploy if the root config already exists), then applies the `config set --batch-json` patch, then `docker compose up -d`.
7. `just openclaw-status`: expect healthz/readyz OK + clean security audit.
8. Message the bot from your allowlisted account; confirm a non-allowlisted account is rejected.
9. Smoke-test a multi-step task to validate Ollama-cloud tool-calling (now that the endpoint/wiring bug is fixed, this actually tests model quality rather than a config error).
10. Add the service to `homelab/services/README.md` + the project `CLAUDE.md` Homelab Services table.

## Backups

`/srv/data/openclaw/` is picked up by the existing nightly restic job — covers config, memory/SQLite, channel credentials, and the auth-secret dir. Restore = stop service, restore dir, start. The `bin/` dir is reproducible from the committed `tools/manifest`, so it's restic-covered but not load-bearing.

## Update path

The image is pinned via **`OPENCLAW_IMAGE`** (the full image reference, e.g. `ghcr.io/openclaw/openclaw:2026.6.11`). To update: bump it in `.env`, `docker compose pull`, `docker compose up -d` to recreate. This depends on our `compose.yaml` declaring no `build:` key (see the compose sketch above) — pairing `image:` with `build:` makes `docker compose pull` ambiguous, which is why the official `scripts/docker/setup.sh` instead runs a plain `docker pull <full-ref>` before `docker compose up -d`. ClawDock's update flow doesn't apply here, since this deploy pulls a pre-built image rather than building from source. Add a `docker compose run --rm openclaw-cli doctor` step after recreate, for config-schema migrations — not just "confirm state intact." Full detail in [findings.md](../research/openclaw-homelab/findings.md#update-path-moving-image-versions).

Not yet live-tested on picklelab (spike §9). The adjacent npm-install `update`→`doctor`→`gateway restart` flow *was* live-tested on `pickleclaw` (2026-07-01, a real patch bump): config/memory/sessions/channel auth all survived, and a manual-recovery path (needed after an `EACCES` on that box's npm install) skipped an automatic "plugin sync" step that then had to be caught via `gateway status --deep`. That's a real gotcha for any install kind doing a manual recovery, but doesn't stand in for testing the Docker `docker pull` + `up -d` path itself.

## Open questions

Need the actual spike, not just source reading (see `spike-questions.md`):

- **Docker pull/recreate mechanism itself** *(spike §9)* — see [Update path](#update-path) above. Still requires an actual `docker compose pull && up -d` version-bump test on picklelab; not resolvable via more pickleclaw research.
- **RAM/CPU under real agentic load, with the browser tool actually invoked** *(spike §7, last remaining gap)* — idle numbers are now measured directly on the J3455 (see below); what's left is a working model actually driving tool calls on that hardware, not an unconfigured `--dev` instance.

**Live-tested on pickleclaw / locally / directly on picklelab (2026-07-01), substantially answered:**

- **Ollama-cloud tool-calling quality, latency, rate limits** *(spike §4)* — 3 agent turns exercising real `exec` tool calls against `ollama-cloud/glm-5.2`: 0 failures, correct results reported accurately. Latency 22–73s/turn; no throttling in a light back-to-back sample. Remaining gap: sustained always-on load and more complex multi-step tasks than simple shell commands.
- **`$include` exercised hands-on** *(spike §3)* — confirmed `config get` resolves an included file's contents correctly. Two new gotchas: default `config patch` merges rather than replaces an already-populated key (so retrofitting `$include` onto a live section needs the include file written first, or the key nulled/cleared, not a bare patch); OpenClaw explicitly blocks flattening a `$include`-owned key via `--replace-path` once one exists. Neither blocks the deploy's fresh-onboard architecture, since target keys start empty.
- **PATH override + live pickup** *(spike §6)* — confirmed on pickleclaw's real exec-tool `PATH` (not just the SSH shell's): dropped a new executable into an already-on-`PATH` dir while the gateway service stayed running, no restart, asked the agent to run it by name — worked first try. Answers the risky part of the tier-1 drop-in-bin-dir question (no OpenClaw-side restart or caching to fight); the narrower Docker-specific nuance (does a live `-v` bind-mount write propagate the same way) is unconfirmed but low-risk, since it's standard bind-mount behavior, not an OpenClaw quirk.
- **Image facts** *(spike §1)* — pulled and ran the real `ghcr.io/openclaw/openclaw` image locally (Docker Desktop on the Mac, not picklelab). Port `18789`, `/healthz`, uid 1000/`node`, `/home/node`, and the `node:24-bookworm-slim` base all confirmed directly from the image, not just the docs. Real image size **1.53 GB**, correcting the community "~20 GB" claim.
- **RAM budget and idle footprint, measured directly on picklelab** *(spike §7, mostly resolved)* — SSH'd into picklelab: 15Gi total RAM, **13Gi available** (not just "free"), existing ~9 services summing to ~1 GB via `docker stats`. Pulled and ran the real image directly on picklelab too (throwaway `--dev` container, cleaned up after, no disruption to real services): idle **~492 MiB RAM, ~1.35% CPU** (comparable to a Mac-based test's ~573 MiB), but **startup took ~2.3s vs. ~243ms on the Mac** — the weak Celeron actually showing up, though still fine for a service that boots once and stays up. Budget is comfortable; only remaining gap is under-real-agentic-load numbers (folded into the bullet above).
- **Allowlist policy** *(spike §5)* — live-tested with a real second sender: flipped `pickleclaw` to `dmPolicy: "allowlist"` with the owner's chat ID preserved (confirmed still working), then a friend's non-allowlisted account messaged the bot — hard reject confirmed, complete silence on the sender's end. Notable finding: the reject leaves **zero trace** on the operator's side either — no log line, no `channels status` counter change, nothing in `pairing list` — unlike Pairing's visibly-listable pairing requests. `pickleclaw` is staying on Allowlist going forward.

## Future

- **More tools / use cases.** Widen the tool profile as trust grows: read-only `just` checks → notifications → richer automation. Each widening is a config change, not a redeploy.
- **Other channels.** WhatsApp/Discord-webhook would add public ingress (Funnel, like `woodpecker`) — a separate design.
- **Rootless docker socket** for the real tool-sandbox, if a use case needs isolated execution — model on `woodpecker`'s `ci` user (uid 2000) rather than granting the root socket.
- **Exec node on picklelab (or another box)** as the "trust grows with capability" path for letting the agent act *outside* its container — on the host itself, or a machine with tools/network the container lacks. A node host's own `exec-approvals.json` is the host-side "narrow interface" `homelab_07` prefers (no `docker.sock`, authority audited host-side). Distinct from sandboxing, which contains rather than extends — see [findings §Sandbox vs nodes](../research/openclaw-homelab/findings.md#sandbox-vs-nodes-different-tools-small-overlap).
