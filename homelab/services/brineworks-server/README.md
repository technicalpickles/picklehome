# Brineworks Server

FastAPI REST API for managing personal contacts, interactions, relationships, and organizations. Backend for the brineworks email triage pipeline.

**Source repo:** `technicalpickles/brineworks` (private), under `server/`.

## Prerequisites (one-time)

Create a `Brineworks Server` item in the `picklehome` 1Password vault:

| Field | How to generate |
|-------|-----------------|
| `db_password` | `openssl rand -base64 32` |
| `api_key` | `openssl rand -hex 32` |

Also create a `Brineworks Server Keyring` item (a password item, field `password`) in the same vault: `openssl rand -base64 32`. It is the master password for the Gmail token keyring (see "Gmail keyring" below).

## First-time Setup

```bash
just dotenv                  # pull secrets from 1Password
just seed-brineworks-gmail   # mint the Gmail keyring (one browser consent); deploy.sh refuses to run without it
just deploy-brineworks-server
```

`deploy.sh` clones the brineworks repo to `/opt/brineworks` on first run, creates data directories, configures Tailscale serve, and starts the systemd service.

On first deploy, the Tailscale endpoint won't respond until you approve the service:

1. Open [Tailscale Services](https://login.tailscale.com/admin/services) in the admin console
2. Find `brineworks` and approve the pending host advertisement
3. Re-advertise the service (tailscaled doesn't auto-detect approval):
   ```bash
   sudo tailscale serve --service=svc:brineworks --https=443 off
   sleep 2
   sudo tailscale serve --service=svc:brineworks --https=443 "http://127.0.0.1:$BRINEWORKS_SERVER_PORT"
   ```
4. Verify: `curl https://brineworks.<tailnet>.ts.net/health`


The deploy script checks both the local and Tailscale health endpoints and prints these steps if the Tailscale endpoint isn't responding.

## Deploying Updates

```bash
just deploy-brineworks-server
```

This pulls the latest from both `picklehome` and `brineworks`, rebuilds the container image, and restarts the service. Alembic migrations run automatically on container startup.

For deploying CLI changes to the `~/brineworks-workspace` install, see [`docs/dev-vs-prod-pipeline.md`](https://github.com/technicalpickles/brineworks/blob/main/docs/dev-vs-prod-pipeline.md#deploying-changes) in the brineworks repo.

## Verifying a Deploy

```bash
curl https://brineworks.<tailnet>.ts.net/health
```

Expected response:

```json
{"status":"ok","env":"production","sha":"<short-sha>"}
```

- `status: ok` means the app is up AND the database connectivity probe inside `/health` passed (returns 503 if DB is unreachable).
- `env: production` confirms `BRINEWORKS_ENV` propagated correctly from `compose.yaml`.
- `sha` is the brineworks commit SHA baked into the image at build time via `ARG GIT_SHA` → `ENV BRINEWORKS_GIT_SHA`. It should match what `deploy.sh` printed as "Brineworks at <sha>". A mismatch means Docker served stale build layers or the build-arg didn't thread through.

## Architecture

- **Build from source:** The brineworks repo is cloned to `/opt/brineworks` on picklelab. The compose build context points at `server/` there. No published container image.
- **Compose layering:** `compose.yaml` is a portable base (`image: brineworks-server:local`). `compose.picklelab.yaml` adds the `build:` directive, loopback port binding, and host volume mounts. Docker Compose merges both: it builds from source and tags the result.
- **Networking:** Server binds to `127.0.0.1:$BRINEWORKS_SERVER_PORT` (loopback only, default `8765`). Tailscale serve proxies `https://brineworks.<tailnet>.ts.net` to it. The `tailscale serve` rule is reapplied unconditionally on every deploy: re-running with a different upstream idempotently replaces the previous rule, no manual `off` needed.
- **Port configuration:** The server port is controlled by one env var, `BRINEWORKS_SERVER_PORT`, threaded end-to-end. `deploy.sh` sets it once at the top (default `8765`) and exports it. Compose files fail fast (`${BRINEWORKS_SERVER_PORT:?...}`) if it's unset. The brineworks image bakes `ENV BRINEWORKS_SERVER_PORT=8765` so containers without an explicit override still work. To change the port, set `BRINEWORKS_SERVER_PORT` in the environment before running `deploy.sh`. Full decision record with alternatives considered: [brineworks `docs/decisions/0001-server-port-configuration.md`](https://github.com/technicalpickles/brineworks/blob/main/docs/decisions/0001-server-port-configuration.md).
- **Healthcheck layering:** Two independent probes catch different failure modes. The container healthcheck is declared in the brineworks `Dockerfile` (`python -m brineworks_server.healthcheck`) and reads the port from its own ENV, so the image is self-contained. It catches "uvicorn crashed or hung." The `deploy.sh` end-to-end curl against the published port catches "container is healthy but the port publish is wrong" (e.g. the port drift we hit on 2026-04-11).

## Environment Variables

Injected from the root `.env` via `compose.picklelab.yaml`:

| Variable | Description |
|----------|-------------|
| `BRINEWORKS_DB_PASSWORD` | Postgres password (shared between db and server containers) |
| `BRINEWORKS_API_KEY` | Bearer token for API authentication (all endpoints except /health) |
| `BRINEWORKS_SERVER_KEYRING_PASSWORD` | Master password for the Gmail token keyring. Set in the container as `KEYRING_CRYPTFILE_PASSWORD`; the `.env` name differs because that one is the agent's. |

`BRINEWORKS_KEYRING_FILE` (`/keyring/cryptfile.cfg`) is set directly in `compose.picklelab.yaml` (not a secret).

The database URL is derived in `compose.yaml`: `postgresql+asyncpg://brineworks:<password>@db:5432/brineworks`.

### Tailscale identity auth

Set directly in `compose.picklelab.yaml` (neither is a secret, so neither goes through 1Password):

| Variable | Description |
|----------|-------------|
| `BRINEWORKS_TRUST_TAILSCALE_HEADERS` | Trust Serve's `Tailscale-User-Login` header as an auth path. Defaults to **false**. |
| `BRINEWORKS_ALLOWED_LOGINS` | Comma-separated tailnet logins allowed to authenticate that way (a JSON list also works). |

These live in the picklelab overlay rather than the portable `compose.yaml` on purpose: they are only safe alongside the loopback-only port binding, which is defined there too. The base compose should not assert a Tailscale topology it cannot guarantee. **Read the port-binding comment in `compose.picklelab.yaml` before changing how this service is published** -- the loopback binding is what makes header trust safe (see the `tailscale-serve-patterns` skill for the general reasoning and failure modes: Docker port publish, a reverse proxy, or any other path that reaches the port without going through Serve can forge the identity header).

**Turning the flag on with an empty `BRINEWORKS_ALLOWED_LOGINS` makes the server refuse to start**, deliberately. A config that reads as "identity auth enabled" but authenticates nobody is worse than a loud failure at boot (ops principle #1). Because the container CMD is `alembic upgrade head && uvicorn`, the migration step is what dies first.

The API key stays required regardless. Tagged devices never receive identity headers, so `brineworks-agent` authenticates by key permanently, not transitionally.

Verify a rollout by watching `brineworks.auth` lines in the container log (`just brineworks-server-logs`): browser traffic shows `identity_kind=user`, the agent shows `identity_kind=key`.

Full design: brineworks `docs/decisions/0007-tailscale-identity-auth.md`.

## Gmail keyring (required in production)

The MCP email tools read Gmail through a cryptfile keyring at `/keyring/cryptfile.cfg`. The server refuses to start in production without a usable token, so `deploy.sh` refuses to deploy without the file. Seed it from the Mac:

```bash
just seed-brineworks-gmail
```

This reads the keyring password from the `Brineworks Server Keyring` 1Password item, runs `bw email auth` (one browser consent, MODIFY scopes) into a temporary cryptfile keyring under key prefix `agent` (what the server image pins), verifies it with `bw email auth --check`, copies it to the host, and keeps the previous file as `cryptfile.cfg.bak`. Re-run it whenever the refresh token dies. The script needs `bw` (set `BW=` if it isn't on PATH; the default falls back to the brineworks venv) and 1Password unlocked.

The keyring directory is root-owned mode 700 and the container runs as root, so no chown is involved; the mount is the directory (not the file) because token refresh writes back.

Rollback note: migrations `0009` and `0010` (triage rules, triage apply results) are additive, but code from before them cannot start on a database stamped `0010`, because alembic cannot locate the revision. Back out by running `alembic downgrade 0008` from the new image first. That drops `triage_rules` and apply history, so export rules first (`bw email rules export`).

## API

- `GET /health`: returns `{"status": "ok"}` if DB is reachable, 503 otherwise
- `GET /docs`: Swagger UI
- Resources: `/contacts`, `/contact_info`, `/interactions`, `/relationships`, `/organizations`, `/contexts`, `/locations`, `/links`
- Special: `POST /contacts/get-or-create-by-info`, `POST /contacts/{id}/promote`, `POST /contacts/{id}/archive`, `GET /contacts/triage`

## Client Config

The brineworks CLI (`bw email sync-prm`) targets the server via env vars in the brineworks repo's `.env`:

```
BRINEWORKS_SERVER_URL=https://brineworks.<tailnet>.ts.net
BRINEWORKS_API_KEY=<same key as server>
```

## Data Locations (on picklelab)

```
/opt/brineworks/                    # brineworks repo clone
/srv/data/brineworks-server/db/     # Postgres data directory
/srv/data/brineworks-server/keyring/  # cryptfile Gmail token keyring (root, 0700 dir / 0600 file)
/srv/data/brineworks-server/dumps/  # pg_dumpall for backups (future)
```
