# Brineworks Agent

An always-on, phone-reachable Claude Code session on picklelab that runs the brineworks CLI against prod. Reached over Tailscale by SSH; work happens in a long-lived tmux session. This is the mobile agent surface (brineworks [ADR 0005](https://github.com/technicalpickles/brineworks/blob/main/docs/decisions/0005-mobile-agent-surface.md)).

**Source repo:** `technicalpickles/brineworks` (private). The image contract (`agent/Dockerfile`, entrypoint, the env vars it reads) lives there; this directory owns orchestration only (brineworks `docs/ops-principles.md` #4).

## What it is

A self-contained Ubuntu container with a real `sshd` (key-only, `authorized_keys` pulled from your GitHub keys), Claude Code, the brineworks CLI (`bw`), and tmux (resurrect/continuum). You SSH in from a phone, `tmux attach`, and you're in a full Claude Code session with `bw` wired to the prod server and prod Gmail.

Modeled on `homelab/dev/` (the container internals: sshd, GitHub-keys auth, host keys on a volume) and `homelab/services/brineworks-server/` (the deploy/orchestration shape).

## Prerequisites (one-time)

**Tailscale admin** (skip the first two if already done for brineworks/taskchampion):
- HTTPS certs enabled at https://login.tailscale.com/admin/dns
- `tag:server` applied to picklelab
- Define a `brineworks-agent` Service at https://login.tailscale.com/admin/services with **TCP port `22`** (raw TCP, not HTTPS 443 like the other services). Without the service definition there is nothing for `tailscale serve --service` to advertise into, so the Services page stays empty and the host never appears as pending.

The agent needs the cryptfile keyring master password in the `picklehome` 1Password vault, surfaced into the root `.env`:

| Field | How to generate | Notes |
|-------|-----------------|-------|
| `KEYRING_CRYPTFILE_PASSWORD` | `openssl rand -base64 32` | Unlocks the in-container Gmail token keyring |

`BRINEWORKS_API_KEY` is reused from the existing `Brineworks Server` item (the agent is a client of the same server). Add the `op://` reference for `KEYRING_CRYPTFILE_PASSWORD` to `.env.template` and run `just dotenv` (see the project [CLAUDE.md](../../../CLAUDE.md) "Secrets & Config").

### Workspace deploy key (one-time)

The agent clones and pushes the `technicalpickles/brineworks-workspace` repo (triage rules + session data) with a **scoped read-write deploy key** -- low blast radius (config data, no code), so AFK-capable push is acceptable (brineworks design doc).

1. Generate an ed25519 keypair (no passphrase -- the container runs unattended):
   ```bash
   ssh-keygen -t ed25519 -f brineworks-workspace-deploy -C "brineworks-agent workspace deploy key" -N ""
   ```
2. Add the **public** key (`brineworks-workspace-deploy.pub`) to `technicalpickles/brineworks-workspace` -> Settings -> Deploy keys, **with "Allow write access" checked**.
3. Store the key in the `picklehome` 1Password vault as an SSH-key item titled `Brineworks Agent` (drag the private key in, or `op` it). Then add a **custom text field** `workspace_deploy_key_b64` holding the **single-line base64** of the private key. The 1Password CLI cannot edit SSH-key items, so add the field in the app; copy the value with:
   ```bash
   op read 'op://picklehome/Brineworks Agent/private key' | base64 | tr -d '\n' | pbcopy
   ```
   (`tr -d '\n'` matters: macOS `base64` wraps at 76 cols, and a multi-line value breaks `scripts/service-env`'s line-based filter. Single line survives it; `deploy.sh` decodes it back to the key file on the volume.)
4. Add the reference to `.env.template` (next to the other Brineworks vars) and re-run `just dotenv`. Custom fields on an SSH-key item nest under its `add more` section, so the ref carries that path:
   ```
   WORKSPACE_DEPLOY_KEY_B64={{ op://picklehome/Brineworks Agent/add more/workspace_deploy_key_b64 }}
   ```
   `WORKSPACE_DEPLOY_KEY_B64` is already in `.env.vars`; until the `op://` reference exists it's skipped silently, and both `deploy.sh` and the entrypoint degrade to a bare workspace (no rules pipeline) with a warning. Delete the local keypair once it's in 1Password and on GitHub.

Your phone's SSH client public key must be in your GitHub keys (`https://github.com/technicalpickles.keys`) -- the entrypoint fetches that into `authorized_keys` on first boot.

## First-time Setup

```bash
just dotenv          # pull secrets from 1Password (incl. KEYRING_CRYPTFILE_PASSWORD)
just deploy-brineworks-agent
```

`deploy.sh` ensures the brineworks source clone at `/opt/brineworks` (lockstep with the server), creates the `/data` volume directories, configures Tailscale serve, builds the image, and starts the systemd service.

### Approve the Tailscale service (first deploy only)

This is the homelab's first **raw-TCP** Tailscale service (SSH, not HTTPS). The service must already be defined in the admin console (see Prerequisites); without it nothing shows up here to approve. On the first deploy the endpoint won't respond until you approve it:

1. Open [Tailscale Services](https://login.tailscale.com/admin/services)
2. Find `brineworks-agent` and approve the pending host advertisement
3. Re-advertise (tailscaled doesn't auto-detect approval):
   ```bash
   sudo tailscale serve --service=svc:brineworks-agent --tcp=22 off
   sleep 2
   sudo tailscale serve --service=svc:brineworks-agent --tcp=22 tcp://127.0.0.1:2223
   ```
4. Verify: `ssh technicalpickles@brineworks-agent.<tailnet>.ts.net`

`deploy.sh` prints these steps if the endpoint isn't reachable. If raw-TCP serve turns out unsupported, the fallback is to bind the published port to the host's tailscale IP (in `compose.picklelab.yaml`) instead of loopback and reach it as `picklelab:2223`.

## Gmail bootstrap (one-time)

The CLI reads its Gmail OAuth token from the cryptfile keyring on `/data`. Until `bw email auth --device` exists (brineworks M4), bootstrap is copy-the-token:

1. On the Mac, auth with MODIFY scopes so the stored token can apply labels.
2. Copy the resulting keyring file onto the volume at `/srv/data/brineworks-agent/keyring/cryptfile.cfg`.

(The container can't run the interactive OAuth browser flow, so the token is minted on the Mac and dropped onto the volume.)

## Connecting

```bash
ssh technicalpickles@brineworks-agent.<tailnet>.ts.net
tmux attach            # or: tmux new -s main
```

The tmux session is long-lived and survives disconnects. A redeploy recreates the container and kills the live session; tmux-resurrect/continuum plus `~/.claude` on the volume restore the layout and conversation on reattach. In-flight pipeline runs are recovered by rerun (brineworks principle #13).

## Deploying Updates

```bash
just deploy-brineworks-agent
```

Pulls latest `picklehome` and `brineworks`, rebuilds the image, restarts the service. Lockstep with `just deploy-brineworks-server` keeps the agent and server at the same brineworks SHA (the CLI talks to the server over a stable HTTP API, so SHA skew is safe if they ever drift).

## Architecture

- **Build from source:** the image builds from `/opt/brineworks` (whole repo, `agent/Dockerfile`) -- the same host clone the server builds from, kept fast-forwarded by `deploy.sh`. No published image.
- **Compose layering:** `compose.yaml` is the portable base (`image: brineworks-agent:local`, non-secret config). `compose.picklelab.yaml` adds the `build:` directive, the loopback port bind, the `/data` volume, and the filtered `env_file`.
- **Code vs. state:** the image bakes the brineworks code (frozen at the build SHA -- the container's analog of the Mac workspace's `repo` symlink + editable install). All durable state lives on the `/data` volume. The container owns no source checkout; to do dev work on brineworks, clone it ad hoc, same as you would on the Mac.
- **Secrets:** the container receives **only** its filtered `.env` (`KEYRING_CRYPTFILE_PASSWORD`, `BRINEWORKS_API_KEY`), never the master `/opt/homelab/.env`. It runs arbitrary Claude sessions, so it gets the github-actions-runner treatment (`homelab/services/README.md`).
- **Networking:** the container's sshd (`:22`) is published on `127.0.0.1:2223` (loopback only; `2223` avoids `homelab/dev`, which holds `2222` on `0.0.0.0`). `tailscale serve --tcp=22` proxies `brineworks-agent.<tailnet>.ts.net:22` to it. Re-applied on every deploy; idempotent.

## Environment Variables

Non-secret config is set in `compose.yaml`; secrets come from the filtered `.env` (`.env.vars` -> `scripts/service-env`).

| Variable | Source | Description |
|----------|--------|-------------|
| `BRINEWORKS_ENV` | compose | `production` -- every `bw` command hits the real server and Gmail |
| `BRINEWORKS_SERVER_URL` | compose | `https://brineworks.<tailnet>.ts.net` (prod server, explicit URL wins) |
| `BRINEWORKS_KEYRING_FILE` | compose | `/data/keyring/cryptfile.cfg` |
| `BRINEWORKS_EMAIL_BASE_DIR` | compose | `/data/workspace/email/sessions` |
| `PF_KEYCHAIN_PREFIX` | compose | `agent` (per-worktree macOS logic doesn't apply in-container) |
| `KEYRING_CRYPTFILE_PASSWORD` | `.env` (1Password) | Master password for the cryptfile keyring |
| `BRINEWORKS_API_KEY` | `.env` (1Password) | Bearer token for the prod server (same key as the server) |
| `WORKSPACE_DEPLOY_KEY_B64` | `.env` (1Password) | Base64 ed25519 deploy key; `deploy.sh` decodes it to `ssh/workspace_deploy_key` for the workspace clone/push |

## Data Locations (on picklelab)

```
/opt/brineworks/                              # brineworks repo clone (shared build input)
/srv/data/brineworks-agent/ssh/host_keys      # persistent sshd host keys
/srv/data/brineworks-agent/ssh/workspace_deploy_key  # scoped brineworks-workspace deploy key (0600, uid 1000)
/srv/data/brineworks-agent/keyring/           # cryptfile Gmail token keyring
/srv/data/brineworks-agent/workspace/         # brineworks-workspace checkout (triage rules + session data)
```

The brineworks `agent/entrypoint.sh` also redirects durable user state onto the volume, so login and sessions survive redeploys:

```
/srv/data/brineworks-agent/claude/       # ~/.claude (.credentials.json, settings, transcripts)
/srv/data/brineworks-agent/claude.json   # ~/.claude.json (OAuth + MCP state)
/srv/data/brineworks-agent/tmux-resurrect # tmux-resurrect/continuum session saves
```

On boot the entrypoint also clones (or fast-forward-pulls) the `brineworks-workspace` repo into `workspace/` via the scoped deploy key, so the triage rules at `email/config/triage-rules.yaml` are present and current for the pipeline. It symlinks the baked skills into the workspace (`workspace/.claude/skills`), mirroring the Mac workspace's `setup`, so `/process-email` resolves from the session. Without the deploy key it falls back to a bare `workspace/` (no rules pipeline).

All of `/data` is backed up by picklehome's restic (once added to the backup service).

## Logs

```bash
just brineworks-agent-logs
just brineworks-agent-logs-follow
```
