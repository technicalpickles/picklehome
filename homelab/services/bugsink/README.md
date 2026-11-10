# Bugsink

Self-hosted error tracker for the Brent stack. Speaks the Sentry SDK protocol, groups events into issues, and tracks resolve and regress. brineworks-server reports its own exceptions here, and brined-almanac ships Brent's failed tool calls here. Almanac polls it to decide when to file a GitHub issue.

Why Bugsink and not GlitchTip or Sentry self-hosted: the brined-almanac plan `docs/superpowers/plans/2026-11-09-error-tracker.md` (Appendix B).

## Architecture

- **Images:** `bugsink/bugsink` and `postgres:16-alpine`, both pinned by version and digest in `compose.yaml`. The web container runs gunicorn plus Bugsink's `snappea` worker, as uid 14237 (image default). It writes nothing to a bind mount: snappea's queue is in the container's `/tmp`.
- **Database:** Postgres, per Bugsink's docs (they advise against SQLite on a Docker volume). Raw data at `/srv/data/bugsink/db`, owned by the postgres image's own uid.
- **Networking:** web binds `127.0.0.1:8380` (`BUGSINK_PORT`), and `tailscale serve --service=svc:bugsink` proxies `https://bugsink.<tailnet>.ts.net` to it. Tailnet only.
- **TLS behind the proxy:** `BEHIND_HTTPS_PROXY=true`. Django checks the login form's `Origin` against the scheme it sees, so it relies on tailscaled sending `X-Forwarded-Proto: https`. Without that header, login fails with "Origin header does not match (deduced) Host ... (wrong scheme)".
- **Phone-home:** off (`PHONEHOME=false`).
- **Users:** `SINGLE_USER`, `SINGLE_TEAM`, registration off. `CREATE_SUPERUSER` makes the first login on the first start and does nothing once a user exists.

## Retention

`/srv` is 30G and shared, so both caps are set in `compose.yaml`:

| Cap | Setting | Enforced by |
|---|---|---|
| 10,000 stored events per project | `MAX_RETENTION_PER_PROJECT_EVENT_COUNT` | Bugsink at ingest. A project's own setting can't go above it. |
| 90 days | `MAX_EVENT_AGE_DAYS` | `bugsink-vacuum.timer`, daily at 04:30. Bugsink only applies the age cap when `vacuum --old-events` runs. |

The spike stored 358 events in 2.8 MB, so the event cap binds long before disk does.

## Secrets

1Password item `Bugsink` in the `picklehome` vault. Create it **before** this lands on `main`: `op inject` fails the whole `.env.template` on a missing item, which breaks `just dotenv` for every module.

| Field | Value |
|---|---|
| `secret_key` | `openssl rand -hex 32` |
| `db_password` | `openssl rand -hex 32` (hex, because it sits inside `DATABASE_URL` unescaped) |
| `admin_email` | the login name |
| `admin_password` | anything strong |

`BUGSINK_PORT` and `BUGSINK_BASE_URL` are not secrets. `deploy.sh` writes them to `.env.build`, with the base URL built from the host's tailnet name.

## First deploy

1. Create the 1Password item above.
2. Define a `bugsink` Service at https://login.tailscale.com/admin/services with port 443.
3. `just deploy-bugsink`. It prints the approve-and-re-advertise steps if the tailnet endpoint doesn't answer yet.
4. `just deploy-backup`, so the `backup` user owns `/srv/data/bugsink/dumps`. Until both deploys have run, the nightly backup's `dump_postgres "bugsink"` fails and marks `backup.service` red.
5. `just bugsink-verify` prints PASS.
6. Log in, create the projects and an API token (Bugsink UI, or `docker exec bugsink-web-1 bugsink-manage create_auth_token`).

## Commands

```bash
just deploy-bugsink    # deploy or update
just bugsink-verify    # health, pinned version, Postgres, vacuum timer, login page over the tailnet
just bugsink-logs      # last 50 lines of the web container
```

## Local run

Throwaway values, nothing from 1Password. `BUGSINK_BEHIND_HTTPS_PROXY=false` lets the login work over plain http:

```bash
cd homelab/services/bugsink
BUGSINK_DB_PASSWORD=$(openssl rand -hex 24) BUGSINK_SECRET_KEY=$(openssl rand -hex 40) \
BUGSINK_ADMIN_EMAIL=admin@example.org BUGSINK_ADMIN_PASSWORD=change-me \
BUGSINK_BASE_URL=http://localhost:8380 BUGSINK_PORT=8380 BUGSINK_BEHIND_HTTPS_PROXY=false \
docker compose -p bugsink-local up -d --wait
```

`docker compose -p bugsink-local down -v` removes it, database included.

## Upgrading

Bump the tag and digest together in `compose.yaml`, read Bugsink's release notes for migrations, deploy, and run `just bugsink-verify`, which fails until the running version matches the pin.

## Data locations (on picklelab)

```
/opt/homelab/homelab/services/bugsink/   # service files, .env.build, .env.op.template
/srv/data/bugsink/db/                    # raw Postgres data (excluded from restic)
/srv/data/bugsink/dumps/pg_dumpall.sql   # nightly dump, backed up by restic
```
