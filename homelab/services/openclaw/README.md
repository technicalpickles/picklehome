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

### Pickleclaw deploy key (one-time)

`gog-mcp`'s source (`nodes/gog-mcp/` in the private `pickleclaw` repo) isn't open source like `goplaces-node`, so it can't be baked into this public repo's Dockerfile — instead `deploy.sh` clones/pulls `pickleclaw@main` directly on picklelab, host-side, using a scoped **read-only** deploy key.

1. Generate an ed25519 keypair (no passphrase):
   ```bash
   ssh-keygen -t ed25519 -f openclaw-pickleclaw-deploy -C "openclaw picklelab pickleclaw deploy key" -N ""
   ```
2. Add the **public** key to `technicalpickles/pickleclaw` -> Settings -> Deploy keys, **with "Allow write access" unchecked** — this key only needs to read.
3. Store the private key in the `picklehome` 1Password vault as an SSH-key item titled `OpenClaw Pickleclaw Deploy Key`, with a custom text field `deploy_key_b64` holding the **single-line base64** of the private key (same convention as the workspace deploy key above — see step 3 there for the `op item get`/"add more" nesting caveat and the `base64 | tr -d '\n'` command).
4. Add to `.env.template`:
   ```
   OPENCLAW_PICKLECLAW_DEPLOY_KEY_B64={{ op://picklehome/OpenClaw Pickleclaw Deploy Key/deploy_key_b64 }}
   ```
   Until the ref exists it's skipped silently and `deploy.sh` degrades to no-clone with a warning, and the guarded `gog-mcp` build step in `deploy.sh` skips the build rather than failing the deploy. Delete the local keypair once it's in 1Password and on GitHub.

### Google Places API key (one-time, for the goplaces second node)

Powers the `goplaces-node` compose service — an isolated container that holds
`GOOGLE_PLACES_API_KEY` separately from every other secret this deploy uses (inference
keys, Telegram token). Full design/verification history:
`docs/superpowers/plans/2026-07-07-goplaces-node-picklelab-deploy.md` and
`docs/setup-notes.md`'s "goplaces node" section, both in the `pickleclaw` repo.

1. Create (or reuse) a GCP project, enable **Places API (New)** and **Routes API**,
   generate an API key, and restrict it to those two APIs — same steps documented in
   the bundled `goplaces` skill's own `SKILL.md` install instructions.
