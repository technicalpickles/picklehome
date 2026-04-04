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
