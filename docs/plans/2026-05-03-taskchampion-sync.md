# TaskChampion Sync Server

Self-host the TaskChampion sync server on picklelab so the Mac's Taskwarrior data is replicated off the laptop.

## Goals

- Off-laptop replica of `~/.task` for backup and disaster recovery.
- Forward compatibility: adding a second device later is config-only, no infra rework.
- Zero changes to picklehome's existing patterns (Compose + systemd + Tailscale Services + 1Password secrets).

## Non-goals

- Multi-device sync today. Single client (the Mac) only.
- Multi-user. Single client_id.
- Making tasks readable from outside the Tailscale net (e.g. Claude Code on the web). Different problem, different shape. See "Future" below.

## Architecture

```
Mac (taskwarrior CLI)
    | task sync (HTTPS)
    v
https://taskchampion.tail2023b7.ts.net
    |  Tailscale Services (TLS terminate)
    v
picklelab :tailscaled → 127.0.0.1:9080
    |
    v
docker container (ghcr.io/gothenburgbitfactory/taskchampion-sync-server)
    |
    v
SQLite at /srv/data/taskchampion-sync/
```

The sync server is zero-knowledge: it stores opaque encrypted blobs keyed by `client_id`. The encryption secret never leaves the Mac. The server's only auth is the `CLIENT_ID` allowlist (one UUID).

Tailscale handles network-layer access ("who can reach this URL"). The sync protocol handles logical identity ("which user's data"). They stay decoupled.

## Service layout

`homelab/services/taskchampion-sync/` follows the conventions in [`homelab/services/README.md`](../../homelab/services/README.md):

| File | Purpose |
|------|---------|
| `compose.yaml` | Local dev compose (named volume) |
| `compose.picklelab.yaml` | Prod overrides: bind mount to `/srv/data/taskchampion-sync` |
| `deploy.sh` | scp + systemd install + tailscale serve setup |
| `.env.vars` | Lists `TASKCHAMPION_SYNC_SERVER_CLIENT_ID` (the only var needed on the host) |
| `taskchampion-sync.service` | systemd unit (long-running) |
| `README.md` | Service-specific setup |

### compose.yaml

```yaml
services:
  taskchampion-sync:
    image: ghcr.io/gothenburgbitfactory/taskchampion-sync-server:latest
    restart: unless-stopped
    environment:
      CLIENT_ID: ${TASKCHAMPION_SYNC_SERVER_CLIENT_ID:?required}
      LISTEN: 0.0.0.0:${TASKCHAMPION_SYNC_PORT:?set by deploy.sh}
      DATA_DIR: /var/lib/taskchampion
    ports:
      - "127.0.0.1:${TASKCHAMPION_SYNC_PORT:?set by deploy.sh}:${TASKCHAMPION_SYNC_PORT:?set by deploy.sh}"
    volumes:
      - data:/var/lib/taskchampion

volumes:
  data:
```

The compose `environment:` block renames our prefixed picklehome vars (`TASKCHAMPION_SYNC_*`) to the upstream's bare names (`CLIENT_ID`, `LISTEN`, `DATA_DIR`). No upstream patches needed.

### compose.picklelab.yaml

```yaml
services:
  taskchampion-sync:
    volumes:
      - /srv/data/taskchampion-sync:/var/lib/taskchampion
```

### Port

Default `9080`, parameterized via `TASKCHAMPION_SYNC_PORT`. `deploy.sh` sets the default and exports it; compose interpolates `${TASKCHAMPION_SYNC_PORT:?...}` and fails fast if unset. `tailscale serve` references the same var.

This mirrors the brineworks-server pattern. 8080 is avoided because it's a common collision target.

### Bind topology

Container listens on `0.0.0.0:9080` inside its network namespace; host port is mapped to `127.0.0.1:9080`. From outside picklelab, the port is unreachable directly. Only `tailscaled`'s local proxy can hit it.

## Secrets

### 1Password item: `picklehome/TaskChampion Sync`

| field | value |
|-------|-------|
| `host` | `taskchampion.tail2023b7.ts.net` |
| `client_id` | `uuidgen` output (single UUID) |
| `encryption_secret` | `openssl rand -base64 32` output |

### `.env.template` additions

```
# TASKCHAMPION_SYNC_HOST: Tailscale Services hostname
TASKCHAMPION_SYNC_HOST={{ op://picklehome/TaskChampion Sync/host }}
# TASKCHAMPION_SYNC_SERVER_CLIENT_ID: server allowlist + client identifier (UUID)
TASKCHAMPION_SYNC_SERVER_CLIENT_ID={{ op://picklehome/TaskChampion Sync/client_id }}
```

`encryption_secret` is **not** in `.env.template`. It never reaches picklelab; it's a client-side secret, materialized into the Mac's shell env via fnox.

### Trust boundary

| secret | lives on Mac | lives on picklelab |
|--------|--------------|--------------------|
| `client_id` | yes (shell env via fnox) | yes (compose env, allowlist) |
| `encryption_secret` | yes (shell env via fnox) | **no** |
| `host` | yes (shell env via fnox) | no (Tailscale handles routing by name) |

