# Homelab Backup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Nightly restic backups of all homelab service data with pg_dump for database consistency and GFS retention policy.

**Architecture:** A backup script dumps each Postgres database to a file inside its service's data directory, then runs `restic backup` over all of `/srv/data`. A systemd timer triggers nightly. Restic handles snapshots, dedup, encryption, and retention (7 daily, 4 weekly, 6 monthly). The restic repo starts as a local directory (`/srv/backups/restic`) for initial testing, with Synology NAS and S3 as future targets (just change the `-r` flag).

**Tech Stack:** restic, pg_dumpall (via `docker compose exec`), bash, systemd timer

---

## Data Map

| Service | Postgres? | User | Data path | Dump target |
|---------|-----------|------|-----------|-------------|
| vikunja | yes | `vikunja` | `/srv/data/vikunja/` | `/srv/data/vikunja/dumps/` |
| baserow | yes | `baserow` | `/srv/data/baserow/` | `/srv/data/baserow/dumps/` |
| climate-auto-switch | no | n/a | `/srv/data/climate-auto-switch/` | n/a (flat files) |

Dumps land inside `/srv/data/` so the single `restic backup /srv/data` picks up everything: live data, file attachments, flat-file state, and database dumps.

---

## Task 1: Create the backup script

**Files:**
- Create: `homelab/services/backup/backup.sh`

This is the core of the whole system. It does three things in order:
1. Dump each Postgres database to a SQL file
2. Run `restic backup` on `/srv/data`
3. Apply the GFS retention policy with `restic forget --prune`

**Step 1: Write the backup script**

```bash
#!/usr/bin/env bash
# Nightly backup: dump databases, snapshot /srv/data with restic, prune old snapshots.
set -euo pipefail

BACKUP_TAG="nightly"
DATA_DIR="/srv/data"

# --- Database dumps ---
# Each dump lands in the service's data dir so restic picks it up automatically.

dump_postgres() {
    local service_dir="$1"
    local compose_project_dir="$2"
    local db_user="$3"
    local dump_dir="$DATA_DIR/$service_dir/dumps"

    mkdir -p "$dump_dir"

    echo "==> Dumping $service_dir postgres (user: $db_user)"
    docker compose \
        -f "$compose_project_dir/compose.yaml" \
        -f "$compose_project_dir/compose.picklelab.yaml" \
        exec -T db pg_dumpall -U "$db_user" \
        > "$dump_dir/pg_dumpall.sql"

    echo "    $(wc -c < "$dump_dir/pg_dumpall.sql") bytes written"
}

REPO_DIR="/opt/homelab/homelab/services"

dump_postgres "vikunja" "$REPO_DIR/vikunja" "vikunja"
dump_postgres "baserow" "$REPO_DIR/baserow" "baserow"

# --- Restic backup ---
echo "==> Running restic backup"
restic backup "$DATA_DIR" --tag "$BACKUP_TAG"

# --- Retention ---
echo "==> Pruning old snapshots"
restic forget \
    --tag "$BACKUP_TAG" \
    --keep-daily 7 \
    --keep-weekly 4 \
    --keep-monthly 6 \
    --prune

echo "==> Backup complete"
restic snapshots --tag "$BACKUP_TAG" --latest 3
```

**Step 2: Make it executable**

Run: `chmod +x homelab/services/backup/backup.sh`

**Step 3: Commit**

```
feat(backup): add restic backup script with pg_dump and GFS retention
```

---

## Task 2: Create the systemd units

**Files:**
- Create: `homelab/services/backup/backup.service`
- Create: `homelab/services/backup/backup.timer`

Follows the same pattern as climate-auto-switch: a oneshot service triggered by a timer.

**Step 1: Write the service unit**

```ini
[Unit]
Description=Restic backup of /srv/data (with database dumps)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
EnvironmentFile=/opt/homelab/homelab/services/backup/.env
ExecStart=/opt/homelab/homelab/services/backup/backup.sh

# Restic needs these from the environment
# RESTIC_REPOSITORY — path or s3:// URL
# RESTIC_PASSWORD  — repo encryption password
```

