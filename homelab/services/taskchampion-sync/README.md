# TaskChampion Sync

Self-hosted Taskwarrior sync server. Replicates the Mac's `~/.task` to picklelab; encryption secret stays Mac-side, server only sees opaque blobs keyed by client ID.

Single-client today (Mac only). Adding a second device is a config change: append a UUID to the allowlist, set the same env on the new device, run `task sync`.

Design: [`docs/plans/2026-05-03-taskchampion-sync.md`](../../../docs/plans/2026-05-03-taskchampion-sync.md).

## Prerequisites (one-time)

1. **Tailscale admin** (skip if already done for brineworks):
   - HTTPS certs enabled at https://login.tailscale.com/admin/dns
   - `tag:server` applied to picklelab
   - Define a `taskchampion` Service at https://login.tailscale.com/admin/services with port `443`

2. **1Password item** `TaskChampion Sync` in the `picklehome` vault:

   | Field | How to generate |
   |-------|-----------------|
   | `host` | `taskchampion.<tailnet>.ts.net` (literal) |
   | `client_id` | `uuidgen` |
   | `encryption_secret` | `openssl rand -base64 32` |

## First-time Setup

```bash
just dotenv             # pull host + client_id from 1Password
just deploy-taskchampion
```

On first deploy, the Tailscale endpoint won't respond until you approve the service:

1. Open [Tailscale Services](https://login.tailscale.com/admin/services)
2. Find `taskchampion` and approve the pending host advertisement
3. Re-advertise (tailscaled doesn't auto-detect approval):
   ```bash
   sudo tailscale serve --service=svc:taskchampion --https=443 off
   sleep 2
   sudo tailscale serve --service=svc:taskchampion --https=443 "http://127.0.0.1:$TASKCHAMPION_SYNC_PORT"
   ```
4. Verify: `curl https://taskchampion.<tailnet>.ts.net/`

The deploy script prints these steps automatically if the Tailscale endpoint isn't responding.

## Mac-side setup

Mac-side config lives in the [dotfiles](https://github.com/technicalpickles/dotfiles) repo, not here. The encryption secret never leaves the Mac.

`~/.taskrc` (managed in `dotfiles/home/.taskrc`) ends with:

```
include ~/.config/task/sync.rc
```

`~/.config/task/sync.rc` holds the three sync settings (`sync.server.url`, `sync.server.client_id`, `sync.encryption_secret`). It is generated from `op://picklehome/TaskChampion Sync` by `dotfiles/taskrc.sh`, which runs as part of the dotfiles install. The generated file lives outside any repo (0600), so the secret is structurally impossible to commit. This mirrors how `gitconfig.sh` generates `~/.gitconfig.local`.

To set up (or regenerate) on a Mac:

```bash
cd ~/path/to/dotfiles && ./taskrc.sh
```

On machines where `taskrc.sh` can't write real creds (non-macOS, no 1Password CLI, or the item is missing), it writes a commented placeholder instead, so the `include` never warns.

First sync uploads existing local task history:

```bash
task sync
```

## Deploying Updates

```bash
just deploy-taskchampion
```

Pulls the latest image (`--pull always` in the systemd unit) and restarts.

## Status & Logs

```bash
just taskchampion-status       # systemd + loopback HTTP + tailscale routing
just taskchampion-logs         # last 50 lines
just taskchampion-logs-follow  # live tail
```

The status recipe runs three checks in order. Any failure tells you which layer to investigate (systemd, the container, or tailscale routing).

## Architecture

- **Image:** `ghcr.io/gothenburgbitfactory/taskchampion-sync-server` (upstream Rust/actix-web). No build from source.
- **Networking:** container binds `0.0.0.0:9080` inside its netns; host port maps to `127.0.0.1:9080`. Reachable only via `tailscaled`'s local proxy.
- **Port configuration:** controlled by `TASKCHAMPION_SYNC_PORT`, default `9080`. `deploy.sh` exports it; compose interpolates with `${...:?...}` and fails fast if unset; `tailscale serve` references the same var. To change the port, export `TASKCHAMPION_SYNC_PORT` before running `deploy.sh`. (Same pattern as brineworks-server.)
- **Storage:** SQLite at `/srv/data/taskchampion-sync/`. Single file (plus WAL/SHM). Backed up nightly by the existing restic job.
- **Auth model:** zero-knowledge. Server stores opaque encrypted blobs keyed by `CLIENT_ID`. The encryption secret never reaches picklelab; only Mac-side clients can decrypt. The `CLIENT_ID` allowlist (set via env) limits which client UUIDs can write.

## Environment Variables

Server-side (set in compose, mapped from `.env`):

| Internal name | From `.env` | Description |
|---------------|-------------|-------------|
| `CLIENT_ID` | `TASKCHAMPION_SYNC_SERVER_CLIENT_ID` | Allowlist of client UUIDs (comma-separated for multiple) |
| `LISTEN` | `TASKCHAMPION_SYNC_PORT` | Bind address; always `0.0.0.0:<port>` inside the container |
| `DATA_DIR` | (constant) | `/var/lib/taskchampion` inside the container |

Mac-side: not env vars. `dotfiles/taskrc.sh` reads three fields from `op://picklehome/TaskChampion Sync` and writes them straight into `~/.config/task/sync.rc`:

| `sync.rc` setting | From 1Password field | Description |
|-------------------|----------------------|-------------|
| `sync.server.url` | `host` (with `https://` prepended) | `https://taskchampion.<tailnet>.ts.net` |
| `sync.server.client_id` | `client_id` | Same UUID as the server allowlist |
| `sync.encryption_secret` | `encryption_secret` | base64; never leaves the Mac |

## Data Locations (on picklelab)

```
/opt/homelab/homelab/services/taskchampion-sync/   # service files
/srv/containers/taskchampion-sync/                 # .env (filtered, deployed by service-env)
/srv/data/taskchampion-sync/                       # SQLite database (backed up nightly)
```
