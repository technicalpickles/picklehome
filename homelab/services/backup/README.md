# Backup

Nightly restic backups of `/srv/data` with Postgres database dumps. Runs as a dedicated `backup` system user via systemd timer at 3am.

## What's backed up

Everything under `/srv/data`, except the raw Postgres data directories (backed up via SQL dumps instead) and the dev-container home.

| Service | Captured | How |
|---------|----------|-----|
| [vikunja](../vikunja/README.md) | database + file attachments | `pg_dumpall` → `/srv/data/vikunja/dumps/pg_dumpall.sql`, then restic snapshots the whole `/srv/data/vikunja/` tree |
| climate-auto-switch | OAuth tokens, last-state, run log | restic snapshots `/srv/data/climate-auto-switch/` directly (flat files, no database) |

## Retention

GFS (grandfather-father-son) retention, pruned automatically after each run:

- **7 daily** snapshots
- **4 weekly** snapshots
- **6 monthly** snapshots

## Backup target

Currently: local directory `/srv/backups/restic` on the NUC's own SSD.

This is intentionally phase 1. Future work:
- **Synology NAS** on the LAN (when online) — change `RESTIC_REPOSITORY` in 1Password, re-init
- **S3 offsite** as a second repo for disaster recovery

## Prerequisites (one-time)

Create a `Restic Backup` item in the `picklehome` 1Password vault:

| field | value |
|-------|-------|
| `repository` | `/srv/backups/restic` (local for now) |
| `password` | generate with `openssl rand -base64 32` — **losing this means losing all backups** |

## First-time Setup

```bash
just dotenv          # pull restic secrets from 1Password
just deploy-backup   # install restic, create backup user, set up ACLs, init repo, enable timer
```

`deploy.sh` is idempotent. It creates the `backup` system user (in `docker` group so `docker exec` works for pg_dump), sets up ACLs on service data dirs (so the backup user can read files owned by container UIDs), and initializes the restic repo if not already initialized.

## Deploying Updates

```bash
just deploy-backup
```

## Running Backups

```bash
just backup-now          # manual trigger
just backup-snapshots    # list snapshots
just backup-status       # timer status + next run
just backup-logs         # last 50 lines of service journal
```

## How Database Dumps Work

The script uses `docker exec` with a container lookup via compose labels, rather than `docker compose exec`, so it doesn't need read access to service `.env` files:

```bash
docker ps --filter "label=com.docker.compose.project=vikunja" \
          --filter "label=com.docker.compose.service=db" \
          --format '{{.Names}}'
```

Dumps land inside `/srv/data/<service>/dumps/pg_dumpall.sql`, so the single `restic backup /srv/data` picks them up alongside file data. Dumps write to a temp file and only `mv` into place on success, so a failed dump preserves the previous good one.

A dump failure doesn't block the rest of the backup: restic still runs, other dumps still run, and the script exits non-zero so systemd marks the run as failed for operator visibility.

## Restore

Restores use `restic restore`. The restic repo and password are in 1Password (`op://picklehome/Restic Backup`).

```bash
# On the target host, after installing restic and pulling secrets:
source /opt/homelab/homelab/services/backup/.env
sudo -u backup -E restic snapshots             # list available snapshots
sudo -u backup -E restic restore latest --target /srv/data
```

Database dumps inside the restored tree can be replayed into a fresh Postgres with:

```bash
cat /srv/data/vikunja/dumps/pg_dumpall.sql | docker exec -i vikunja-db-1 psql -U vikunja
```

## Data Locations (on picklelab)

```
/srv/backups/restic/         — restic repository (snapshots, encrypted)
/srv/backups/restic-cache/   — restic cache (owned by backup user, safe to delete)
/srv/data/<service>/dumps/   — per-service SQL dumps (rewritten each run)
```

## Security Model

- Backup runs as the `backup` system user (no login shell, `/var/backups` home)
- Member of `docker` group (effectively root-equivalent, but that's the nature of Docker access)
- `RESTIC_REPOSITORY` and `RESTIC_PASSWORD` injected via systemd `EnvironmentFile` from `.env`
- ACLs grant read-only access to service data without changing file ownership
- Restic encrypts all snapshots at rest — safe to ship the repo offsite