`EnvironmentFile` injects `RESTIC_REPOSITORY` and `RESTIC_PASSWORD` so the backup script doesn't need to hardcode them. Restic reads these env vars natively.

**Step 2: Write the timer unit**

```ini
[Unit]
Description=Run nightly backup at 3am

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

`Persistent=true` means if the NUC was off at 3am, the backup runs as soon as it boots. `RandomizedDelaySec=300` jitters up to 5 minutes to avoid thundering herd if you ever add more timers.

**Step 3: Commit**

```
feat(backup): add systemd service and timer for nightly backup
```

---

## Task 3: Add secrets to 1Password and .env

**Files:**
- Create: `homelab/services/backup/.env.vars`
- Modify: `.env.template`

The restic repo password is the one secret here. It encrypts everything in the restic repo, so losing it means losing your backups. It goes in 1Password like everything else.

**Step 1: Create the .env.vars file**

```
RESTIC_REPOSITORY
RESTIC_PASSWORD
```

**Step 2: Add entries to .env.template**

Add after the existing entries:

```
# Backup (restic)
RESTIC_REPOSITORY={{ op://picklehome/Restic Backup/repository }}
RESTIC_PASSWORD={{ op://picklehome/Restic Backup/password }}
```

**Step 3: Create the 1Password item**

This is a manual step. Create a "Restic Backup" item in the picklehome vault with:
- `repository` field: `/srv/backups/restic` (local path for now, change to `s3:s3.amazonaws.com/bucket-name` later)
- `password` field: generate a strong random password

**Step 4: Regenerate .env**

Run: `just dotenv`

**Step 5: Commit**

```
feat(backup): add restic secrets to env template and .env.vars
```

---

## Task 4: Create the deploy script

**Files:**
- Create: `homelab/services/backup/deploy.sh`

Follows the exact same pattern as vikunja and baserow deploy scripts: create dirs, link units, enable timer.

**Step 1: Write deploy.sh**

```bash
#!/usr/bin/env bash
# Deploy backup service on picklelab.
# Idempotent: safe to run on first setup or any subsequent deploy.
# Run from the repo root on the target host.
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/backup"
BACKUP_DIR=/srv/backups/restic

cd "$REPO_DIR"

echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Installing restic"
if ! command -v restic &> /dev/null; then
    sudo apt-get update && sudo apt-get install -y restic
fi

echo "==> Creating backup directory"
sudo mkdir -p "$BACKUP_DIR"

echo "==> Initializing restic repo (if needed)"
# Source the env file for RESTIC_REPOSITORY and RESTIC_PASSWORD
set -a
source "$SERVICE_DIR/.env"
set +a
if ! restic snapshots &> /dev/null; then
    echo "    Initializing new restic repository at $RESTIC_REPOSITORY"
    restic init
else
    echo "    Restic repository already initialized"
fi

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/backup.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/backup.timer" /etc/systemd/system/

echo "==> Reloading systemd and enabling timer"
sudo systemctl daemon-reload
sudo systemctl enable backup.timer
sudo systemctl restart backup.timer

echo "==> Status"
systemctl status backup.timer --no-pager

echo ""
echo "Done! Next run:"
systemctl list-timers backup.timer --no-pager
```

**Step 2: Make it executable**

Run: `chmod +x homelab/services/backup/deploy.sh`

**Step 3: Commit**

```
feat(backup): add deploy script for backup service
```

---

## Task 5: Add Justfile tasks

**Files:**
- Modify: `Justfile`

Add deployment task and operational tasks matching the patterns of other services.

**Step 1: Add the deploy task and operational commands**

Add to the Justfile:

```just
# Deploy backup service to picklelab (idempotent: first setup or update)
deploy-backup host="picklelab":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -n "$(git status --porcelain)" ]; then
        echo "ERROR: uncommitted changes. Commit or stash first."
        exit 1
    fi
    BRANCH=$(git branch --show-current)
    if [ "$BRANCH" != "main" ]; then
        echo "ERROR: not on main (on $BRANCH). Switch to main first."
        exit 1
    fi
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Pushing to origin/main..."
        git push
    fi
    echo "Deploying commit $(git rev-parse --short HEAD) to {{host}}"
    echo "==> Copying .env to {{host}}"
    mkdir -p tmp
    scripts/service-env homelab/services/backup/.env.vars > tmp/backup.env
    scp tmp/backup.env {{host}}:/opt/homelab/homelab/services/backup/.env
    rm tmp/backup.env
    ssh -t {{host}} "cd /opt/homelab && git pull && homelab/services/backup/deploy.sh"

# Run backup now on picklelab (manual trigger)
backup-now host="picklelab":
    ssh -t {{host}} "sudo systemctl start backup.service"

# Show recent restic snapshots from picklelab
backup-snapshots host="picklelab":
    ssh {{host}} "set -a && source /opt/homelab/homelab/services/backup/.env && restic snapshots --tag nightly"

# Show backup timer status on picklelab
backup-status host="picklelab":
    ssh {{host}} "systemctl status backup.timer --no-pager && echo '' && systemctl list-timers backup.timer --no-pager"

# Show backup service logs (last run output)
backup-logs host="picklelab" lines="50":
    ssh {{host}} "journalctl -u backup.service --no-pager -n {{lines}}"
```

**Step 2: Commit**

```
feat(backup): add Justfile tasks for deploy, run, snapshots, status, logs
```

---

## Task 6: Update the backup plan doc

**Files:**
- Modify: `homelab/plans/homelab_05_backup_and_recovery.md`

Update to reflect actual implementation rather than aspirational "we might do this" language.

**Step 1: Update the doc**

Key changes:
- Backup Tools section: replace rsync/restic comparison with "we use restic"
- Add the concrete retention policy (7 daily, 4 weekly, 6 monthly)
- Add the pg_dump approach as the chosen strategy
- Add a "Running backups" operational section
- Update the restore procedure with restic restore commands
- Note the local-first approach with S3 as planned addition

**Step 2: Commit**

```
docs(backup): update plan to reflect restic implementation
```

---

## Task 7: Test the whole flow

This runs on picklelab. It's the "does it actually work" task.

**Step 1: Deploy**

Run: `just deploy-backup`

Verify: deploy.sh completes, restic repo initializes, timer is active.

**Step 2: Trigger a manual backup**

Run: `just backup-now`

Then check: `just backup-logs`

Verify: both pg_dump lines show non-zero byte counts, restic backup completes, forget/prune runs.

**Step 3: Verify snapshots**

Run: `just backup-snapshots`

Verify: one snapshot exists with the "nightly" tag.

**Step 4: Verify a dump is restorable**

Run on picklelab:
```bash
# Peek at the vikunja dump
head -20 /srv/data/vikunja/dumps/pg_dumpall.sql
```

Should show valid SQL starting with `--` comments and `SET` statements.

**Step 5: Verify restic can restore**

Run on picklelab:
```bash
# Dry-run: list files in latest snapshot
source /opt/homelab/homelab/services/backup/.env
restic ls latest --tag nightly | head -30
```

Should show the `/srv/data/` tree including dumps.

**Step 6: Commit any fixes from testing**

---

## Future Work (not in this plan)

- **Synology NAS target**: Mount via NFS/SMB, change `RESTIC_REPOSITORY` to NAS path
- **S3 offsite**: Add a second restic repo targeting S3, run both in backup.sh
- **Backup health alerting**: Post to Slack or pushover on failure (check exit code in a wrapper)
- **Restore runbook**: Detailed step-by-step restore-from-restic tested on a fresh host
- **Backup verification cron**: Weekly `restic check` to verify repo integrity
