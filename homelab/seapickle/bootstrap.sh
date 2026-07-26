#!/usr/bin/env bash
# Bootstrap seapickle, the beach house Raspberry Pi 3B+ jump box + probe node.
#
# Run as root on a freshly flashed Raspberry Pi OS Lite (64-bit) install:
#
#   sudo ./bootstrap.sh 192.168.x.0/24
#
# The argument is the beach house LAN subnet to advertise over Tailscale.
# It is remembered in /etc/seapickle/subnet so re-runs don't need it, and it
# is passed as an argument so it never lives in git (see docs/CONVENTIONS.md
# on sensitive data). Idempotent: safe to re-run to converge changes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR=/usr/local/lib/seapickle
STATE_DIR=/etc/seapickle
LOG_DIR=/var/log/seapickle

if [[ $EUID -ne 0 ]]; then
    echo "error: must run as root (sudo $0 ...)" >&2
    exit 1
fi

# --- subnet: from argument, or remembered from a previous run -------------
mkdir -p "$STATE_DIR"
if [[ $# -ge 1 ]]; then
    echo "$1" > "$STATE_DIR/subnet"
fi
if [[ ! -s "$STATE_DIR/subnet" ]]; then
    echo "error: no subnet given and none remembered." >&2
    echo "usage: sudo $0 <beach-subnet-cidr>   e.g. sudo $0 192.168.x.0/24" >&2
    exit 1
fi
SUBNET="$(cat "$STATE_DIR/subnet")"

# --- packages -------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y install \
    mtr-tiny iperf3 tcpdump nmap arp-scan dnsutils jq curl \
    unattended-upgrades logrotate

# Ookla speedtest CLI: official packagecloud repo, ships arm64/armhf debs.
if ! command -v speedtest >/dev/null 2>&1; then
    curl -fsSL https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash
    apt-get -y install speedtest
fi

# Tailscale: official install script adds the apt repo for this OS release.
if ! command -v tailscale >/dev/null 2>&1; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi

# --- low-RAM / SD-wear tuning ---------------------------------------------
# Headless: give the GPU the minimum split so nearly all 1GB goes to the OS.
BOOT_CONFIG=/boot/firmware/config.txt
[[ -f $BOOT_CONFIG ]] || BOOT_CONFIG=/boot/config.txt
if ! grep -q '^gpu_mem=' "$BOOT_CONFIG"; then
    echo "gpu_mem=16" >> "$BOOT_CONFIG"
    echo "note: gpu_mem=16 added to $BOOT_CONFIG (takes effect after reboot)"
fi

# Compressed-RAM swap instead of SD-card swap. Current Raspberry Pi OS
# (Debian 13+) ships systemd-zram-generator, which claims /dev/zram0 as swap
# before this script even runs. Installing zram-tools on top collides over
# the same device (mkswap refuses because it's already mounted). Only manage
# zram ourselves on older images that lack the generator; otherwise leave
# the OS default alone.
if systemctl is-active --quiet systemd-zram-setup@zram0.service 2>/dev/null; then
    echo "note: zram swap already managed by systemd-zram-generator, skipping zram-tools"
    systemctl disable --now zramswap.service >/dev/null 2>&1 || true
else
    apt-get -y install zram-tools
    systemctl enable --now zramswap.service
fi

# Cap journald so logs can't eat the SD card.
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/seapickle.conf <<'EOF'
[Journal]
SystemMaxUse=64M
EOF
systemctl restart systemd-journald

# --- subnet routing -------------------------------------------------------
cat > /etc/sysctl.d/99-tailscale.conf <<'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sysctl -p /etc/sysctl.d/99-tailscale.conf >/dev/null

# --- probes ---------------------------------------------------------------
mkdir -p "$LIB_DIR" "$LOG_DIR"
install -m 755 "$SCRIPT_DIR/net-probe.sh" "$SCRIPT_DIR/speedtest-probe.sh" "$LIB_DIR/"
install -m 644 "$SCRIPT_DIR"/seapickle-*.service "$SCRIPT_DIR"/seapickle-*.timer \
    /etc/systemd/system/

cat > /etc/logrotate.d/seapickle <<'EOF'
/var/log/seapickle/*.jsonl {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
EOF

systemctl daemon-reload
systemctl enable --now seapickle-net-probe.timer seapickle-speedtest.timer

# --- tailscale up ---------------------------------------------------------
echo
if tailscale status >/dev/null 2>&1; then
    echo "Tailscale is already up. To (re)apply routes:"
else
    echo "Bootstrap done. Bring up Tailscale with:"
fi
echo
echo "  sudo tailscale up --ssh --advertise-routes=$SUBNET --hostname=seapickle"
echo
echo "Then in the admin console: approve the machine, approve the subnet"
echo "route, and disable key expiry for this node."