The `service-env` script enforces this split: picklelab gets only what's in `.env.vars`.

## Client (Mac) configuration

### fnox

Source of truth in 1Password; fnox materializes into shell env on startup using its keychain provider (current default per `dotfiles/fnox.toml`).

```fish
# One-time, after creating the 1Password item:
fnox set TASKCHAMPION_SYNC_SERVER_URL "https://taskchampion.tail2023b7.ts.net"
fnox set TASKCHAMPION_SYNC_SERVER_CLIENT_ID "<uuid from 1password>"
fnox set TASKCHAMPION_SYNC_ENCRYPTION_SECRET "<secret from 1password>"
```

`fnox activate fish` (already in shell startup via dotfiles) exposes them on every new shell.

### `~/.taskrc` additions

```
sync.server.url=$TASKCHAMPION_SYNC_SERVER_URL
sync.server.client_id=$TASKCHAMPION_SYNC_SERVER_CLIENT_ID
sync.encryption_secret=$TASKCHAMPION_SYNC_ENCRYPTION_SECRET
```

Taskwarrior expands `$VAR` from the environment. `.taskrc` itself stays free of secrets and could move into dotfiles later without leaking anything.

## Justfile recipes

```just
deploy-taskchampion host="picklelab":
    # follows the deploy-vikunja shape: push check, scp, systemctl install + restart

# Status: systemd + loopback + tailscale routing in one shot
taskchampion-status host="picklelab":
    #!/usr/bin/env bash
    set -uo pipefail
    echo "==> systemd unit on {{host}}"
    ssh {{host}} "sudo systemctl status taskchampion-sync.service --no-pager" || true
    echo ""
    echo "==> loopback HTTP on {{host}}"
    ssh {{host}} "curl -fsS http://127.0.0.1:9080/ -o /dev/null -w 'HTTP %{http_code}  %{time_total}s\n'" || echo "loopback FAILED"
    echo ""
    echo "==> tailscale routing (from this machine)"
    if [ -z "${TASKCHAMPION_SYNC_SERVER_URL:-}" ]; then
        echo "TASKCHAMPION_SYNC_SERVER_URL not set in shell env (fnox not loaded?)"
    else
        curl -fsS "$TASKCHAMPION_SYNC_SERVER_URL" -o /dev/null -w "HTTP %{http_code}  %{time_total}s\n" || echo "tailscale routing FAILED"
    fi

taskchampion-logs host="picklelab" lines="50":
    ssh {{host}} "sudo journalctl -u taskchampion-sync.service --no-pager -n {{lines}}"

taskchampion-logs-follow host="picklelab":
    ssh {{host}} "sudo journalctl -u taskchampion-sync.service -f"
```

The status recipe doubles as a self-test. Three HTTP codes localize any failure to systemd, tailscale, or the upstream image without manual diagnosis.

## Bootstrap order

1. Create the `TaskChampion Sync` item in 1Password (`picklehome` vault).
2. Add `TASKCHAMPION_SYNC_*` lines to `.env.template`; `just dotenv` to materialize.
3. `fnox set` the three vars on the Mac. Restart shell. Verify with `echo $TASKCHAMPION_SYNC_ENCRYPTION_SECRET`.
4. Add the three `sync.*` lines to `~/.taskrc`. Verify with `task _show | grep ^sync\.`.
5. Tailscale admin prereqs (same as Vikunja): HTTPS enabled, `tag:server` on picklelab, `taskchampion` Service defined.
6. `just deploy-taskchampion`.
7. `just taskchampion-status`: expect three OK codes.
8. `task sync`: uploads existing `~/.task` history.
9. Add the service to `homelab/services/README.md` registry.

## Backups

Container's bind mount lives under `/srv/data/taskchampion-sync/`, so the existing nightly restic job picks it up without changes. The data is a single SQLite file (plus WAL/SHM); restoring is "stop service, replace file, start."

No `pg_dump` equivalent needed.

## Risks & open questions

- **Upstream root response.** The status recipe assumes `curl http://127.0.0.1:9080/` returns *something* (likely 404). If the upstream image returns connection-refused on `/` instead, the loopback check needs to hit a known-good path. Verify on first deploy.
- **Volume override pattern.** `compose.picklelab.yaml` replaces the named volume from the base file with a bind mount. The intended override mechanism may need `volumes:` declarations in both files; will confirm during implementation.
- **fnox + keychain on a new Mac.** Recovery story is "sign into 1Password, `op read` each value, `fnox set` each value." Documented in the service README.
- **Allowlist size.** Currently one client_id. Adding a device means appending a new UUID (comma-delimited per upstream args.rs): config change, no rebuild.

## Future

- **Second device.** Add a UUID to the allowlist, set the same vars on the new device's shell, `task sync`. No server changes.
- **Tasks readable to Claude Code on the web.** Separate service, not this one. Sync server stores encrypted blobs and won't help; the right shape is an HTTP/MCP API that decrypts and exposes (or queries against a different backend like Vikunja). Out of scope here.
