#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing Docker Engine prerequisites"
sudo apt install -y ca-certificates curl

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
sudo mkdir -p /srv/docker /srv/data /srv/containers

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

echo ""
echo "Done! Log out and back in for docker group membership to take effect."
