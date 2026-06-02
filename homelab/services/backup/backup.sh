#!/usr/bin/env bash
# Nightly backup: dump databases, snapshot /srv/data with restic, prune old snapshots.
set -uo pipefail

BACKUP_TAG="nightly"
DATA_DIR="/srv/data"

# --- Database dumps ---
# Each dump lands in the service's data dir so restic picks it up automatically.
# Uses `docker exec` with a container name lookup (instead of `docker compose exec`)
# so this script doesn't need read access to the compose project .env files.

dump_postgres() {
    local service_name="$1"
    local db_user="$2"
    local dump_dir="$DATA_DIR/$service_name/dumps"

    echo "==> Dumping $service_name postgres (user: $db_user)"

    # Look up the running db container by compose project label
    local container
    container=$(docker ps --filter "label=com.docker.compose.project=$service_name" \
                          --filter "label=com.docker.compose.service=db" \
                          --format '{{.Names}}' | head -n1)

    if [ -z "$container" ]; then
        echo "ERROR: no running db container for $service_name" >&2
        return 1
    fi

    local tmp_file
    tmp_file=$(mktemp "$dump_dir/pg_dumpall.XXXXXX.sql")

    if ! docker exec "$container" pg_dumpall -U "$db_user" > "$tmp_file"; then
        echo "ERROR: pg_dumpall failed for $service_name" >&2
        rm -f "$tmp_file"
        return 1
    fi

    if [ ! -s "$tmp_file" ]; then
        echo "ERROR: dump for $service_name is empty" >&2
        rm -f "$tmp_file"
        return 1
    fi

    mv "$tmp_file" "$dump_dir/pg_dumpall.sql"
    echo "    $(wc -c < "$dump_dir/pg_dumpall.sql") bytes written"
}

DUMP_FAILURES=0
# No Postgres services currently deployed, so nothing calls dump_postgres.
# Add a `dump_postgres "<service>" "<db_user>"` line here when one returns.

# --- Restic backup ---
# When a Postgres service is deployed, exclude its raw data dir here: the
# pg_dump SQL files are the authoritative database backup. Raw data dirs are
# large, owned by container UIDs (unreadable by the backup user), and not
# consistent unless postgres is stopped. (None deployed currently.)
#
# Exclude /srv/data/dev-home: that's the dev container's home directory,
# unrelated to homelab services. Has its own backup concerns.
echo "==> Running restic backup"
restic backup "$DATA_DIR" --tag "$BACKUP_TAG" --verbose \
    --exclude "$DATA_DIR/dev-home"
RESTIC_EXIT=$?

# Restic exit codes: 0 = success, 3 = partial (some files unreadable but snapshot saved).
# Treat 3 as a warning: snapshot is still valid, we want to continue to the prune.
if [ "$RESTIC_EXIT" -ne 0 ] && [ "$RESTIC_EXIT" -ne 3 ]; then
    echo "ERROR: restic backup failed with exit $RESTIC_EXIT" >&2
    exit "$RESTIC_EXIT"
fi

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

# Exit non-zero if anything went sideways, so systemd marks the run as failed.
if [ "$DUMP_FAILURES" -gt 0 ]; then
    echo "WARNING: $DUMP_FAILURES database dump(s) failed" >&2
    exit 1
fi
if [ "$RESTIC_EXIT" -eq 3 ]; then
    echo "WARNING: restic backup had unreadable files (exit 3): snapshot saved but incomplete" >&2
    exit 1
fi
