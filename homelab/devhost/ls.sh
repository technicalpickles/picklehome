#!/usr/bin/env bash
# Usage: ls.sh
# One line per dev host new.sh made (a file in homelab/hosts/local/), with the
# machine's state from `orb list` (running, stopped) or "missing" if OrbStack
# has no such machine.
#
# ORB_BIN and DEVHOST_LOCAL_DIR override the orb binary and that directory (tests).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

shopt -s nullglob
files=("$LOCAL_DIR"/*.env)
if [ "${#files[@]}" -eq 0 ]; then
    echo "no dev hosts (nothing in $LOCAL_DIR)"
    exit 0
fi

# `orb list` prints: name state distro version arch size [ip].
listing="$("$ORB" list </dev/null)"
for f in "${files[@]}"; do
    name="$(basename "$f" .env)"
    state="$(awk -v n="$name" '$1 == n { print $2; exit }' <<<"$listing")"
    printf '%-24s %s\n' "$name" "${state:-missing}"
done
