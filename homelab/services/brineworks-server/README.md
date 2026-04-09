# Brineworks Server

FastAPI REST API for managing personal contacts, interactions, relationships, and organizations. Backend for the brineworks email triage pipeline.

**Source repo:** `technicalpickles/brineworks` (private), under `server/`.

## Prerequisites (one-time)

Create a `Brineworks Server` item in the `picklehome` 1Password vault:

| Field | How to generate |
|-------|-----------------|
| `db_password` | `openssl rand -base64 32` |
| `api_key` | `openssl rand -hex 32` |

## First-time Setup

```bash
just dotenv          # pull secrets from 1Password
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
   sudo tailscale serve --service=svc:brineworks --https=443 http://127.0.0.1:8000
   ```
4. Verify: `curl https://brineworks.<tailnet>.ts.net/health`


The deploy script checks both the local and Tailscale health endpoints and prints these steps if the Tailscale endpoint isn't responding.

## Deploying Updates

```bash
just deploy-brineworks-server
```

This pulls the latest from both `picklehome` and `brineworks`, rebuilds the container image, and restarts the service. Alembic migrations run automatically on container startup.

## Architecture

- **Build from source:** The brineworks repo is cloned to `/opt/brineworks` on picklelab. The compose build context points at `server/` there. No published container image.
- **Compose layering:** `compose.yaml` is a portable base (`image: brineworks-server:local`). `compose.picklelab.yaml` adds the `build:` directive, loopback port binding, and host volume mounts. Docker Compose merges both: it builds from source and tags the result.
- **Networking:** Server binds to `127.0.0.1:8000` (loopback only). Tailscale serve proxies `https://brineworks.<tailnet>.ts.net` to it.

## Environment Variables

Injected from the root `.env` via `compose.picklelab.yaml`:

| Variable | Description |
|----------|-------------|
| `BRINEWORKS_DB_PASSWORD` | Postgres password (shared between db and server containers) |
| `BRINEWORKS_API_KEY` | Bearer token for API authentication (all endpoints except /health) |

The database URL is derived in `compose.yaml`: `postgresql+asyncpg://brineworks:<password>@db:5432/brineworks`.

## API

- `GET /health`: returns `{"status": "ok"}` if DB is reachable, 503 otherwise
- `GET /docs`: Swagger UI
- Resources: `/contacts`, `/contact_info`, `/interactions`, `/relationships`, `/organizations`, `/contexts`, `/locations`, `/links`
- Special: `POST /contacts/get-or-create-by-info`, `POST /contacts/{id}/promote`, `POST /contacts/{id}/archive`, `GET /contacts/triage`

## Client Config

The brineworks CLI (`bw email sync-prm`) targets the server via env vars in the brineworks repo's `.env`:

```
BRINEWORKS_PRM_URL=https://brineworks.<tailnet>.ts.net
BRINEWORKS_API_KEY=<same key as server>
```

## Data Locations (on picklelab)

```
/opt/brineworks/                    # brineworks repo clone
/srv/data/brineworks-server/db/     # Postgres data directory
/srv/data/brineworks-server/dumps/  # pg_dumpall for backups (future)
```
