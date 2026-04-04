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
    local tmp_file
    tmp_file=$(mktemp "$dump_dir/pg_dumpall.XXXXXX.sql")

    docker compose \
        -f "$compose_project_dir/compose.yaml" \
        -f "$compose_project_dir/compose.picklelab.yaml" \
        exec -T db pg_dumpall -U "$db_user" \
        > "$tmp_file"

    if [ ! -s "$tmp_file" ]; then
        echo "ERROR: dump for $service_dir is empty" >&2
        rm -f "$tmp_file"
        return 1
    fi

    mv "$tmp_file" "$dump_dir/pg_dumpall.sql"
    echo "    $(wc -c < "$dump_dir/pg_dumpall.sql") bytes written"
}

REPO_DIR="/opt/homelab/homelab/services"

DUMP_FAILURES=0

dump_postgres "vikunja" "$REPO_DIR/vikunja" "vikunja" || DUMP_FAILURES=$((DUMP_FAILURES + 1))
dump_postgres "baserow" "$REPO_DIR/baserow" "baserow" || DUMP_FAILURES=$((DUMP_FAILURES + 1))

# --- Restic backup ---
echo "==> Running restic backup"
restic backup "$DATA_DIR" --tag "$BACKUP_TAG" --verbose

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

if [ "$DUMP_FAILURES" -gt 0 ]; then
    echo "WARNING: $DUMP_FAILURES database dump(s) failed" >&2
    exit 1
fi
