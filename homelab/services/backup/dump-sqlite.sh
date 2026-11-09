#!/usr/bin/env bash
# Snapshot openclaw's live SQLite databases into a backup-readable dumps dir.
# Must run as root (ExecStartPre=+ on backup.service): config/state is mode
# 700 and openclaw re-chmods it, which wipes the backup user's ACL grant and
# made restic fail with "open .../config/state: permission denied".
#
# Two problems with letting restic read config/state directly:
#   1. Permissions: the ACL race above (see reapply-acls.sh).
#   2. Consistency: openclaw.sqlite runs in WAL mode, so recent writes live in
#      openclaw.sqlite-wal. Copying the main file alone yields a stale or
#      torn database. SQLite's online backup API takes a consistent snapshot
#      of a live database, including WAL content.
#
# backup.sh excludes config/state and picks these snapshots up from dumps/.
# The sqlite3 CLI isn't installed on picklelab, so this uses python3's stdlib
# binding to the same backup API.
#
# Exits non-zero if any snapshot fails, but backup.service runs it with a '-'
# prefix so that doesn't block the whole nightly; backup.sh checks that the
# snapshots exist and are fresh, and fails the run loudly if not.
set -uo pipefail

# Overridable so the script can be exercised without root (the state dir is
# owned by the deploy user, so a non-root run can read it).
SRC_DIR="${DUMP_SQLITE_SRC_DIR:-/srv/data/openclaw/config/state}"
DEST_DIR="${DUMP_SQLITE_DEST_DIR:-/srv/data/openclaw/dumps}"
BACKUP_USER="${DUMP_SQLITE_OWNER:-backup}"

DBS=(openclaw.sqlite openclaw-quarantine.sqlite)

mkdir -p "$DEST_DIR"
chown "$BACKUP_USER:$BACKUP_USER" "$DEST_DIR"
chmod 750 "$DEST_DIR"

rc=0
for db in "${DBS[@]}"; do
    src="$SRC_DIR/$db"
    dest="$DEST_DIR/$db"
    tmp="$DEST_DIR/.$db.tmp"

    if [ ! -f "$src" ]; then
        echo "dump-sqlite: $src not found, skipping" >&2
        continue
    fi

    rm -f "$tmp"
    if ! python3 - "$src" "$tmp" <<'PY'
import sqlite3, sys
src, dest = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
d = sqlite3.connect(dest)
with d:
    s.backup(d)
ok = d.execute("PRAGMA integrity_check").fetchone()[0]
d.close()
s.close()
if ok != "ok":
    sys.exit(f"integrity_check failed: {ok}")
PY
    then
        echo "dump-sqlite: failed to snapshot $db" >&2
        rm -f "$tmp"
        rc=1
        continue
    fi

    chown "$BACKUP_USER:$BACKUP_USER" "$tmp"
    chmod 640 "$tmp"
    mv "$tmp" "$dest"
    echo "dump-sqlite: $db -> $dest ($(stat -c %s "$dest") bytes)"
done

exit "$rc"
