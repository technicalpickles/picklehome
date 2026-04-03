# Vikunja

Self-hosted task manager. Three containers managed as a single systemd service:

- **Postgres 16** — database
- **Vikunja** — app server + frontend (port 3456 internally)
- **Caddy** — TLS termination via Tailscale-provisioned certs, reverse proxy

Accessible at `https://$VIKUNJA_HOST` from any device on the Tailscale tailnet (including on the LAN — Tailscale routes traffic directly without hairpinning).

## Prerequisites (one-time)

1. **Enable HTTPS in Tailscale admin:** https://login.tailscale.com/admin/dns → toggle "Enable HTTPS certificates"

2. **Create a `Vikunja` item in the `picklehome` 1Password vault** with these fields:

   | field | how to get it |
   |-------|---------------|
   | `host` | Run `just tailscale-dns` on picklelab, e.g. `picklelab.tail1234.ts.net` |
   | `db_password` | `openssl rand -base64 32` |
   | `jwt_secret` | `openssl rand -base64 32` |

## First-time Setup

```bash
just dotenv          # pull secrets from 1Password into .env
just push-env        # sync .env to picklelab
just deploy-vikunja  # provision cert, create data dirs, install + start systemd unit
```

`deploy.sh` is idempotent — safe to re-run.

## Deploying Updates

```bash
just deploy-vikunja
```

Pulls latest images on the host (`--pull always` in the systemd unit), restarts containers.

## Logs

```bash
just vikunja-logs              # last 50 lines from all containers
just vikunja-logs-follow       # live tail
ssh picklelab "sudo journalctl -u vikunja.service -n 50"
```

## TLS Cert Renewal

Tailscale certs are valid for 90 days. Re-running `tailscale cert` refreshes the files in place; Caddy picks up the change automatically.

```bash
ssh picklelab "source /opt/homelab/.env && sudo tailscale cert \
  --cert-file=/srv/certs/\$VIKUNJA_HOST.crt \
  --key-file=/srv/certs/\$VIKUNJA_HOST.key \
  \$VIKUNJA_HOST"
```

## API

- Base URL: `https://$VIKUNJA_HOST/api/v1`
- Docs (Swagger UI): `https://$VIKUNJA_HOST/api/v1/docs`
- **Login endpoint:** `POST /api/v1/login` — note: NOT `/api/v1/user/login` (returns 404)
- **Auth for automation:** create an API token in Settings → API Tokens; pass as `Authorization: Bearer <token>`
- **Inbox project** is always id=1, auto-created on first login; all 4 views (List, Gantt, Table, Kanban) are created automatically

## Local Testing

Requires `homelab/services/vikunja/.env` (gitignored) with:

```
VIKUNJA_DB_PASSWORD=localtest
VIKUNJA_JWT_SECRET=localtest-jwt-secret-not-for-production
VIKUNJA_HOST=localhost
```

```bash
just vikunja-validate      # check compose config syntax
just vikunja-local-up      # start Postgres + Vikunja locally on :3456 (no Caddy/TLS)
just vikunja-local-down    # tear down and remove volumes
```

## Data Locations (on picklelab)

```
/srv/data/vikunja/db/               — Postgres data directory
/srv/data/vikunja/files/            — file attachments (must be owned by UID 1000)
/srv/data/vikunja/caddy/            — Caddy data
/srv/data/vikunja/caddy-config/     — Caddy config
/srv/certs/$VIKUNJA_HOST.crt        — Tailscale TLS certificate
/srv/certs/$VIKUNJA_HOST.key        — Tailscale TLS private key
```

## Config Reference

Vikunja uses Viper with prefix `VIKUNJA_` and dot-to-underscore mapping. Key vars:

| env var | config key | notes |
|---------|-----------|-------|
| `VIKUNJA_SERVICE_PUBLICURL` | `service.publicurl` | required when CORS is enabled |
| `VIKUNJA_SERVICE_SECRET` | `service.secret` | JWT signing key (`VIKUNJA_SERVICE_JWTSECRET` is deprecated) |
| `VIKUNJA_DATABASE_TYPE` | `database.type` | `postgres` |
| `VIKUNJA_DATABASE_HOST` | `database.host` | container name `db` |
| `VIKUNJA_DATABASE_USER` | `database.user` | |
| `VIKUNJA_DATABASE_PASSWORD` | `database.password` | |
| `VIKUNJA_DATABASE_DATABASE` | `database.database` | |

Source of truth for all config keys: `vendor/vikunja/pkg/config/config.go`.
