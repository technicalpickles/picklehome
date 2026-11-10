# Runbooks

Step-by-step procedures you run by hand more than once. Unlike `docs/plans/`
(point-in-time) these are meant to stay true, so fix them when a step turns out
wrong.

## Rotating secrets

Written after the Oct 22, 2026 exposure, when a batch of secrets landed in a
Claude transcript. One runbook per group, matching how the work splits up:

| Runbook | Covers |
|---|---|
| [Tailscale](rotate-tailscale.md) | auth keys, API OAuth client |
| [GitHub](rotate-github.md) | workspace PAT, Woodpecker OAuth app, deploy keys, runner token |
| [OpenClaw](rotate-openclaw.md) | gateway token, Telegram bot, GOG MCP token, Ollama / OpenRouter / Gemini keys |
| [Brineworks](rotate-brineworks.md) | API key, MCP key, Postgres password |
| [Open WebUI, Open Terminal, UniFi](rotate-open-webui-unifi.md) | admin password, secret key, terminal key, UniFi login and key |
| [Device and cloud accounts](rotate-device-accounts.md) | Ecobee, Nest, Hue, LG, Yale, Aladdin, BlueAir, ConnectLife, Moen Flo, VicoHome, Cloudflare Radar, Google keys |
| [Restic and keyring passwords](rotate-restic-and-keyrings.md) | passwords that protect data at rest. Decide before acting |

Steps marked **Verify** are things the repo could not confirm (a vendor console
layout, an app's behaviour). Check them the first time and edit the runbook.

### How secrets reach services

Every secret lives in a 1Password item (paths are in `.env.template`). Services
never hold a plaintext `.env` on picklelab: the systemd unit wraps
`docker compose up` in `op run`, which resolves `op://` references at start. So
for nearly every secret, rotation is:

1. Make the new value at the provider. Leave the old one working.
2. Put the new value in the 1Password item field.
3. Restart the consumer so `op run` re-reads it (`just deploy-<service>`).
4. Check the service works on the new value.
5. Revoke the old value at the provider.
6. Close the taskwarrior task and note what changed.

Revoke last. If step 4 fails you still have the old value to fall back to.

### Rules

- **Edit values in the 1Password app.** `op item edit field=value` puts the
  value on the command line, and a command line is visible in `ps` and in any
  transcript that captures it. That is how the last exposure happened.
- **Never paste a value into a chat, a commit, a doc, or a command.** This repo
  is public. Write the `op://` path, never the value.
- **Generate random values with `openssl rand -hex 32`** (or `-base64 32` where
  a runbook says so) and copy straight into the 1Password field.
- **Check Brent is idle before deploying openclaw or brineworks-server.** The
  deploys refuse while he was active in the last five minutes
  ([ADR 0003](../adr/0003-refuse-deploys-while-brent-is-active.md)). Run
  `just openclaw-quiet` to check on its own.
- **One deploy at a time.** picklelab takes a host-wide lock, so a second deploy
  fails fast with exit 75.
- **Two vaults.** Items under `picklehome` are read by `op-token-picklehome`.
  Items under `Brent Pickleclaw` are shared with the pickleclaw dev VM, so
  rotating them there changes what that VM reads too.

### Order for a full sweep

1. Dead credentials first (revoke only, nothing to deploy): old Tailscale auth
   keys, the retired runner token, deploy keys for torn-down agents.
2. Things that grant access: Tailscale, GitHub.
3. Bot and server tokens: OpenClaw, Brineworks.
4. Web admin and UniFi, then device accounts.
5. Restic and keyrings last, once decided.

Group deploys so each service restarts once: OpenClaw and Brineworks each have
secrets from several runbooks.

### Recording it

Per secret, `task <uuid> annotate "rotated, old revoked"` then `task <uuid> done`.
Cite tasks by UUID in commits, never by integer id.
