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
                                  user node (uid 1000), bind 127.0.0.1:18789
                                           |
                  +------------------------+------------------------+
                  v            v             v                      v
        /srv/data/openclaw/  config/     workspace/   auth/      bin/  (tools on PATH)
                  |            |             |          |
              restic-backed  (config + memory + tokens, credentials/, sessions/)
                                           |
                          Ollama cloud  ──>  https://ollama.com/v1  (outbound, ${OLLAMA_API_KEY})
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
| `deploy.sh` | scp + `mkdir -p`/`chown` data dirs + systemd install + `tailscale serve` |
| `.env.vars` | Var names this service needs (filtered from master `.env`) |
| `openclaw.config.json5` | **Committed** declarative config (providers, channel policy, tool profile, MCP servers) with secrets as `${ENV}` refs |
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
      OPENCLAW_SKIP_ONBOARDING: "1"        # boot from the committed config, not the interactive wizard
      OPENCLAW_BIND: loopback              # (spike) confirm the exact bind-mode key; force loopback, not lan
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN:?required}
      OLLAMA_API_KEY: ${OLLAMA_API_KEY:?required}
      TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:?required}
      OPENCLAW_ALLOWED_CHAT_IDS: ${OPENCLAW_ALLOWED_CHAT_IDS:?required}
      OPENCLAW_EXTRA_MOUNTS: "/srv/data/openclaw/bin:/opt/tools:ro"   # tools dir, read-only
      PATH: "/opt/tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"  # (spike) confirm PATH override
    ports:
      - "127.0.0.1:18789:18789"
    volumes:
      - config:/home/node/.openclaw
      - workspace:/home/node/.openclaw/workspace
      - auth:/home/node/.config/openclaw
      - ./openclaw.config.json5:/home/node/.openclaw/openclaw.json5:ro   # (spike) confirm config filename

volumes:
  config:
  workspace:
  auth:
```

### compose.picklelab.yaml

```yaml
services:
  openclaw:
    volumes:
      - /srv/data/openclaw/config:/home/node/.openclaw
      - /srv/data/openclaw/workspace:/home/node/.openclaw/workspace
      - /srv/data/openclaw/auth:/home/node/.config/openclaw
      - /srv/data/openclaw/bin:/opt/tools:ro
      - ./openclaw.config.json5:/home/node/.openclaw/openclaw.json5:ro
```

### Port & bind topology

Single HTTP port **`18789`** (UI + REST + webhooks), mapped to `127.0.0.1:18789`. OpenClaw's own default is `lan` bind mode for host-browser convenience; we **force loopback** (its security doc recommends loopback + "prefer Tailscale Serve"). From outside picklelab the port is unreachable directly — only `tailscaled`'s local proxy reaches it. `tailscale serve` fronts it as `https://openclaw.tail2023b7.ts.net`.

## Declarative config (`openclaw.config.json5`)

Committed to the repo with secrets as `${ENV}` refs (OpenClaw resolves `"${VAR}"` template syntax). This is the source of truth; the live copy in the config mount is what the container reads.

```json5
{
  // Off-box inference: Ollama cloud as an OpenAI-compatible provider
  models: { providers: { "ollama-cloud": {
    baseUrl: "https://ollama.com/v1",     // the "narrow network trust decision" — allowlists this origin
    apiKey: "${OLLAMA_API_KEY}",
    api: "openai-completions",
    models: [{ id: "<pick-from-catalog>", contextWindow: 128000, maxTokens: 32000 }]  // (spike) pick model
  } } },

  // Front door: only our chat IDs may drive the agent
  session: { dm: { policy: "allowlist", allow: "${OPENCLAW_ALLOWED_CHAT_IDS}" } },  // (spike) confirm exact keys

  // Minimal blast radius: deny runtime/fs by default, ask on exec, no browser
  tools: {
    profile: "minimal",
    deny: ["browser", "canvas", "group:automation"],
    exec: { security: "deny", ask: "always" },
  },

  // Structured ecosystem tools (tier 2) — declarative, committed
  mcp: { servers: {
    // example: a read-only homelab MCP, or community servers; add per docs/cli/mcp
  } },
}
```

Notes:
- **Gateway token** and **bot token** stay in env (`.env`), never in the committed file.
- The config dir intermingles this config file with memory/tokens/credentials, so the *whole* `/srv/data/openclaw/config` is sensitive and restic-backed; the committed `.json5` is re-applied (read-only mount) on every deploy as source-of-truth.
- *(spike §3)* confirm the real config filename and whether `session.dm`/`tools` keys are env-overridable (which could let us drop some of the committed file).

