# OpenClaw on picklelab — deployment design

Deploy OpenClaw (self-hosted AI gateway: chat → agent that can act) as a homelab service, following the standard Compose + systemd + Tailscale Services + 1Password pattern.

**Status:** design, pre-implementation. Depends on the laptop spike to confirm the values tagged *(spike)* below — see [`docs/research/openclaw-homelab/spike-questions.md`](../research/openclaw-homelab/spike-questions.md). Research backing this doc: [`docs/research/openclaw-homelab/findings.md`](../research/openclaw-homelab/findings.md).

**Update (2026-06-30, same day):** cross-checked this doc's `(spike)`-tagged guesses against the running `pickleclaw` spike and a source read of its pinned `vendor/openclaw` clone (tag `v2026.6.10`). Several were wrong, not just unconfirmed — the config mount strategy, the Ollama provider wiring (would have broken tool calling), the bind env var/value, and the DM-policy config path. Corrected below; see `findings.md` and `spike-questions.md` for the full evidence trail.

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
    image: ghcr.io/openclaw/openclaw:${OPENCLAW_IMAGE_TAG:?pin a version}   # (spike) pin a real tag, not latest
    restart: unless-stopped
    user: "1000:1000"                      # image default (node); data dir isn't shared, so 1000 is fine
    environment:
      OPENCLAW_GATEWAY_BIND: lan            # NOT loopback — see "Port & bind topology" below for why
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:?required}
      OLLAMA_API_KEY: ${OLLAMA_API_KEY:?required}          # ollama-cloud is a built-in provider, no custom config needed
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

**Correction (source-verified, `docs/install/docker.md` + `src/config/gateway-control-ui-origins.ts`): the app-internal bind mode should be `lan`, not `loopback`, for a Docker deploy.** Docker's default bridge networking means traffic from a published port (`-p 18789:18789`) arrives on the container's `eth0`, not its loopback interface — a gateway bound to `loopback` *inside* the container would be unreachable even from the host, breaking the whole deploy. `scripts/docker/setup.sh` defaults to `OPENCLAW_GATEWAY_BIND=lan` for exactly this reason (host access still works because Docker's port-publish only routes `eth0` traffic, and Docker doesn't publish `lo`). This is *not* a security regression: **the real loopback restriction is the compose port mapping** (`127.0.0.1:18789:18789`, host-side) — the app can bind `0.0.0.0` internally and still be unreachable from outside picklelab, because nothing besides the host's own `127.0.0.1` is ever published. `tailscaled`'s local proxy reaches it via that same host-side loopback binding; `tailscale serve` fronts it as `https://openclaw.tail2023b7.ts.net`.

## Declarative config

**Corrected architecture (source-verified, `v2026.6.10`).** The original single-file, fully-read-only-mounted `openclaw.config.json5` doesn't match how OpenClaw actually manages config, on two counts:

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

### Ollama cloud — corrected, not just confirmed

**The original plan's Ollama config was wrong and would likely have broken tool calling.** `ollama-cloud` is a **first-class built-in provider** (`docs/providers/ollama-cloud.md`) — there's no custom `models.providers` entry to write at all:

- Auth: `OLLAMA_API_KEY` env var (already in `.env`) — no `baseUrl`/`api` config needed.
- **Do not point anything at `https://ollama.com/v1`.** The provider uses Ollama's native `/api/chat`, base URL `https://ollama.com` (no `/v1`). The docs are explicit: *"Do not use the `/v1` OpenAI-compatible URL... This breaks tool calling and models may output raw tool JSON as plain text."* The original plan's `baseUrl: "https://ollama.com/v1", api: "openai-completions"` snippet would have hit exactly this failure mode — and it would have looked like "this model is bad at tool calling" (spike §4's biggest worry) when the real bug was the endpoint shape.
- Model refs: `ollama-cloud/<id>` (e.g. `ollama-cloud/kimi-k2.6`); list the live hosted catalog with `openclaw models list --provider ollama-cloud`.
- Still register the model in **both** `agents.defaults.model.primary` and `agents.defaults.models` (see the bootstrap `config set` above) — every official custom-provider example in `config-tools.md` pairs these, and pickleclaw independently hit the silent-fallback-to-an-expensive-model failure mode when this pairing is skipped.

### Channel front door — corrected key path

The config path is **per-channel**, not a global `session.dm.*` key (source-confirmed, `src/config/types.channel-messaging-common.ts`/`types.base.ts`): `channels.telegram.dmPolicy: "allowlist"` + `channels.telegram.allowFrom: [...]` — see the bootstrap `config set` above. `session.dmScope` is a real but unrelated setting (session isolation, not the allow/deny policy).

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
| Egress | Outbound to `api.telegram.org` + `ollama.com` (+ MCP endpoints). Note in README; tighten later if warranted |

## Secrets

### 1Password item: `picklehome/OpenClaw`

| field | value |
|-------|-------|
| `host` | `openclaw.tail2023b7.ts.net` |
| `gateway_token` | `openssl rand -hex 32` |
| `ollama_api_key` | from `ollama.com/settings/keys` |
| `telegram_bot_token` | from @BotFather |
| `allowed_chat_ids` | your Telegram numeric chat ID(s), comma-separated |

### `.env.template` additions

```
# OPENCLAW_HOST: Tailscale Services hostname
OPENCLAW_HOST={{ op://picklehome/OpenClaw/host }}
# OPENCLAW_GATEWAY_TOKEN: control-UI/API bearer token
OPENCLAW_GATEWAY_TOKEN={{ op://picklehome/OpenClaw/gateway_token }}
# OLLAMA_API_KEY: Ollama cloud subscription key
OLLAMA_API_KEY={{ op://picklehome/OpenClaw/ollama_api_key }}
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
TELEGRAM_BOT_TOKEN
OPENCLAW_ALLOWED_CHAT_IDS
OPENCLAW_IMAGE_TAG
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
3. Add `OPENCLAW_*` / `OLLAMA_API_KEY` / `TELEGRAM_BOT_TOKEN` lines to `.env.template`; `just dotenv`.
4. Pick the Ollama model from the live catalog (`openclaw models list --provider ollama-cloud`); fill it into the bootstrap `config set --batch-json` step (see [Declarative config](#declarative-config)) and confirm the subscription tier covers expected volume.
5. Tailscale admin prereqs (same as other HTTPS services): HTTPS enabled, `tag:server` on picklelab, `openclaw` Service defined.
6. `just deploy-openclaw` — runs onboarding once (idempotent, skipped on redeploy if the root config already exists), then applies the `config set --batch-json` patch, then `docker compose up -d`.
7. `just openclaw-status`: expect healthz/readyz OK + clean security audit.
8. Message the bot from your allowlisted account; confirm a non-allowlisted account is rejected.
9. Smoke-test a multi-step task to validate Ollama-cloud tool-calling (now that the endpoint/wiring bug is fixed, this actually tests model quality rather than a config error).
10. Add the service to `homelab/services/README.md` + the project `CLAUDE.md` Homelab Services table.

## Backups

`/srv/data/openclaw/` is picked up by the existing nightly restic job — covers config, memory/SQLite, channel credentials, and the auth-secret dir. Restore = stop service, restore dir, start. The `bin/` dir is reproducible from the committed `tools/manifest`, so it's restic-covered but not load-bearing.

## Risks & open questions

Resolved via source read (`v2026.6.10`) since the last pass — no longer open, kept here for the record:

- ~~Config key names~~ — `channels.<channel>.dmPolicy`/`allowFrom` (not `session.dm.*`), `tools.*` shape, `gateway.bind` (`OPENCLAW_GATEWAY_BIND` env, value `lan` for Docker) all confirmed against source. Config **filename** (`openclaw.json`) confirmed via pickleclaw.
- ~~Onboarding vs. skip~~ — `OPENCLAW_SKIP_ONBOARDING` is for re-running setup against an *already-onboarded* persisted volume, not initial bring-up; a fresh deploy always onboards once (scripted, non-interactive) then applies config patches. See the corrected bootstrap sequence above.
- ~~Ollama provider wiring~~ — built-in `ollama-cloud` provider, native API, not a custom OpenAI-compatible entry hitting `/v1` (which would have broken tool calling).

Still open — need the actual spike, not just source reading (see `spike-questions.md`):

- **`$include` exercised hands-on** *(spike §3)* — the committed-include-file architecture above is source-derived, not yet run against a real instance. Confirm a read-only-mounted include actually resolves, and that `config set --batch-json` for the pointing keys works as expected.
- **PATH override + live pickup** *(spike §6)* — the tier-1 drop-in story assumes `PATH` is env-overridable and a dropped binary is picked up without restart. Confirm; if PATH isn't overridable, fall back to mounting onto an existing PATH dir.
- **Runtime RAM** *(spike §7)* — budget against the 16 GB box; confirm browser-off lands near ~4 GB and idle is modest on the J3455.
- **Ollama-cloud tool-calling quality, latency, rate limits** *(spike §4)* — the chosen model must reliably emit tool calls, *and* be strong enough to resist tool-misuse; the cheap-model-with-tools tension is real. These are inherently live-test facts, not something a docs/source read can settle — and now that the endpoint bug is fixed, a live test actually measures model quality instead of a config error.
- **Allowlist policy itself** *(spike §5)* — only the Pairing flow has been exercised hands-on (on pickleclaw); confirm a hard-reject for a non-allowlisted sender with `dmPolicy: "allowlist"` actually configured.

## Future

- **More tools / use cases.** Widen the tool profile as trust grows: read-only `just` checks → notifications → richer automation. Each widening is a config change, not a redeploy.
- **Other channels.** WhatsApp/Discord-webhook would add public ingress (Funnel, like `woodpecker`) — a separate design.
- **Rootless docker socket** for the real tool-sandbox, if a use case needs isolated execution — model on `woodpecker`'s `ci` user (uid 2000) rather than granting the root socket.
- **Exec node on picklelab (or another box)** as the "trust grows with capability" path for letting the agent act *outside* its container — on the host itself, or a machine with tools/network the container lacks. A node host's own `exec-approvals.json` is the host-side "narrow interface" `homelab_07` prefers (no `docker.sock`, authority audited host-side). Distinct from sandboxing, which contains rather than extends — see [findings §Sandbox vs nodes](../research/openclaw-homelab/findings.md#sandbox-vs-nodes-different-tools-small-overlap).
