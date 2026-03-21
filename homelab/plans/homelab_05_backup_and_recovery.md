# Backup and Recovery

This document defines how persistent data is protected, how backups are performed, and how the homelab server can be restored after failure.

The goal is not perfect data durability or enterprise-grade disaster recovery. The goal is **fast, understandable recovery with minimal operational stress.**

---

## Backup Philosophy

The homelab treats the host as largely disposable.

Only a small set of data must be preserved:

- Persistent container state under `/srv/data`
- Infrastructure configuration under `/opt/homelab`
- Optional database dumps or exported service state

Everything else is rebuildable:

- Docker images
- container overlay layers
- build cache
- temporary development artifacts

Backups should be designed so that a full rebuild can be performed confidently without needing to reverse-engineer the previous system state.

---

## What Is Backed Up

### Persistent Service Data

All important container data must live in bind-mounted directories:

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

It should also be versioned remotely (e.g., GitHub or private Git service).

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

## Backup Target

Primary backup target:

- Synology NAS on the local network

Backups are expected to run over the LAN and should not depend on public internet connectivity.

Future evolution may include:

- encrypted offsite backups
- snapshot replication
- cloud object storage

---

## Backup Tools

### Initial Approach: rsync

A simple nightly job can synchronize persistent data:

Example:

```
rsync -a --delete /srv/data/ synology:/volume1/backups/nuc-data/
```

Advantages:

- easy to understand
- easy to debug
- fast over LAN
- minimal setup

Tradeoffs:

- no built-in snapshotting or retention
- risk of propagating accidental deletions
- limited visibility into historical states

This approach is acceptable as a starting point.

### Evolved Approach: restic

Restic is a likely upgrade path once the system stabilizes.

Benefits:

- snapshot-based backups
- deduplication
- retention policies
- encryption by default
- easier migration to offsite storage

Example workflow:

```
restic backup /srv/data
```

Restic repositories can live on:

- mounted Synology storage
- S3-compatible endpoints
- cloud backup providers

---

## Database Backup Considerations

Some services (e.g., PostgreSQL, MariaDB) may require consistent backups.

Options include:

### Application-Level Dumps (Preferred)

Example:

```
docker exec postgres pg_dumpall > /srv/backups/postgres.sql
```

Advantages:

- consistent logical backup
- portable restore
- simple validation

### Filesystem-Level Backups (Acceptable for Homelab)

Backing up bind-mounted data directories while containers are running is often sufficient for lightweight services.

This carries some risk of inconsistent state but is usually acceptable in non-critical environments.

---

## Restore Procedure

The system should be recoverable using the following high-level process:

1. Install Ubuntu Server LTS on the NUC
2. Install Docker Engine and required utilities
3. Restore `/srv/data` from backup
4. Clone or restore `/opt/homelab`
5. Run bootstrap script
6. Start services via systemd or wrapper commands

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

## Operational Safeguards

To reduce backup-related risk:

- monitor disk usage regularly
- ensure backup jobs are scheduled and logged
- alert on backup failures where practical
- avoid storing critical state outside `/srv/data`

Backup discipline is more important than backup sophistication.

---

## Future Improvements

Potential enhancements include:

- retention policies for multiple restore points
- offsite encrypted backups
- automated database dump workflows
- LVM snapshot-based backup consistency
- backup validation scripts

The backup system should evolve alongside operational needs, not ahead of them.

---

## Summary

The homelab backup model is intentionally simple:

- persist only what matters
- store state in predictable locations
- back up to a reliable local NAS
- maintain a clear and documented restore path

The success criterion is confidence: the system can be rebuilt quickly without guesswork or data loss anxiety.