## Tools / extension model

Two paths, neither requires rebuilding the image (full rationale in [findings.md](../research/openclaw-homelab/findings.md#mounts-version-control-and-adding-tools)):

1. **Drop-in CLIs (`gogcli`, etc.)** — `/srv/data/openclaw/bin` is bind-mounted to `/opt/tools` (`OPENCLAW_EXTRA_MOUNTS`, official) and prepended to `PATH`. Add a tool = copy the binary in; the agent's next shell call picks it up, no restart. Base is Debian/glibc so static/Go binaries run as-is. A committed `homelab/services/openclaw/tools/manifest` (name → source URL/version) documents what should be there; `deploy.sh` fetches them onto the host. Binaries themselves stay out of git.
2. **MCP servers (structured tools)** — declared in `mcp.servers` (committed). stdio servers run in-process; HTTP/SSE servers run as **sidecar containers**. Iterating a sidecar restarts only the sidecar; registering a *new* server needs a gateway **reload** (`openclaw mcp reload`), not an image rebuild.

Stable system packages only (e.g. `git`) go via `OPENCLAW_IMAGE_APT_PACKAGES` at build time — not the iteration path.

## Security decisions

Maps the [official security model](../research/openclaw-homelab/findings.md#security--sandbox-model-from-the-official-gatewaysecurity--gatewaysandboxing-docs) onto `homelab_07`:

| Concern | Decision |
|---|---|
| Who can reach the UI | Tailscale Services (loopback bind) + **gateway token** |
| Who can drive the agent | Channel **allowlist** (our chat IDs); default Pairing is already not-open |
| Shell/fs access | Default-deny (`group:runtime`/`group:fs` off, `exec: deny/ask:always`); widen per use case |
| Tool sandbox vs. docker.sock | **No socket.** Gateway is containerized; rely on tool policy, not the in-container Docker sandbox. Revisit a rootless socket (woodpecker-style) only if a real need appears |
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
    # service-env filter -> scp compose + config + .env -> mkdir/chown /srv/data/openclaw -> systemd install + restart

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
4. Pick the Ollama model + subscription tier; fill `models[].id` in `openclaw.config.json5`.
5. Tailscale admin prereqs (same as other HTTPS services): HTTPS enabled, `tag:server` on picklelab, `openclaw` Service defined.
6. `just deploy-openclaw`.
7. `just openclaw-status`: expect healthz/readyz OK + clean security audit.
8. Message the bot from your allowlisted account; confirm a non-allowlisted account is rejected.
9. Smoke-test a multi-step task to validate Ollama-cloud tool-calling.
10. Add the service to `homelab/services/README.md` + the project `CLAUDE.md` Homelab Services table.

## Backups

`/srv/data/openclaw/` is picked up by the existing nightly restic job — covers config, memory/SQLite, channel credentials, and the auth-secret dir. Restore = stop service, restore dir, start. The `bin/` dir is reproducible from the committed `tools/manifest`, so it's restic-covered but not load-bearing.

## Risks & open questions

All resolved by the spike before implementation (see `spike-questions.md`):

- **Config key names** *(spike §3)* — `session.dm.policy`/`allow`, `tools.*`, bind-mode key, and the config **filename** are inferred from the docs' shapes; confirm exact spellings against a real instance before trusting the committed `.json5`.
- **PATH override + live pickup** *(spike §6)* — the tier-1 drop-in story assumes `PATH` is env-overridable and a dropped binary is picked up without restart. Confirm; if PATH isn't overridable, fall back to mounting onto an existing PATH dir.
- **Runtime RAM** *(spike §7)* — budget against the 16 GB box; confirm browser-off lands near ~4 GB and idle is modest on the J3455.
- **Ollama-cloud tool-calling quality** *(spike §4)* — the chosen model must reliably emit tool calls, *and* be strong enough to resist tool-misuse; the cheap-model-with-tools tension is real.
- **Onboarding vs. skip** — assumes `OPENCLAW_SKIP_ONBOARDING=1` + committed config boots cleanly; if onboarding is mandatory for channel pairing, bootstrap runs it once interactively (like `obsidian-sync`'s auth) then captures the config.

## Future

- **More tools / use cases.** Widen the tool profile as trust grows: read-only `just` checks → notifications → richer automation. Each widening is a config change, not a redeploy.
- **Other channels.** WhatsApp/Discord-webhook would add public ingress (Funnel, like `woodpecker`) — a separate design.
- **Rootless docker socket** for the real tool-sandbox, if a use case needs isolated execution — model on `woodpecker`'s `ci` user (uid 2000) rather than granting the root socket.
