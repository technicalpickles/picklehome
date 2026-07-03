# OpenClaw

Self-hosted OpenClaw gateway (chat -> agent that can act) on picklelab. Phone-reachable via Telegram, control UI over Tailscale. A sibling to `brineworks-agent` / `second-brain-agent`: trusted-but-shaped, deployed on purpose.

Full design rationale: [`docs/plans/2026-06-30-openclaw-deploy.md`](../../../docs/plans/2026-06-30-openclaw-deploy.md). This README is setup/operational reference only — see that doc for the "why".

This deploy is a **migration** from `pickleclaw` (an OrbStack-VM spike on the Mac), not a from-scratch bring-up: it carries over the workspace/memory repo, the Telegram bot identity, and the validated model chain. See the design doc's "Migration from pickleclaw" section.

## Prerequisites (one-time)

### Tailscale admin

- `tag:server` applied to picklelab (same as the other HTTPS services).
- HTTPS enabled on the tailnet.
- **Define the Service before the first deploy** — `tailscale serve --service=svc:openclaw` on the host has nothing to attach a pending-host-approval to until the Service exists in the admin console; it won't create one for you. At [Tailscale Services](https://login.tailscale.com/admin/services), click "Define Service": Name `openclaw`, Ports `443`. Same gotcha as `taskchampion`'s original setup — see its README/impl doc if this needs re-deriving later.

### 1Password item: `picklehome/OpenClaw`

**Don't copy `pickleclaw`'s existing keys into this item — reference them directly.** Only genuinely new, picklelab-specific values live here:

| field | value |
|-------|-------|
| `host` | `openclaw.tail2023b7.ts.net` |
| `gateway_token` | `openssl rand -hex 32` — picklelab's own, not shared with `pickleclaw` |
| `allowed_chat_ids` | same numeric Telegram chat ID(s) `pickleclaw` already allowlists, comma-separated |

`ollama_api_key`, `openrouter_api_key`, and `telegram_bot_token` stay in their existing items (same Ollama Cloud subscription, same OpenRouter key, same Telegram bot as `pickleclaw` — no new item, no duplicate copy to keep in sync).

Add to `.env.template`:

```
OPENCLAW_HOST={{ op://picklehome/OpenClaw/host }}
OPENCLAW_GATEWAY_TOKEN={{ op://picklehome/OpenClaw/gateway_token }}
OPENCLAW_ALLOWED_CHAT_IDS={{ op://picklehome/OpenClaw/allowed_chat_ids }}
OLLAMA_API_KEY={{ op://<pickleclaw's existing Ollama item path> }}
OPENROUTER_API_KEY={{ op://<pickleclaw's existing OpenRouter item path> }}
TELEGRAM_BOT_TOKEN={{ op://<pickleclaw's existing Telegram bot item path> }}
```

`OPENCLAW_IMAGE` isn't a secret — set it directly in `.env` (or `.env.template` as a plain default), e.g. `OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:2026.6.11`.

### Workspace deploy key (one-time)

