#!/usr/bin/env bash
# Provision the golden machine. Runs INSIDE picklelab-golden, fed through
# `orb -m` by golden.sh, with OPENCLAW_IMAGE exported. Idempotent.
#
# Mirrors what picklelab has, minus anything that needs identity: no
# `tailscale up`, no host.env, no service-account token. Clones add those.
set -euo pipefail

: "${OPENCLAW_IMAGE:?golden.sh must export OPENCLAW_IMAGE}"

echo "==> Installing base packages"
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y jq git curl nodejs

# Public repo, no key needed. Later tasks sync the branch under test over this.
echo "==> Cloning picklehome to /opt/homelab"
if [ ! -d /opt/homelab/.git ]; then
    sudo mkdir -p /opt/homelab
    sudo chown "$(id -u):$(id -g)" /opt/homelab
    git clone https://github.com/technicalpickles/picklehome.git /opt/homelab
else
    echo "    already cloned"
fi

# setup-docker.sh ends with `docker info` as this user, right after adding them
# to the docker group. This shell predates that, so on a first run the verify
# fails with "permission denied" although everything before it succeeded. Run
# it tolerantly, then do the verification ourselves under the new group.
echo "==> setup-docker.sh"
/opt/homelab/homelab/scripts/setup-docker.sh \
    || echo "    setup-docker.sh exited non-zero (expected on a first run, the docker group is not active yet); verifying below"
docker_root="$(sg docker -c "docker info --format '{{.DockerRootDir}}'")"
if [ "$docker_root" != /srv/docker ]; then
    echo "ERROR: docker root is '$docker_root', expected /srv/docker: setup-docker.sh did not finish." >&2
    exit 1
fi

# Install only. setup-tailscale.sh runs `tailscale up`, which a golden must not.
echo "==> Installing tailscale (install only)"
if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
else
    echo "    already installed"
fi

echo "==> setup-deploy-access.sh"
/opt/homelab/homelab/scripts/setup-deploy-access.sh

# setup-docker.sh just added this user to the docker group, which a running
# session does not pick up, so docker goes through sudo from here on.
echo "==> Pulling $OPENCLAW_IMAGE"
sudo docker pull "$OPENCLAW_IMAGE"

echo "==> Checking github ssh through the forwarded agent"
# `ssh -T git@github.com` exits 1 even when auth works, so read its message.
ssh_out="$(ssh -T -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new git@github.com 2>&1 </dev/null || true)"
if [[ "$ssh_out" != *"successfully authenticated"* ]]; then
    echo "SKIP: no github ssh, first deploy builds"
    exit 0
fi

clone_private() { # <repo> <dir>
    if [ ! -d "$2/.git" ]; then
        sudo mkdir -p "$2"
        sudo chown "$(id -u):$(id -g)" "$2"
        git clone "git@github.com:technicalpickles/$1.git" "$2"
    else
        echo "    $2 already cloned"
    fi
}
echo "==> Cloning brineworks and pickleclaw"
clone_private brineworks /opt/brineworks
clone_private pickleclaw /opt/pickleclaw

# compose parses every service's ${VAR:?} even for a single build, so feed
# placeholders for every name in .env.vars (same trick deploy.sh uses).
echo "==> Building gog-mcp and goplaces-node"
cd /opt/homelab/homelab/services/openclaw
env_overrides=("OPENCLAW_IMAGE=$OPENCLAW_IMAGE")
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^#|^[[:space:]]*$ ]] && continue
    env_overrides+=("${line}=build-placeholder")
done < .env.vars
sudo env "${env_overrides[@]}" docker compose -f compose.yaml -f compose.picklelab.yaml build gog-mcp goplaces-node

echo "==> Golden provisioned"
