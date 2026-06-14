#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing prerequisites (docker repo deps + rsync for the containerd-migration runbook)"
sudo apt install -y ca-certificates curl rsync

echo "==> Adding Docker GPG key"
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "==> Adding Docker apt repository"
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "==> Installing Docker Engine + Compose plugin"
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "==> Adding $USER to docker group"
sudo usermod -aG docker "$USER"

echo "==> Creating /srv layout"
sudo mkdir -p /srv/docker /srv/data /srv/containers /srv/containerd

# Docker uses the containerd image store, so image layers live in containerd's
# snapshotter (root = /var/lib/containerd by default), NOT under docker's
# data-root. data-root only moves docker's containers/volumes/metadata, so
# without this the root volume fills with images while /srv sits idle. Relocate
# containerd's root to /srv too. The containerd.io package ships config.toml with
# `#root = "/var/lib/containerd"` commented out; uncomment it and repoint it,
# editing in place to keep the rest of the shipped config (disabled_plugins etc.)
# rather than clobbering it with a pinned-defaults dump. The `#\?` matches whether
# the line is commented or not; the `grep` verify below fails the script (set -e)
# if the substitution didn't take.
echo "==> Configuring containerd (root: /srv/containerd)"
sudo sed -i 's|^#\?root = .*|root = "/srv/containerd"|' /etc/containerd/config.toml
sudo systemctl restart containerd

echo "==> Configuring Docker daemon (data-root: /srv/docker, log limits)"
sudo tee /etc/docker/daemon.json > /dev/null <<'DAEMON'
{
  "data-root": "/srv/docker",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
DAEMON

echo "==> Restarting Docker"
sudo systemctl restart docker

echo "==> Verifying"
docker info | grep -E 'Docker Root Dir|Logging Driver'
grep '^root' /etc/containerd/config.toml

echo ""
echo "Done! Log out and back in for docker group membership to take effect."