2. Add a custom text field `google_places_api_key` to the existing `picklehome/OpenClaw`
   1Password item (same item as `host`/`gateway_token`/`allowed_chat_ids` — this is
   another picklelab-specific value, not shared with `pickleclaw`'s own testing key).
3. `.env.template` already references it (`{{ op://picklehome/OpenClaw/google_places_api_key }}`)
   — running `just dotenv` after step 2 pulls it into `.env` automatically.

### Include-file setup (one-time, per dev machine)

`openclaw.tools.json5` (tool policy) and `openclaw.mcp.json5` (MCP server config) aren't committed to this **public** repo — the MCP file would leak real server names/commands. Both live in the private `pickleclaw` repo instead, symlinked in:

```bash
ln -sf ~/github.com/technicalpickles/pickleclaw/openclaw-config/tools.json5 \
  homelab/services/openclaw/openclaw.tools.json5
ln -sf ~/github.com/technicalpickles/pickleclaw/openclaw-config/mcp.json5 \
  homelab/services/openclaw/openclaw.mcp.json5
```

`deploy.sh` runs from the Mac, where `pickleclaw` is already cloned with your own GitHub access — `git pull` it before deploying, same as any other dependency.

**`pickleclaw` must be on a pushed `main`, not dirty, before `just deploy-openclaw`.** This deploy now pulls from `pickleclaw` in two independent places that have to agree: `just deploy-openclaw` symlinks `tools.json5`/`mcp.json5` from whatever local checkout you have here (no branch/cleanliness guard), while `deploy.sh` separately clones/pulls `pickleclaw@main` on picklelab itself for gog-mcp's build context. If your local checkout is on a feature branch or has uncommitted changes when you symlink from it, the config picklelab loads and the gog-mcp source picklelab builds can silently diverge. Push to `main` and make sure the local tree is clean before running the symlink setup or a deploy.

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
3. Confirm: `ssh picklelab "docker exec openclaw-openclaw-1 openclaw channels status"` shows `running, connected, mode:polling`. Hot-reload is confirmed for `agents.defaults.model.*`/`heartbeat.*` (not for every key under `agents.defaults.*` — e.g. `thinkingDefault` needs a restart, see `pickleclaw`'s `CLAUDE.md`), and not independently confirmed for channel enablement — if it doesn't take effect live, `docker compose restart openclaw`.
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
| `GOOGLE_PLACES_API_KEY` | `.env` (1Password) | Real key for the isolated `goplaces-node` service only — the `openclaw` service itself gets a hardcoded placeholder, never this value |
| `OPENCLAW_WORKSPACE_DEPLOY_KEY_B64` | `.env` (1Password) | Base64 ed25519 deploy key; `deploy.sh` decodes it to `ssh/workspace_deploy_key` for the one-time workspace clone |
| `OPENCLAW_PICKLECLAW_DEPLOY_KEY_B64` | `.env` (1Password) | Base64 ed25519 read-only deploy key; `deploy.sh` decodes it to `ssh/pickleclaw_deploy_key` to clone/pull `pickleclaw@main` (gog-mcp's build context) |
| `GOG_MCP_TOKEN` | `.env` (1Password) | Bearer token gog-mcp's HTTP endpoint requires; set on both the `openclaw` service (interpolated into `mcp.json5`'s Authorization header) and the `gog-mcp` service (to check incoming requests) |
| `GOG_KEYRING_PASSWORD` | `.env` (1Password) | Decryption password for gog-mcp's file keyring (OAuth refresh tokens); set only on the `gog-mcp` service |
| `OPENCLAW_IMAGE` | `.env` | Pinned image ref, e.g. `ghcr.io/openclaw/openclaw:2026.6.11` |

**Why `OPENCLAW_HOST` also has to be pushed into `gateway.controlUi.allowedOrigins` (`deploy.sh`'s `config set --batch-json` step):** OpenClaw doesn't auto-discover its own Tailscale hostname for browser-Origin validation on a non-loopback bind (`lan`/`tailnet`/`auto`) — it only auto-seeds `http://localhost:<port>`/`http://127.0.0.1:<port>` (`gateway-control-ui-origins.ts` in the vendored source). Without an explicit entry, the Control UI would still often work anyway: `origin-check.ts` has a same-origin fallback that trusts any `*.ts.net` hostname when the `Origin` and `Host` headers match — but that's an implicit fallback, not a guarantee (e.g. it breaks if something ever proxies with a different `Host`), so keep setting `allowedOrigins` explicitly rather than relying on it.

## Data Locations (on picklelab)

```
/srv/data/openclaw/config/openclaw.json      # writable root config (created by onboard)
/srv/data/openclaw/workspace/                # openclaw-workspace checkout (identity/memory)
/srv/data/openclaw/auth/                     # OpenClaw's own auth-profile store
/srv/data/openclaw/bin/                      # drop-in CLIs, mounted read-only to /opt/tools
/srv/data/openclaw/ssh/workspace_deploy_key  # scoped openclaw-workspace deploy key (0600)
/srv/data/openclaw/ssh/pickleclaw_deploy_key # scoped read-only pickleclaw deploy key (0600)
/srv/data/openclaw/gog-keyring/              # gog-mcp's OAuth token file keyring, bind-mounted
                                              # into the gog-mcp container (moved off a named
                                              # Docker volume so it's covered by backup below)
/opt/pickleclaw/                             # pickleclaw@main checkout, gog-mcp's build context
                                              # (host-side, NOT under /srv/data -- not backed up,
                                              # reproducible by re-cloning)
```

All of `/srv/data/openclaw` is picked up by the nightly restic job. `bin/` is reproducible from a future committed manifest, so it's covered but not load-bearing. `/opt/pickleclaw` is deliberately outside `/srv/data`: it's a disposable source checkout, not state — see `deploy.sh`'s clone/pull step.

**Ongoing workspace sync** is automated via an in-container `openclaw cron` job (`workspace-git-sync`, hourly): commits local changes, `git pull --rebase`, pushes; a real rebase conflict escalates to an `openclaw agent` call for judgment rather than guessing. Registered idempotently by `deploy.sh`. Git auth is HTTPS + a fine-grained PAT (`OPENCLAW_WORKSPACE_GITHUB_TOKEN`) via a `GIT_ASKPASS` helper, not the SSH deploy key above — the container image has no ssh client. See `docs/plans/2026-07-04-workspace-git-sync-picklelab-rollout.md` and `pickleclaw`'s `scripts/workspace-git-sync.sh` / `docs/setup-notes.md` "Workspace git backup".

## Security

Tool profile is `coding`, full local tool surface, no `deny` list (browser/canvas/automation deny removed 2026-07-02, "for now", explicit request — matches pickleclaw's local config 1:1, which never had one) — see `openclaw.tools.json5` in the private `pickleclaw` repo. No `docker.sock` grant; the gateway is containerized and relies on tool policy rather than the in-container Docker sandbox. Full rationale in the design doc's "Security decisions".

**Exec policy matches pickleclaw's local permission model** (changed 2026-07-02, Josh's explicit call): `exec: { security: "full", ask: "off" }` — exec runs immediately, no live Telegram approval prompt. This reverses the original day-one/second-day plan (`minimal` profile + `alsoAllow` + `ask: "always"`, every exec call gated on a live approval), which was deliberately more conservative than pickleclaw's own defaults. That `ask: "always"` flow caused a real, confusing failure mode in practice: an expired/denied approval for a given command silently auto-denied a later identical request with no new prompt shown (collateral denial, not a real user rejection) — see the 2026-07-02 weather/tides testing session. Given picklelab is a single-trusted-operator bot (Telegram DM allowlist, `commands.ownerAllowFrom` both set to `OPENCLAW_ALLOWED_CHAT_IDS`), Josh chose to match pickleclaw's local testing behavior (`security=full`, `ask=off`) rather than keep fighting the approval-flow edge cases. Web search still reuses pickleclaw's proven Gemini wiring (`tools.web.search.provider: "gemini"`, `GEMINI_API_KEY` env var, no plugin install needed — it's a stock extension), now granted natively by the `coding` profile rather than via `alsoAllow`.

**Session visibility is `agent`, so the chat allowlist is the only thing isolating sessions** (changed 2026-07-26). `tools.sessions.visibility: "agent"` in `openclaw.tools.json5` means every session under agent id `main` can read, memory-search, and `sessions_send` into every other one, no matter which surface opened it (Telegram, CLI, Control UI, heartbeat). Session keys are `agent:<agentId>:<rest>` and the check only compares that agent id, so `agent:main:telegram:direct:<id>` and `agent:main:main` are peers.

This routes around [openclaw/openclaw#114180](https://github.com/openclaw/openclaw/issues/114180): under the default `tree`, `sessions_list` hands the agent a session key that `sessions_history` then refuses, because history derives tree membership from a display-filtered listing whose child links expire 30 minutes after the child ends. The agent gets a bare `{"status":"forbidden"}` it can't act on, and the error text blames `tools.sessions.visibility`, which sends you off editing config for something that isn't a config problem. There is no narrower setting: upstream #55420 (open) asks for a glob allowlist precisely because nothing sits between `tree` and `agent`.

**The trade is explicit.** Before this, two independent things had to fail for one session to read another: the chat allowlist and the tool-layer tree check. Now the allowlist does all of it. That's acceptable only because it holds exactly one chat id and groups are closed (`deploy.sh` never sets `groupPolicy`, so it resolves to `"disabled"`). A second id, or an allowlisted group, would grant that person history access to every session on the box plus memory search across them. So `OPENCLAW_ALLOWED_CHAT_IDS` is a security control now, not just an access list, and `.env.template` says so at the point of editing.

"Single-trusted-operator bot" is load-bearing for two settings now, not one: it justifies both `exec: { security: "full", ask: "off" }` above and this. If that premise stops being true, both need revisiting together. Verified on the pickleclaw dev VM before landing here; background and a model-free gateway-RPC repro live in `pickleclaw`'s `docs/setup-notes.md`, "Unrelated find: `sessions_list` and `sessions_history` disagree about tree".

## Drift watchdog

A systemd oneshot + timer (`watchdog/`) that hashes both containers'
`exec-approvals.json` every 5 minutes and alerts on any change, plus a
standing every-run check for a wildcard (`*`) allowlist pattern (full exec in
disguise). It watches for drift under **any** exec-policy mode — it doesn't
assume allowlist mode is active. Currently picklelab runs `security: "full",
ask: "off"` (see Security above), so the file mostly just holds the exec
socket's own bookkeeping; the watchdog still matters because that's exactly
the state where an unnoticed rewrite (e.g. someone/something flipping a
container to `allowlist` with a `*` entry, or an agent silently rewriting its
own node's approvals — see `pickleclaw`'s `docs/setup-notes.md` Gotcha 9)
would otherwise go undetected. Journal is the record of truth regardless of
whether Telegram delivery succeeds; Telegram delivery resolves its target
from the gateway's own `commands.ownerAllowFrom` config at alert time — no
chat id is hardcoded anywhere in the script.

### Install

The watchdog service runs as root because it requires access to the Docker socket for `docker exec` and maintains state under `/var/lib/openclaw-approvals-watch`.

```bash
scp homelab/services/openclaw/watchdog/exec-approvals-watch.sh \
    homelab/services/openclaw/watchdog/openclaw-approvals-watch.service \
    homelab/services/openclaw/watchdog/openclaw-approvals-watch.timer \
    picklelab:/tmp/

ssh picklelab '
  sudo install -m 755 /tmp/exec-approvals-watch.sh /usr/local/bin/exec-approvals-watch.sh &&
  sudo install -m 644 /tmp/openclaw-approvals-watch.service /etc/systemd/system/ &&
  sudo install -m 644 /tmp/openclaw-approvals-watch.timer /etc/systemd/system/ &&
  rm -f /tmp/exec-approvals-watch.sh /tmp/openclaw-approvals-watch.service /tmp/openclaw-approvals-watch.timer
'
```

### Enable

```bash
ssh picklelab '
  sudo systemctl daemon-reload &&
  sudo systemctl enable --now openclaw-approvals-watch.timer &&
  systemctl list-timers openclaw-approvals-watch.timer
'
```

Expected: the timer listed with a next-run time. The first run establishes a
baseline hash per container — no alert on that run even though it has
nothing to compare against yet.

### Test with a manufactured drift

```bash
ssh picklelab '
  docker exec openclaw-openclaw-1 openclaw approvals allowlist add --agent main "/usr/bin/false" --json &&
  sudo systemctl start openclaw-approvals-watch.service &&
  journalctl -u openclaw-approvals-watch.service --since "2 min ago" | tail -10
'
```

Expected: `ALERT: gateway: exec-approvals.json changed (was ... now ...)` in
the journal, and the configured Telegram owner gets the
`🚨 approvals-watch: ...` message. Clean up the dummy entry afterward with
the exact command used in the verified 2026-07-12 test run:

```bash
ssh picklelab '
  docker exec openclaw-openclaw-1 sh -c "openclaw approvals get --json" \
    | jq ".file // ." \
    | jq ".agents.main.allowlist |= map(select(.pattern != \"/usr/bin/false\"))" > /tmp/cleaned.json &&
  docker exec -i openclaw-openclaw-1 openclaw approvals set --stdin < /tmp/cleaned.json &&
  rm /tmp/cleaned.json &&
  docker exec openclaw-openclaw-1 openclaw approvals get --json | jq ".file.agents.main.allowlist"
'
```

The removal itself alerts once on the next timer tick (it is *also* a hash
change from the dirty state) — that's correct behavior, not a bug. The tick
after that should be silent.

### Remove

```bash
ssh picklelab '
  sudo systemctl disable --now openclaw-approvals-watch.timer &&
  sudo rm -f /etc/systemd/system/openclaw-approvals-watch.{service,timer} \
             /usr/local/bin/exec-approvals-watch.sh &&
  sudo rm -rf /var/lib/openclaw-approvals-watch &&
  sudo systemctl daemon-reload
'
```

## Logs

```bash
just openclaw-logs
just openclaw-logs-follow
```
