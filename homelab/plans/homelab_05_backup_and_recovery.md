# Backup and Recovery

This document defines how persistent data is protected, how backups are performed, and how the homelab server can be restored after failure.

The goal is not perfect data durability or enterprise-grade disaster recovery. The goal is **fast, understandable recovery with minimal operational stress.**

---

## Backup Philosophy

The homelab treats the host as largely disposable.

Only a small set of data must be preserved:

- Persistent container state under `/srv/data`
- Infrastructure configuration under `/opt/homelab`
- Database dumps (generated pre-backup, stored alongside service data)

Everything else is rebuildable:

- Docker images
- container overlay layers
- build cache
- temporary development artifacts

Backups should be designed so that a full rebuild can be performed confidently without needing to reverse-engineer the previous system state.

---

## What Is Backed Up

### Persistent Service Data

All important container data lives in bind-mounted directories:

```
/srv/data/<service>
```

Examples:

- Home Assistant configuration and database
- application uploads or media
- database storage directories
- reverse proxy certificates or config state

This directory tree is the primary backup target.

### Infrastructure Repository

```
/opt/homelab
```

This repository contains:

- Compose definitions
- systemd unit templates
- operational scripts
- validation checks
- documentation

It is also versioned remotely on GitHub.

---

## What Is NOT Backed Up

The following paths and data are intentionally excluded:

- `/srv/docker` (Docker runtime storage)
- `/var/lib/docker`
- container image layers
- devcontainer build outputs
- ephemeral logs or temporary files

Backing up these artifacts adds complexity and slows recovery without improving resilience.

---

## Backup Tools

Backups use [restic](https://restic.net/). It provides snapshot-based, deduplicated, encrypted backups with built-in retention policies.

The backup script (`homelab/services/backup/backup.sh`) runs nightly at 3am via a systemd timer with up to 5 minutes of random delay.

---

## Backup Target

Current backup target:

- Local directory: `/srv/backups/restic`

Planned additions:

- Synology NAS on the local network
- S3-compatible cloud storage

Changing targets only requires updating `RESTIC_REPOSITORY` in the service's `.env`.

---

## Retention Policy

Restic prunes old snapshots using a grandfather-father-son (GFS) pattern:

- **7 daily** snapshots
- **4 weekly** snapshots
- **6 monthly** snapshots

Pruning runs automatically after each backup.

---

## Database Backups

Services with PostgreSQL databases get logical dumps before the restic snapshot runs. Currently dumped: Vikunja. (brineworks-server also runs Postgres but isn't dumped yet, per the [service registry](../services/README.md).)

The dump process:

1. `pg_dumpall` runs via `docker compose exec` against the service's `db` container
2. Output goes to a temp file in `/srv/data/<service>/dumps/`
3. The temp file is validated (must be non-empty)
4. On success, it's moved to `pg_dumpall.sql`, replacing the previous dump

Because dumps land inside `/srv/data`, restic picks them up automatically.

If a dump fails, the backup continues with the remaining services and the previous dump file (if any) is still included in the snapshot. The script exits with a warning so the failure is visible in logs.

---

## Operations

### Deploy or update the backup service

```
just deploy-backup
```

### Run a backup manually

```
just backup-now
```

### View recent snapshots

```
just backup-snapshots
```

### Check timer status

```
just backup-status
```

### View logs from the last run

```
just backup-logs
```

---

## Restore Procedure

The system is recoverable using the following process:

1. Install Ubuntu Server LTS on the NUC
2. Install Docker Engine and required utilities
3. Restore `/srv/data` from backup:
   ```
   restic restore latest --target /srv/data
   ```
4. Clone or restore `/opt/homelab`
5. Run bootstrap script
6. Start services via systemd

If successful, services should resume with preserved state.

---

## Testing Recovery

Recovery procedures should be validated occasionally.

Possible approaches:

- restore selected service directories to a temporary location
- verify configuration integrity
- simulate a partial rebuild in a controlled environment

Testing ensures that backups remain usable and that assumptions about restore order remain correct.

---

## Future Improvements

- Synology NAS as a backup target
- Offsite encrypted backups (S3)
- Alerting on backup failures
- Backup validation scripts

The backup system should evolve alongside operational needs, not ahead of them.

---

## Summary

The homelab backup model is intentionally simple:

- persist only what matters
- store state in predictable locations
- snapshot nightly with restic, prune automatically
- maintain a clear and documented restore path

The success criterion is confidence: the system can be rebuilt quickly without guesswork or data loss anxiety.
