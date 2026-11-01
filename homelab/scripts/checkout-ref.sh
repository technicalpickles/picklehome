# shellcheck shell=bash
# Source this from a deploy.sh. Do not execute it.
#
#   checkout_ref <dir> <url> <ref>
#
# Gets <dir> onto <ref> of <url>: clones when <dir>/.git is missing, then fetches
# <ref> from origin and checks it out. A GIT_SSH_COMMAND set by the caller
# (including as a one-command prefix: GIT_SSH_COMMAND=... checkout_ref ...) is
# used for both the clone and the fetch.
#
# How the checkout moves depends on HOMELAB_HOST_KIND (from host-identity.sh):
#   prod  fast-forward only. A local branch that diverged from origin fails the
#         call and is left alone, same as `git pull --ff-only` did.
#   dev   `checkout -B`: the local branch is reset to origin's ref, so a dev box
#         follows a rebased or force-pushed branch.
#
# Returns non-zero on any failure, so a failed fetch fails the deploy instead of
# building a stale checkout. Works with or without set -e in the caller.

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "checkout-ref.sh: source this file, don't run it" >&2
    exit 64
fi

checkout_ref() {
    local dir=${1:?checkout_ref: dir required}
    local url=${2:?checkout_ref: url required}
    local ref=${3:?checkout_ref: ref required}
    local kind=${HOMELAB_HOST_KIND?checkout_ref: HOMELAB_HOST_KIND unset (source host-identity.sh first)}

    case "$kind" in
        prod | dev) ;;
        *)
            echo "ERROR: checkout_ref: HOMELAB_HOST_KIND must be prod or dev, got '$kind'" >&2
            return 1
            ;;
    esac

    if [ ! -d "$dir/.git" ]; then
        echo "    Cloning $url to $dir"
        sudo mkdir -p "$dir" || return 1
        sudo chown "$(id -u):$(id -g)" "$dir" || return 1
        git clone -q "$url" "$dir" || return 1
    fi

    git -C "$dir" fetch -q origin "$ref" || {
        echo "ERROR: checkout_ref: fetch of '$ref' from origin failed in $dir" >&2
        return 1
    }

    if [ "$kind" = dev ]; then
        git -C "$dir" checkout -q -B "$ref" "origin/$ref" || return 1
    else
        if git -C "$dir" show-ref --verify --quiet "refs/heads/$ref"; then
            git -C "$dir" checkout -q "$ref" || return 1
        else
            git -C "$dir" checkout -q -b "$ref" "origin/$ref" || return 1
        fi
        git -C "$dir" merge -q --ff-only "origin/$ref" || {
            echo "ERROR: checkout_ref: $dir has local commits not on origin/$ref; refusing to reset a prod checkout" >&2
            return 1
        }
    fi

    echo "    $dir at $(git -C "$dir" rev-parse --short HEAD) ($ref)"
}
