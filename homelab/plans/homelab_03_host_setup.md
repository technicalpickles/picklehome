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
- **Recommended:** `sudo systemctl reboot --firmware-setup` from the OS — reboots directly into BIOS setup without key-mashing. The NUC's POST is fast enough that catching F2 is unreliable, especially through GRUB.

**BIOS settings (configured):**

- Auto power-on after power loss — enabled
- Boot order: SSD first

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

### Disk Layout (verified)

LVM on `/dev/sda4`:

| Volume | Size | Mount |
|--------|------|-------|
| `vg0-root` | 30 GB | `/` |
| `vg0-srv` | 30 GB | `/srv` |
| **VFree** | ~49 GB | expandable later |

Swap: installer-created `/swap.img` (~3.7 GB), configured in `/etc/fstab`.

### Disable password SSH login

```bash
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

Verify from another machine: `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no picklelab` should get `Permission denied (publickey)`.

### Unattended security updates

Already installed on Ubuntu Server 24.04 minimized. Enable auto-apply:

```bash
sudo dpkg-reconfigure -plow unattended-upgrades
```

On minimized installs, this falls back to readline (no `dialog` package) — answer `yes`.

### Docker Engine + Compose + `/srv` layout

Scripted install: `homelab/scripts/setup-docker.sh`

Installs Docker CE 29.3, Compose plugin, buildx from the official Docker apt repo. Configures:

- `data-root: /srv/docker` — keeps images/layers off root LV
- Log driver: `json-file` with 10MB × 3 file rotation per container
- `/srv` directories: `/srv/docker`, `/srv/data`, `/srv/containers`
- Adds current user to `docker` group (re-login required)

### Tailscale

Scripted install: `homelab/scripts/setup-tailscale.sh`

- Installed on host (not in Docker) for reliable remote access even if container networking fails
- Tailscale IP: `100.123.122.68`
- SSH over Tailscale verified working

**Client setup (Mac):**

1. Install: `brew install --cask tailscale` (GUI app — not the CLI-only `brew install tailscale`, which requires manually running `tailscaled`)
2. Open Tailscale from Applications, sign in with the same account
3. Verify: `tailscale status` should show both your Mac and `picklelab`
4. Test: `ssh technicalpickles@100.123.122.68`

MagicDNS is enabled — `ssh picklelab` and `ssh picklelab.tail2023b7.ts.net` both work from any device on the tailnet. No SSH config or `/etc/hosts` needed.

### Log rotation

Scripted: `homelab/scripts/setup-log-rotation.sh`

- Docker logs: handled by `daemon.json` (json-file, 10MB × 3 per container)
- System journal: capped at 500MB via `/etc/systemd/journald.conf.d/size.conf`

### Infra repo

```bash
sudo mkdir -p /opt/homelab && sudo chown technicalpickles: /opt/homelab
git clone git@github.com:technicalpickles/picklehome.git /opt/homelab
```

Requires SSH agent forwarding — configured in `~/.ssh/config.d/hosts` on Mac (`ForwardAgent yes` for picklelab).

### TODO

- Static DHCP lease on USG
