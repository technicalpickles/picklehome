#!/usr/bin/env bash
# Set up a rootless Docker daemon running as a dedicated unprivileged `ci` user.
# The Woodpecker agent points at THIS daemon's socket to spawn CI step containers,
# so a compromised step runs as `ci` (uid 2000) and cannot read the host secret
# superset at /opt/homelab/.env. See docs/plans/2026-06-18-woodpecker-ci-design.md
# (Section 4, Option D).
#
# Idempotent: safe to run on first setup or re-run. Run interactively on the host.
set -euo pipefail

CI_USER=ci
CI_UID=2000
CI_DATA_ROOT=/srv/ci-docker          # keep bulky CI image layers off the root volume
RT=/run/user/${CI_UID}

echo "==> Creating the ${CI_USER} user (uid ${CI_UID})"
if id "$CI_USER" &>/dev/null; then
    echo "    user ${CI_USER} already exists"
else
    sudo useradd --uid "$CI_UID" --create-home --shell /usr/bin/bash "$CI_USER"
fi

echo "==> Ensuring subordinate uid/gid ranges (required by rootless docker)"
# Modern useradd usually allocates these automatically; add a high, collision-safe
# range only if missing.
if ! grep -q "^${CI_USER}:" /etc/subuid; then
    sudo usermod --add-subuids 2000000-2065535 "$CI_USER"
fi
if ! grep -q "^${CI_USER}:" /etc/subgid; then
    sudo usermod --add-subgids 2000000-2065535 "$CI_USER"
fi

echo "==> Installing rootless prerequisites"
sudo apt-get update
sudo apt-get install -y uidmap dbus-user-session docker-ce-rootless-extras slirp4netns fuse-overlayfs

echo "==> Enabling linger so the ${CI_USER} daemon survives logout/reboot"
sudo loginctl enable-linger "$CI_USER"

echo "==> Creating rootless data-root at ${CI_DATA_ROOT}"
sudo mkdir -p "$CI_DATA_ROOT"
sudo chown "${CI_USER}:${CI_USER}" "$CI_DATA_ROOT"

echo "==> Writing rootless daemon config (data-root on /srv + log limits)"
sudo -u "$CI_USER" mkdir -p "/home/${CI_USER}/.config/docker"
sudo -u "$CI_USER" tee "/home/${CI_USER}/.config/docker/daemon.json" > /dev/null <<DAEMON
{
  "data-root": "${CI_DATA_ROOT}",
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
DAEMON

echo "==> Installing the rootless docker daemon as ${CI_USER}"
sudo -iu "$CI_USER" env XDG_RUNTIME_DIR="$RT" dockerd-rootless-setuptool.sh install

echo "==> Enabling + starting the rootless docker user service"
sudo -iu "$CI_USER" env XDG_RUNTIME_DIR="$RT" systemctl --user enable --now docker

echo "==> Waiting for the rootless socket"
for i in 1 2 3 4 5; do
    if sudo test -S "${RT}/docker.sock"; then echo "    socket up"; break; fi
    [ "$i" -eq 5 ] && { echo "ERROR: ${RT}/docker.sock never appeared"; exit 1; }
    sleep 2
done

run_ci() { sudo -iu "$CI_USER" env XDG_RUNTIME_DIR="$RT" DOCKER_HOST="unix://${RT}/docker.sock" "$@"; }

echo "==> Verify: hello-world runs on the rootless daemon"
run_ci docker run --rm hello-world | grep -q "Hello from Docker" && echo "    hello-world OK"

echo "==> Verify: data-root is on /srv"
echo "    DockerRootDir = $(run_ci docker info --format '{{.DockerRootDir}}')"

echo "==> Verify ISOLATION (the whole point of Option D)"
# A rootless container's root maps to host uid ${CI_UID} (ci), which owns nothing
# sensitive. Prove it cannot read a root-owned file. /etc/shadow is the
# deterministic target (always present, 640 root:shadow); /opt/homelab/.env is the
# real-world stake (checked too, if present).
run_ci docker pull -q alpine > /dev/null
if run_ci docker run --rm -v /etc/shadow:/s:ro alpine cat /s > /dev/null 2>&1; then
    echo "    !! FAIL: rootless container READ /etc/shadow. Isolation is NOT working."
    echo "       Check: docker info | grep -i rootless ; and the subuid/subgid mapping."
    exit 1
fi
echo "    PASS: rootless container denied /etc/shadow"
if sudo test -f /opt/homelab/.env; then
    if run_ci docker run --rm -v /opt/homelab:/host:ro alpine cat /host/.env > /dev/null 2>&1; then
        echo "    !! FAIL: rootless container READ /opt/homelab/.env."
        echo "       Check: ls -l /opt/homelab/.env (want 600, owner technicalpickles)."
        exit 1
    fi
    echo "    PASS: rootless container denied /opt/homelab/.env"
else
    echo "    (note: /opt/homelab/.env not present yet; /etc/shadow check already proves isolation)"
fi

echo ""
echo "Done! Rootless docker for ${CI_USER} is running."
echo "  socket:    ${RT}/docker.sock"
echo "  data-root: ${CI_DATA_ROOT}"
echo "The Woodpecker agent will bind-mount the socket and run as uid ${CI_UID}."
