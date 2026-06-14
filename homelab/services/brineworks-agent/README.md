# Brineworks Agent

An always-on, phone-reachable Claude Code session on picklelab that runs the brineworks CLI against prod. Reached over Tailscale by SSH; work happens in a long-lived tmux session. This is the mobile agent surface (brineworks [ADR 0005](https://github.com/technicalpickles/brineworks/blob/main/docs/decisions/0005-mobile-agent-surface.md)).

**Source repo:** `technicalpickles/brineworks` (private). The image contract (`agent/Dockerfile`, entrypoint, the env vars it reads) lives there; this directory owns orchestration only (brineworks `docs/ops-principles.md` #4).

## What it is

A self-contained Ubuntu container with a real `sshd` (key-only, `authorized_keys` pulled from your GitHub keys), Claude Code, the brineworks CLI (`bw`), and tmux (resurrect/continuum). You SSH in from a phone, `tmux attach`, and you're in a full Claude Code session with `bw` wired to the prod server and prod Gmail.

Modeled on `homelab/dev/` (the container internals: sshd, GitHub-keys auth, host keys on a volume) and `homelab/services/brineworks-server/` (the deploy/orchestration shape).

## Prerequisites (one-time)

**Tailscale admin** (skip the first if already done for brineworks/taskchampion):
- `tag:server` applied to picklelab, and `tag:server` listed under `tagOwners` in the ACL so an auth key may advertise it.
- Mint a **reusable, non-ephemeral auth key** at https://login.tailscale.com/admin/settings/keys, tagged `tag:server`. This authenticates the `ts-agent` node sidecar (the agent runs as its own tailnet node; see Architecture). Store it as `TS_AUTHKEY` (below). No Tailscale **Service** is needed anymore: the node advertises itself, so the old `svc:brineworks-agent` raw-TCP Service can be deleted.

The agent needs the cryptfile keyring master password in the `picklehome` 1Password vault, surfaced into the root `.env` as `KEYRING_CRYPTFILE_PASSWORD` (it unlocks the in-container Gmail token keyring). It lives in the `Brineworks Agent Keyring` password item (created with `op item create --generate-password`); `.env.template` carries the `op://` reference, so `just dotenv` picks it up (see the project [CLAUDE.md](../../../CLAUDE.md) "Secrets & Config").

The `ts-agent` sidecar joins the tailnet with `TS_AUTHKEY`. Store the minted key in the `picklehome` 1Password vault (e.g. a custom field `ts_authkey` on the `Brineworks Agent` item) and add the `op://` reference to `.env.template`:

```
TS_AUTHKEY={{ op://picklehome/Brineworks Agent/add more/ts_authkey }}
```

`TS_AUTHKEY` is already in `.env.vars`; until the reference exists it is skipped silently and the node cannot authenticate (the agent stays unreachable). Re-run `just dotenv` after adding it. A persisted node identity (`/data/ts-state`) means the key is used once at first join; rotating it later does not disturb a registered node.

`BRINEWORKS_API_KEY` is reused from the existing `Brineworks Server` item (the agent is a client of the same server).

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

`deploy.sh` ensures the brineworks source clone at `/opt/brineworks` (lockstep with the server), creates the `/data` volume directories (including `ts-state`), builds the image, and starts the systemd service (the `ts-agent` node sidecar plus the agent).

### Approve the node (first deploy only)

The agent joins the tailnet as its own node (`brineworks-agent`) via the `ts-agent` sidecar. If your tailnet requires device approval, the first deploy won't be reachable until you approve it:

1. Open [Tailscale Machines](https://login.tailscale.com/admin/machines)
2. Find `brineworks-agent` and approve / authorize it. Confirm it carries `tag:server`.
3. If an old `svc:brineworks-agent` **Service** still exists at [Tailscale Services](https://login.tailscale.com/admin/services), delete it so its name doesn't collide with the node.
4. If the node registered *while* the Service (or any other device) held the name, Tailscale deduped it to `brineworks-agent-1` and will **not** auto-rename once the conflict clears. The tell: `ssh brineworks-agent.<tailnet>.ts.net` hangs (the bare name resolves to nothing real) while `brineworks-agent-1.<tailnet>.ts.net` works. Fix it in [Tailscale Machines](https://login.tailscale.com/admin/machines): edit the machine name back to `brineworks-agent` (or re-check "auto-generate from OS hostname", since the container's hostname is already `brineworks-agent`). The name sticks across redeploys because the node identity persists on the `ts-state` volume.
5. Verify: `ssh technicalpickles@brineworks-agent.<tailnet>.ts.net` (MagicDNS for a fresh node can lag a few seconds).

`deploy.sh` prints these steps if the node isn't reachable. If the `net_admin` + `/dev/net/tun` grant is ever unacceptable (`homelab_07`), the documented fallback is the host-node path (bind the published port to the host's tailscale IP, reach it as `picklelab`); plain SSH works there but mosh's UDP is fiddlier. See `homelab/services/README.md` "container-as-node".

## Gmail bootstrap (one-time)

The CLI reads its Gmail OAuth token from the cryptfile keyring on `/data`. Until `bw email auth --device` exists (brineworks M4), bootstrap is copy-the-token. Two artifacts go onto the volume:

1. **The token, re-keyed for the container.** The Mac token lives in the macOS Keychain under service `main/pf-email`, but the container looks up `agent/pf-email` (its `PF_KEYCHAIN_PREFIX` is `agent`). So a straight keychain export won't match: mint a cryptfile keyring on the Mac with `KEYRING_CRYPTFILE_PASSWORD` (from the `Brineworks Agent Keyring` item), write the token JSON under service `agent/pf-email`, account `gmail-oauth`, and copy the file to `/srv/data/brineworks-agent/keyring/cryptfile.cfg` (0600, uid 1000). The token must carry MODIFY scopes so the pipeline can apply labels.
2. **The OAuth client-secrets JSON** (the `client_secret_*.json` from Google Cloud Console). The email CLI resolves it upfront (`load_config`) even when the stored token is valid, so `bw email search` fails without it; only `bw email auth --check` works token-only. Copy it to `/srv/data/brineworks-agent/config/app-credentials.json` (0600, uid 1000); `PFA_APP_CREDENTIALS` in `compose.yaml` points there.

(The container can't run the interactive OAuth browser flow, so the token is minted on the Mac and dropped onto the volume.)

Verify from any machine on the tailnet:

```bash
ssh technicalpickles@brineworks-agent.<tailnet>.ts.net 'bw email auth --check'   # token + keyring
ssh technicalpickles@brineworks-agent.<tailnet>.ts.net 'bw email search "in:inbox newer_than:2d" --name verify'   # full pipeline reach
```

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
- **Compose layering:** `compose.yaml` is the portable base (`image: brineworks-agent:local`, non-secret config). `compose.picklelab.yaml` adds the `build:` directive, the `ts-agent` Tailscale node sidecar, `network_mode: service:ts-agent` on the agent, the `/data` volume, and the filtered `env_file`.
- **Code vs. state:** the image bakes the brineworks code (frozen at the build SHA -- the container's analog of the Mac workspace's `repo` symlink + editable install). All durable state lives on the `/data` volume. The container owns no source checkout; to do dev work on brineworks, clone it ad hoc, same as you would on the Mac.
- **Secrets:** the container receives **only** its filtered `.env` (`KEYRING_CRYPTFILE_PASSWORD`, `BRINEWORKS_API_KEY`), never the master `/opt/homelab/.env`. It runs arbitrary Claude sessions, so it gets the github-actions-runner treatment (`homelab/services/README.md`).
- **Networking:** the agent runs as its own **Tailscale node** via the `ts-agent` sidecar (`tailscale/tailscale`, `TS_USERSPACE=false` kernel/TUN mode, `NET_ADMIN` + `/dev/net/tun`). The agent container shares the node's netns (`network_mode: service:ts-agent`), so its sshd (`:22`) and mosh-server's UDP land on the node's tailnet interface directly. Nothing is published to the host; reach the agent at `brineworks-agent.<tailnet>.ts.net`. This replaces the old `tailscale serve --tcp=22` Service (TCP-only, so it could not carry mosh's UDP). Rationale and rejected alternatives: brineworks [ADR 0006](https://github.com/technicalpickles/brineworks/blob/main/docs/decisions/0006-agent-tailnet-node-for-mosh.md); the reusable pattern is in `homelab/services/README.md` "container-as-node". The `net_admin` + tun grant lets the container manage its own interface, not the host: not `--privileged`, no docker socket, no host mount (consistent with `homelab_07`).

## Environment Variables

Non-secret config is set in `compose.yaml`; secrets come from the filtered `.env` (`.env.vars` -> `scripts/service-env`).

| Variable | Source | Description |
|----------|--------|-------------|
| `BRINEWORKS_ENV` | compose | `production` -- every `bw` command hits the real server and Gmail |
| `BRINEWORKS_SERVER_URL` | compose | `https://brineworks.<tailnet>.ts.net` (prod server, explicit URL wins) |
| `BRINEWORKS_KEYRING_FILE` | compose | `/data/keyring/cryptfile.cfg` |
| `BRINEWORKS_EMAIL_BASE_DIR` | compose | `/data/workspace/email/sessions` |
| `PF_KEYCHAIN_PREFIX` | compose | `agent` (per-worktree macOS logic doesn't apply in-container) |
| `PFA_APP_CREDENTIALS` | compose | `/data/config/app-credentials.json` (OAuth client-secrets JSON, copied during the Gmail bootstrap) |
| `KEYRING_CRYPTFILE_PASSWORD` | `.env` (1Password) | Master password for the cryptfile keyring |
| `BRINEWORKS_API_KEY` | `.env` (1Password) | Bearer token for the prod server (same key as the server) |
| `WORKSPACE_DEPLOY_KEY_B64` | `.env` (1Password) | Base64 ed25519 deploy key; `deploy.sh` decodes it to `ssh/workspace_deploy_key` for the workspace clone/push |
| `TS_AUTHKEY` | `.env` (1Password) | Reusable, `tag:server` auth key the `ts-agent` sidecar uses to join the tailnet (used once; node identity then persists on `/data/ts-state`) |

## Data Locations (on picklelab)

```
/opt/brineworks/                              # brineworks repo clone (shared build input)
/srv/data/brineworks-agent/ssh/host_keys      # persistent sshd host keys
/srv/data/brineworks-agent/ssh/workspace_deploy_key  # scoped brineworks-workspace deploy key (0600, uid 1000)
/srv/data/brineworks-agent/keyring/           # cryptfile Gmail token keyring
/srv/data/brineworks-agent/config/            # OAuth client-secrets JSON (app-credentials.json)
/srv/data/brineworks-agent/workspace/         # brineworks-workspace checkout (triage rules + session data)
/srv/data/brineworks-agent/ts-state/          # ts-agent Tailscale node identity (TS_STATE_DIR)
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
