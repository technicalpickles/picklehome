#!/usr/bin/env bash
# Bootstrap seapickle, the beach house Raspberry Pi 3B+ jump box + probe node.
#
# Run as root on a freshly flashed Raspberry Pi OS Lite (64-bit) install:
#
#   sudo ./bootstrap.sh
#
# seapickle is a jump host only: you SSH into it and run diagnostics from
# its own shell, using its own physical LAN access. It deliberately does not
# advertise a Tailscale subnet route -- that would make every device on the
# beach house LAN directly reachable from anything else on the tailnet (and
# vice versa), which is more exposure than a jump host needs. Idempotent:
# safe to re-run to converge changes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR=/usr/local/lib/seapickle
LOG_DIR=/var/log/seapickle

if [[ $EUID -ne 0 ]]; then
    echo "error: must run as root (sudo $0 ...)" >&2
    exit 1
fi

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
    echo "Tailscale is already up."
else
    echo "Bootstrap done. Bring up Tailscale with:"
    echo
    echo "  sudo tailscale up --ssh --hostname=seapickle"
fi
echo
echo "Then in the admin console: approve the machine (if device approval is"
echo "on) and disable key expiry for this node. No subnet route to approve --"
echo "seapickle is a jump host only, it doesn't advertise one."
