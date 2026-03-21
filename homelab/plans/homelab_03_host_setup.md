# Host Setup

_TODO: fill in post-install sections as the build progresses._

---

## Hardware Reference

**Model:** Intel NUC6CAYH (Arches Canyon)

**Ports:**

- 2x USB 3.0 (front, one charging) + 2x USB 3.0 (rear)
- HDMI 2.0 (4K)
- VGA
- Gigabit Ethernet
- Combo audio jack + optical audio out
- SD card slot

**BIOS access:**

- **F2** at power-on → BIOS Setup
- **F10** at power-on → Boot device menu
- If using a Mac keyboard with Fn toggle, ensure function keys send F1–F12 (not media keys), or hold Fn+F2
- Power button hold (3 sec) → Power Button Menu → BIOS Setup (fallback)

**BIOS settings to configure:**

- Enable auto power-on after power loss
- Enable USB boot (if not already)
- Boot order: USB first for install, then SSD

---

## Install Media

**Image:** Ubuntu Server 24.04 LTS (amd64) — `ubuntu-24.04.4-live-server-amd64.iso` (~3.2 GB)

**Download:** https://ubuntu.com/download/server

**Creating bootable USB from macOS:**

```bash
# Find the USB disk identifier
diskutil list

# Unmount it
diskutil unmountDisk /dev/diskN

# Write the ISO (use rdiskN for ~10x faster writes)
sudo dd if=~/Downloads/ubuntu-24.04.4-live-server-amd64.iso of=/dev/rdiskN bs=1M status=progress

# Eject
diskutil eject /dev/diskN
```

macOS may show a "disk not readable" dialog after dd completes — ignore/eject it (the disk is now a Linux boot image).

---

## Ubuntu Server Install

- Choose **Ubuntu Server (minimized)** if offered
- Enable **OpenSSH server** during install
- Import SSH keys from GitHub when prompted (enter GitHub username)
- Plug in Ethernet for the install — smoother than WiFi

**Post-install gotcha:** the minimized server install may not enable `sshd` at boot even if selected during install. After first boot, verify and fix from the console:

```bash
sudo systemctl enable ssh
sudo systemctl start ssh
```

### Disk Partitioning

Use **Custom storage layout** in the installer:

- `/` → ~30 GB
- `/srv` → remainder of SSD

---

## Post-Install (over SSH)

_TODO: concrete commands for each step._

Planned:

- Admin user: SSH key-only login, disable password SSH
- Static DHCP lease on USG
- Swapfile creation (2 GB)
- Unattended security updates
- Docker Engine + Compose plugin install and `daemon.json`
- Tailscale install (on host, not in Docker)
- `/srv` directory layout (`/srv/data`, `/srv/containers`, `/srv/docker`)
- Log rotation config
- Clone infra repo to `/opt/homelab`
- Set hostname (e.g., `nuc`)
