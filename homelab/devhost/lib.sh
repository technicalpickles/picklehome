# shellcheck shell=bash
# Shared by new.sh, rm.sh and ls.sh. Source it, don't run it.
#
# Expects the caller to have set HERE (this directory) and set -euo pipefail.
# Overrides, all for tests:
#   ORB_BIN            the orb binary (default: orb)
#   DEVHOST_LOCAL_DIR  where generated identity files live
#                      (default: homelab/hosts/local, gitignored)

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
ORB="${ORB_BIN:-orb}"
LOCAL_DIR="${DEVHOST_LOCAL_DIR:-$REPO_ROOT/homelab/hosts/local}"
SSH_HOSTS_FILE="$HOME/.ssh/config.d/hosts"

# Names that must never be cloned into or deleted. picklelab is the real host,
# picklelab-golden is the clone source.
devhost_check_name() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "usage: $(basename "$0") <name>" >&2
        exit 1
    fi
    case "$name" in
        picklelab | picklelab-golden)
            echo "ERROR: refusing '$name': protected machine name." >&2
            exit 1
            ;;
    esac
    # Lowercase letters, digits and hyphens: safe in a hostname, a path, and the
    # awk patterns below.
    if [[ ! "$name" =~ ^[a-z][a-z0-9-]*$ ]]; then
        echo "ERROR: refusing '$name': use lowercase letters, digits and hyphens, starting with a letter." >&2
        exit 1
    fi
}

# Print the ssh config with this host's marked block removed.
devhost_ssh_strip_block() {
    local name="$1"
    awk -v b="# devhost $name begin" -v e="# devhost $name end" '
        $0 == b { skip = 1; next }
        $0 == e { skip = 0; next }
        !skip { print }
    ' "$SSH_HOSTS_FILE"
}

# Print the `Host` lines naming this host that sit outside its own markers.
devhost_ssh_foreign_lines() {
    local name="$1"
    [ -f "$SSH_HOSTS_FILE" ] || return 0
    devhost_ssh_strip_block "$name" | awk -v n="$name" '
        tolower($1) == "host" {
            for (i = 2; i <= NF; i++) if ($i == n) { print; next }
        }
    '
}

# Rewrite the hosts file with the contents of stdin. Goes through a temp file
# (the input usually comes from the file itself) and then cat, so the file keeps
# its mode; a new one gets 0600.
devhost_ssh_replace() {
    local tmp
    tmp="$(mktemp "$SSH_HOSTS_FILE.XXXXXX")"
    cat >"$tmp"
    if [ ! -f "$SSH_HOSTS_FILE" ]; then (umask 077; : >"$SSH_HOSTS_FILE"); fi
    cat "$tmp" >"$SSH_HOSTS_FILE"
    rm -f "$tmp"
}