The workspace (`github.com/technicalpickles/openclaw-workspace` — `AGENTS.md`, `SOUL.md`, `memory/*.md`, etc., already `pickleclaw`'s workspace repo) is cloned host-side by `deploy.sh` using a scoped **write** deploy key, same mechanism as `brineworks-agent`'s `WORKSPACE_DEPLOY_KEY_B64` — different var name since each service's key is scoped to a different repo.

1. Generate an ed25519 keypair (no passphrase):
   ```bash
   ssh-keygen -t ed25519 -f openclaw-workspace-deploy -C "openclaw picklelab workspace deploy key" -N ""
   ```
2. Add the **public** key to `technicalpickles/openclaw-workspace` -> Settings -> Deploy keys, **with "Allow write access" checked**. Don't reuse `pickleclaw`'s Mac-side key material — this is picklelab's own key, same as every other per-service credential in this repo.
3. Store the private key in the `picklehome` 1Password vault as an SSH-key item titled `OpenClaw Workspace`, with a **custom text field** `workspace_deploy_key_b64` holding the **single-line base64** of the private key. If created via `op item create` with a JSON template (fields array), the custom field lands top-level; if added afterward through the 1Password app UI (the only way to edit an existing SSH-key item's fields via the app, since the CLI can't), it nests under an "add more" section instead — check which with `op item get "OpenClaw Workspace" --vault picklehome` and adjust the ref path accordingly. To derive the base64 by hand:
   ```bash
   op read 'op://picklehome/OpenClaw Workspace/private key' | base64 | tr -d '\n' | pbcopy
   ```
   (`tr -d '\n'` matters — macOS `base64` wraps at 76 cols, and a multi-line value breaks `scripts/service-env`'s line-based filter.)
4. Add to `.env.template`:
   ```
   OPENCLAW_WORKSPACE_DEPLOY_KEY_B64={{ op://picklehome/OpenClaw Workspace/workspace_deploy_key_b64 }}
   ```
   Until the ref exists it's skipped silently and `deploy.sh` degrades to an empty workspace with a warning. Delete the local keypair once it's in 1Password and on GitHub.

### Include-file setup (one-time, per dev machine)

`openclaw.tools.json5` (tool policy) and `openclaw.mcp.json5` (MCP server config) aren't committed to this **public** repo — the MCP file would leak real server names/commands. Both live in the private `pickleclaw` repo instead, symlinked in:

```bash
ln -sf ~/github.com/technicalpickles/pickleclaw/openclaw-config/tools.json5 \
  homelab/services/openclaw/openclaw.tools.json5
ln -sf ~/github.com/technicalpickles/pickleclaw/openclaw-config/mcp.json5 \
  homelab/services/openclaw/openclaw.mcp.json5
```

`deploy.sh` runs from the Mac, where `pickleclaw` is already cloned with your own GitHub access — `git pull` it before deploying, same as any other dependency.

## First-time Setup

```bash
just dotenv              # pull secrets from 1Password
just deploy-openclaw
```

`deploy.sh` creates the `/srv/data/openclaw` directories, clones the workspace repo, runs `onboard` once (idempotent — skipped if the root config already exists), applies the declarative `config set --batch-json` (includes, model chain, channel policy — every deploy, self-healing), and brings the container up with `channels.telegram.enabled: false`.

Verify: `just openclaw-status` — expect healthz/readyz OK and a clean `openclaw security audit`, with the Telegram channel still disabled.

## Telegram bot cutover

Telegram allows only **one** active long-poller per bot token — running `pickleclaw`'s gateway and picklelab's at once causes `409 Conflict` on both. Do this only after `just openclaw-status` is clean:

1. Stop `pickleclaw`'s gateway: `systemctl --user stop openclaw-gateway` inside the OrbStack VM.
2. Flip picklelab's channel on:
   ```bash
   ssh picklelab "cd /opt/homelab/homelab/services/openclaw && \
     docker compose -f compose.yaml -f compose.picklelab.yaml run --rm --no-deps --entrypoint node openclaw \
       dist/index.js config set --batch-json '[{\"path\":\"channels.telegram.enabled\",\"value\":true}]'"
   ```
3. Confirm: `ssh picklelab "docker exec openclaw openclaw channels status"` shows `running, connected, mode:polling`. Hot-reload is confirmed for `agents.defaults.*`, not independently confirmed for channel enablement — if it doesn't take effect live, `docker compose restart openclaw`.
4. Message the bot from the allowlisted chat; confirm it responds. Confirm a non-allowlisted account is silently rejected (no trace on either side — expected, not a bug).

Only after this is confirmed working should `pickleclaw` be decommissioned (design doc "Decommissioning pickleclaw" — give it a day or two of stable real traffic first).

## Deploying Updates

```bash
just deploy-openclaw
```

Bumps run through the pinned `OPENCLAW_IMAGE` var: change it in `.env`, redeploy. `deploy.sh` runs `docker compose pull` then `up -d` (no `build:` key, so `pull` is unambiguous), and a `doctor` pass catches config-schema migrations.

## Environment Variables

Non-secret config is set in `compose.yaml`; secrets come from the filtered `.env` (`.env.vars` -> `scripts/service-env`).

| Variable | Source | Description |
|----------|--------|-------------|
| `OPENCLAW_GATEWAY_BIND` | compose | `lan` — required internally even though the only host-side exposure is `127.0.0.1:18789`, see design doc "Port & bind topology" |
| `OPENCLAW_HOST` | `.env` (1Password) | Tailscale Services hostname |
| `OPENCLAW_GATEWAY_TOKEN` | `.env` (1Password) | Control-UI/API bearer token |
| `OLLAMA_API_KEY` | `.env` (1Password) | Ollama Cloud subscription key (chat/heartbeat) |
| `OPENROUTER_API_KEY` | `.env` (1Password) | Embeddings only — Ollama Cloud doesn't support them |
| `TELEGRAM_BOT_TOKEN` | `.env` (1Password) | Bot identity (same bot as `pickleclaw`) |
| `GEMINI_API_KEY` | `.env` (1Password) | `web_search` (gemini provider) — reused from `pickleclaw` |
| `OPENCLAW_ALLOWED_CHAT_IDS` | `.env` (1Password) | Comma-separated chat-ID allowlist — the front door |
| `OPENCLAW_WORKSPACE_DEPLOY_KEY_B64` | `.env` (1Password) | Base64 ed25519 deploy key; `deploy.sh` decodes it to `ssh/workspace_deploy_key` for the one-time workspace clone |
| `OPENCLAW_IMAGE` | `.env` | Pinned image ref, e.g. `ghcr.io/openclaw/openclaw:2026.6.11` |

**Why `OPENCLAW_HOST` also has to be pushed into `gateway.controlUi.allowedOrigins` (`deploy.sh`'s `config set --batch-json` step):** OpenClaw doesn't auto-discover its own Tailscale hostname for browser-Origin validation on a non-loopback bind (`lan`/`tailnet`/`auto`) — it only auto-seeds `http://localhost:<port>`/`http://127.0.0.1:<port>` (`gateway-control-ui-origins.ts` in the vendored source). Without an explicit entry, the Control UI would still often work anyway: `origin-check.ts` has a same-origin fallback that trusts any `*.ts.net` hostname when the `Origin` and `Host` headers match — but that's an implicit fallback, not a guarantee (e.g. it breaks if something ever proxies with a different `Host`), so keep setting `allowedOrigins` explicitly rather than relying on it.

## Data Locations (on picklelab)

```
/srv/data/openclaw/config/openclaw.json    # writable root config (created by onboard)
/srv/data/openclaw/workspace/              # openclaw-workspace checkout (identity/memory)
/srv/data/openclaw/auth/                   # OpenClaw's own auth-profile store
/srv/data/openclaw/bin/                    # drop-in CLIs, mounted read-only to /opt/tools
/srv/data/openclaw/ssh/workspace_deploy_key # scoped openclaw-workspace deploy key (0600)
```

All of `/srv/data/openclaw` is picked up by the nightly restic job. `bin/` is reproducible from a future committed manifest, so it's covered but not load-bearing.

**Ongoing workspace sync** is a manual `git add . && git commit && git push` from inside `/srv/data/openclaw/workspace/` on picklelab (same pattern `pickleclaw` used) — not automated by the container or `deploy.sh` on day one.

## Security

Tool profile is `coding`, full local tool surface, no `deny` list (browser/canvas/automation deny removed 2026-07-02, "for now", explicit request — matches pickleclaw's local config 1:1, which never had one) — see `openclaw.tools.json5` in the private `pickleclaw` repo. No `docker.sock` grant; the gateway is containerized and relies on tool policy rather than the in-container Docker sandbox. Full rationale in the design doc's "Security decisions".

**Exec policy matches pickleclaw's local permission model** (changed 2026-07-02, Josh's explicit call): `exec: { security: "full", ask: "off" }` — exec runs immediately, no live Telegram approval prompt. This reverses the original day-one/second-day plan (`minimal` profile + `alsoAllow` + `ask: "always"`, every exec call gated on a live approval), which was deliberately more conservative than pickleclaw's own defaults. That `ask: "always"` flow caused a real, confusing failure mode in practice: an expired/denied approval for a given command silently auto-denied a later identical request with no new prompt shown (collateral denial, not a real user rejection) — see the 2026-07-02 weather/tides testing session. Given picklelab is a single-trusted-operator bot (Telegram DM allowlist, `commands.ownerAllowFrom` both set to `OPENCLAW_ALLOWED_CHAT_IDS`), Josh chose to match pickleclaw's local testing behavior (`security=full`, `ask=off`) rather than keep fighting the approval-flow edge cases. Web search still reuses pickleclaw's proven Gemini wiring (`tools.web.search.provider: "gemini"`, `GEMINI_API_KEY` env var, no plugin install needed — it's a stock extension), now granted natively by the `coding` profile rather than via `alsoAllow`.

## Logs

```bash
just openclaw-logs
just openclaw-logs-follow
```
