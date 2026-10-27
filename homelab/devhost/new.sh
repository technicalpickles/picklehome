#!/usr/bin/env bash
# Usage: new.sh <name>
# Clone the stopped picklelab-golden OrbStack machine into a dev host called
# <name> and give it its identity. Runs on the Mac.
#
# Secrets arrive in the environment (the Justfile recipe wraps this in
# `av inject`):
#   DEVHOST_OP_TOKEN    the dev 1Password service-account token
#   DEVHOST_TS_AUTH_KEY a reusable Tailscale auth key restricted to tag:devhost
# Both are read into shell variables and unset, so no child process inherits
# them. They reach the machine on stdin only: the token files via tee, the auth
# key via a `read` inside the machine. The one place the auth key becomes argv
# is the `tailscale up` process inside the machine.
#
# Every orb call that takes a machine names it. A bare `orb stop` stops all of
# OrbStack.
#
# ORB_BIN and DEVHOST_LOCAL_DIR override the orb binary and the generated
# identity directory (tests); HOME decides which ~/.ssh is touched.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

NAME="${1-}"
devhost_check_name "$NAME"

OP_TOKEN="${DEVHOST_OP_TOKEN-}"
TS_AUTH_KEY="${DEVHOST_TS_AUTH_KEY-}"
unset DEVHOST_OP_TOKEN DEVHOST_TS_AUTH_KEY
if [ -z "$OP_TOKEN" ]; then
    echo "ERROR: DEVHOST_OP_TOKEN is empty. Run this through \`just devhost-new $NAME\` (av inject supplies it)." >&2
    exit 1
fi
if [ -z "$TS_AUTH_KEY" ]; then
    echo "ERROR: DEVHOST_TS_AUTH_KEY is empty. Run this through \`just devhost-new $NAME\` (av inject supplies it)." >&2
    exit 1
fi

# A hand-written `Host <name>` block is not ours to overwrite or later remove.
foreign="$(devhost_ssh_foreign_lines "$NAME")"
if [ -n "$foreign" ]; then
    echo "ERROR: $SSH_HOSTS_FILE already has a 'Host $NAME' entry outside its devhost markers:" >&2
    echo "    $foreign" >&2
    echo "       Pick another name, or remove that block by hand." >&2
    exit 1
fi

# `orb list -q` prints one machine name per line.
# Captured first: a failing `orb list` must abort under set -e, not read as "absent".
machines="$("$ORB" list -q </dev/null)"
if grep -Fxq -- "$NAME" <<<"$machines"; then
    echo "ERROR: a machine named '$NAME' already exists." >&2
    exit 1
fi

echo "==> Cloning picklelab-golden to $NAME"
"$ORB" clone picklelab-golden "$NAME"
trap 'echo "==> $NAME is half-built. Remove it with: just devhost-rm $NAME" >&2' ERR

# Written now, not at the end, so devhost-rm can clean up after any later failure.
mkdir -p "$LOCAL_DIR"
LOCAL_ENV="$LOCAL_DIR/$NAME.env"
{
    cat "$HERE/../hosts/dev-identity.env"
    echo "HOMELAB_HOST_NAME=$NAME"
} >"$LOCAL_ENV"

# The machine is stopped after clone; config is set before it first boots.
for key in isolated isolate_network forward_ssh_agent; do
    "$ORB" config set "machine.$NAME.$key" true
done
echo "==> Starting $NAME"
"$ORB" start "$NAME"

# Run a command in the machine as root. Stdin passes through.
in_machine() { "$ORB" -m "$NAME" sudo "$@"; }

echo "==> Writing identity and token files"
in_machine install -d -m 0755 /etc/opt/homelab </dev/null
in_machine tee /etc/opt/homelab/host.env >/dev/null <"$LOCAL_ENV"
# umask first so the file is never readable by others, chmod for a pre-existing one.
for path in /etc/opt/homelab/op-token-picklehome /etc/opt/homelab/op-token-pickleclaw; do
    printf 'OP_SERVICE_ACCOUNT_TOKEN=%s\n' "$OP_TOKEN" |
        in_machine bash -c 'umask 077; tee "$1" >/dev/null; chmod 0600 "$1"' _ "$path"
done

# The golden started tailscaled once, so every clone carries the same machine
# key. Wipe the state so this one registers as its own node.
echo "==> Resetting tailscale state and joining the tailnet"
in_machine systemctl stop tailscaled </dev/null
in_machine find /var/lib/tailscale -mindepth 1 -delete </dev/null
in_machine systemctl start tailscaled </dev/null
printf '%s\n' "$TS_AUTH_KEY" |
    in_machine bash -c 'IFS= read -r key && exec tailscale up --auth-key="$key" --hostname "$1" --advertise-tags=tag:devhost' _ "$NAME"

echo "==> Adding ssh config for $NAME"
mkdir -p "$(dirname "$SSH_HOSTS_FILE")"
{
    if [ -f "$SSH_HOSTS_FILE" ]; then devhost_ssh_strip_block "$NAME"; fi
    printf '# devhost %s begin\nHost %s\n    HostName %s.orb.local\n# devhost %s end\n' "$NAME" "$NAME" "$NAME" "$NAME"
} | devhost_ssh_replace

trap - ERR
echo "==> $NAME is up: ssh $NAME"
