# shellcheck shell=bash
# Source this from a deploy.sh (right after deploy-lock.sh). Do not execute it.
#
# Reads the per-host identity file and exports what differs between hosts:
#   HOMELAB_HOST_NAME        this host (env, else the file, else `hostname -s`)
#   HOMELAB_HOST_KIND        prod | dev
#   HOMELAB_SERVICE_SUFFIX   appended to Tailscale Service names; empty on prod
#   HOMELAB_ENV_OVERLAY      overlay name under homelab/hosts/overlays/; may be empty
#   HOMELAB_SECONDARY_VAULT  the 1Password vault besides picklehome
#   BRINEWORKS_REF, PICKLECLAW_REF   git refs to build
#   HOMELAB_HOST_ALIASES     space-separated other names for this host; may be empty
#
# Lookup order, first hit wins:
#   1. $HOMELAB_HOST_FILE, if set (an explicit path must exist)
#   2. ${HOMELAB_REPO_DIR:-/opt/homelab}/homelab/hosts/<host>.env  (committed, prod hosts)
#   3. /etc/opt/homelab/host.env  (copied onto dev hosts)
# No file, or a missing key: exit 78. There is deliberately no default, so a host
# nobody described can never fall back to prod names.
#
# A required key only has to be defined, not non-empty. Callers reference the
# values as ${VAR?} so a script that forgot to source this fails under set -u
# instead of using a prod name on the wrong box.

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "host-identity.sh: source this file, don't run it" >&2
    exit 64
fi

_hi_required="HOMELAB_HOST_KIND HOMELAB_SERVICE_SUFFIX HOMELAB_ENV_OVERLAY HOMELAB_SECONDARY_VAULT BRINEWORKS_REF PICKLECLAW_REF HOMELAB_HOST_ALIASES"

_hi_lookup_name="${HOMELAB_HOST_NAME:-$(hostname -s)}"
_hi_repo_file="${HOMELAB_REPO_DIR:-/opt/homelab}/homelab/hosts/${_hi_lookup_name}.env"
_hi_box_file=/etc/opt/homelab/host.env

if [ -n "${HOMELAB_HOST_FILE:-}" ]; then
    _hi_file="$HOMELAB_HOST_FILE"
    if [ ! -f "$_hi_file" ]; then
        echo "ERROR: HOMELAB_HOST_FILE=$_hi_file does not exist" >&2
        exit 78
    fi
elif [ -f "$_hi_repo_file" ]; then
    _hi_file="$_hi_repo_file"
elif [ -f "$_hi_box_file" ]; then
    _hi_file="$_hi_box_file"
else
    echo "ERROR: no identity file for host '$_hi_lookup_name'. Looked at:" >&2
    echo "    $_hi_repo_file" >&2
    echo "    $_hi_box_file" >&2
    exit 78
fi

# The file is the only source for the required keys, so drop anything inherited
# from the caller's environment first. HOMELAB_HOST_NAME is the exception: an
# environment value beats the file.
for _hi_key in $_hi_required; do unset "$_hi_key"; done
_hi_env_name="${HOMELAB_HOST_NAME:-}"
unset HOMELAB_HOST_NAME

case "$-" in *a*) _hi_had_allexport=1 ;; *) _hi_had_allexport=0 ;; esac
set -a
# shellcheck disable=SC1090
. "$_hi_file"
[ "$_hi_had_allexport" = 1 ] || set +a

if [ -n "$_hi_env_name" ]; then
    HOMELAB_HOST_NAME="$_hi_env_name"
elif [ -z "${HOMELAB_HOST_NAME:-}" ]; then
    HOMELAB_HOST_NAME="$(hostname -s)"
fi
export HOMELAB_HOST_NAME

_hi_bad=0
for _hi_key in $_hi_required; do
    if [ -z "${!_hi_key+x}" ]; then
        echo "ERROR: $_hi_file does not define $_hi_key" >&2
        _hi_bad=1
    fi
done
[ "$_hi_bad" = 0 ] || exit 78

unset _hi_required _hi_lookup_name _hi_repo_file _hi_box_file _hi_file _hi_env_name _hi_had_allexport _hi_bad _hi_key
