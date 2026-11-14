# Host Setup

Concrete steps to reproduce picklelab from bare metal: install media, Ubuntu Server install,
and the post-install configuration (disk layout, SSH hardening, Docker, Tailscale, deploy
access, and convenience tooling). Reflects the current host; update as the build changes.

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
- **Recommended:** `sudo systemctl reboot --firmware-setup` from the OS, which reboots directly into BIOS setup without key-mashing. The NUC's POST is fast enough that catching F2 is unreliable, especially through GRUB.

**BIOS settings (configured):**

- Auto power-on after power loss: enabled
- Boot order: SSD first

---

## Install Media

**Image:** Ubuntu Server 24.04 LTS (amd64): `ubuntu-24.04.4-live-server-amd64.iso` (~3.2 GB)

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

macOS may show a "disk not readable" dialog after dd completes. Ignore/eject it (the disk is now a Linux boot image).

---

## Ubuntu Server Install

- Choose **Ubuntu Server (minimized)** if offered
- Enable **OpenSSH server** during install
- Import SSH keys from GitHub when prompted (enter GitHub username)
- Plug in Ethernet for the install (smoother than WiFi)

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

On minimized installs, this falls back to readline (no `dialog` package). Answer `yes`.

### Keep needrestart off containerd

Scripted: `homelab/scripts/setup-needrestart.sh`

After a library upgrade, unattended-upgrades runs needrestart, which restarts every service still using the old library. The stock config already skips `docker.service` but not `containerd.service`. On 2026-11-14 a glibc upgrade restarted containerd under a running dockerd, and dockerd then failed every `docker exec`, healthcheck and image build with "not found" until docker restarted.

The script installs `homelab/config/needrestart-containerd.conf` to `/etc/needrestart/conf.d/` as a root-owned copy, then checks that needrestart skips both daemons. Both then stay on the old library until someone restarts them. host-state's `runtime-docker` check reports that as a warning, and reports a containerd restart under a running dockerd as critical. Fix either one in a quiet window with `sudo systemctl restart containerd docker`, which restarts every container.

```bash
cd /opt/homelab
homelab/scripts/setup-needrestart.sh
```

### Docker Engine + Compose + `/srv` layout

Scripted install: `homelab/scripts/setup-docker.sh`

Installs Docker CE 29.3, Compose plugin, buildx from the official Docker apt repo. Configures:

- `data-root: /srv/docker`: keeps images/layers off root LV
- Log driver: `json-file` with 10MB × 3 file rotation per container
- `/srv` directories: `/srv/docker`, `/srv/data`, `/srv/containers`
- Adds current user to `docker` group (re-login required)

### Rootless Docker for CI (the `ci` user)

Scripted install: `homelab/scripts/setup-rootless-ci-docker.sh`

A *second*, rootless Docker daemon running as a dedicated unprivileged `ci` user
(uid 2000), used only by the Woodpecker agent to spawn CI step containers. This is
the isolation boundary: a compromised CI step runs as `ci` and cannot read
root-/`technicalpickles`-owned files, including the secret superset at
`/opt/homelab/.env`. Configures:

- `ci` user at fixed uid 2000 (socket path `/run/user/2000/docker.sock` is then deterministic)
- subuid/subgid ranges + linger (daemon survives reboot)
- `data-root: /srv/ci-docker`: keeps CI image layers off the root LV (same discipline as the main daemon)
- Self-verifies isolation (rootless container is denied `/etc/shadow` and `/opt/homelab/.env`); exits non-zero if it fails

Rationale: `docs/plans/2026-06-18-woodpecker-ci-design.md` (Section 4, Option D).

### Tailscale

Scripted install: `homelab/scripts/setup-tailscale.sh`

- Installed on host (not in Docker) for reliable remote access even if container networking fails
- Tailscale IP: `100.123.122.68`
- SSH over Tailscale verified working
- **Disable key expiry for this node** in the [admin console](https://login.tailscale.com/admin/machines) once it's approved: picklelab is headless, so nothing ever reauths it, and an expired key just goes dark with no warning. Same reasoning as `seapickle` (see `homelab/seapickle/README.md`); every per-service Tailscale sidecar (`ts-woodpecker`, `brineworks-agent`, etc.) needs the same treatment individually, since each is its own tailnet node even though they all run on this one box. `just tailscale-audit` checks this across the whole tailnet.

**Client setup (Mac):**

1. Install: `brew install --cask tailscale` (GUI app, not the CLI-only `brew install tailscale`, which requires manually running `tailscaled`)
2. Open Tailscale from Applications, sign in with the same account
3. Verify: `tailscale status` should show both your Mac and `picklelab`
4. Test: `ssh technicalpickles@100.123.122.68`

MagicDNS is enabled, so `ssh picklelab` and `ssh picklelab.tail2023b7.ts.net` both work from any device on the tailnet. No SSH config or `/etc/hosts` needed.

### Log rotation

Scripted: `homelab/scripts/setup-log-rotation.sh`

- Docker logs: handled by `daemon.json` (json-file, 10MB × 3 per container)
- System journal: capped at 500MB via `/etc/systemd/journald.conf.d/size.conf`

### Infra repo

```bash
sudo mkdir -p /opt/homelab && sudo chown technicalpickles: /opt/homelab
git clone git@github.com:technicalpickles/picklehome.git /opt/homelab
```

Requires SSH agent forwarding, configured in `~/.ssh/config.d/hosts` on Mac (`ForwardAgent yes` for picklelab).

### Deploy access (passwordless sudo)

Scripted: `homelab/scripts/setup-deploy-access.sh`

Installs a sudoers drop-in (`/etc/sudoers.d/deploy-ops`) granting `technicalpickles` passwordless sudo for the specific commands used by deploy scripts: `mkdir`, `ln`, `systemctl`, `chown`, `tailscale serve`, `setfacl`, `useradd`, `usermod`, `apt-get`, a read-only `test -S` on the `ci` rootless docker socket (woodpecker pre-flight), and running commands as the `backup` user.

This enables non-interactive deploys from Mac (`ssh picklelab "..."` without `-t` flag).

The allowlist template lives in `homelab/config/sudoers-deploy-ops`. The setup script validates syntax with `visudo -cf` before installing, so a bad edit won't lock you out.

Run after initial host setup:

```bash
cd /opt/homelab
homelab/scripts/setup-deploy-access.sh
```

### Static DHCP lease

Fixed IP `192.168.1.82` assigned via UniFi controller (`/rest/user` → `use_fixedip: true`).

### mosh

Installed on host: `sudo apt install mosh`

No firewall config needed (UFW not installed on the minimized Ubuntu 24.04 image; mosh UDP ports 60000-61000 are open by default).

**Client setup (Mac):** `brew install mosh`

**Connect:** `mosh picklelab` (works via Tailscale MagicDNS)

Initial connection may take a few seconds while Tailscale establishes a direct peer-to-peer UDP path. Once connected, mosh is resilient to network changes and sleep/wake cycles.

### neovim

Installed on host: `sudo apt install neovim`

### smartmontools and tmux

Installed on host 2026-11-03, one command, for the disk swap: `sudo apt-get install -y smartmontools tmux`.

**smartmontools** (7.4): `sudo smartctl -a /dev/sda` reads the root SSD's SMART data (the 1TB PNY since the 2026-11-09 swap). `smartd` is enabled and running from the package default, so it also watches the drive in the background. Running `smartctl` needs the interactive sudo password; only `apt-get install` is on the passwordless list. The PNY isn't in smartctl's database, so several attributes show as `Unknown_Attribute`.

**tmux**: for the long steps in the disk-swap runbook (`pvmove` in particular), so a dropped ssh session doesn't lose the progress output.

### node and gitleaks (for `openclaw-ro`)

`openclaw-ro` is a read-only, redacted query wrapper for agent probes of OpenClaw. It lives in the private `pickleclaw` repo (`scripts/openclaw-ro/`) and runs from the `/opt/pickleclaw` clone that `services/openclaw/deploy.sh` keeps current, so there is nothing to install for the wrapper itself. It does need two things on the host, both one-time:

**node:** installed on host: `sudo apt install nodejs` (18.19.1 on Ubuntu 24.04). The wrapper runs its redactor with the host's node and refuses to run without it, since the alternative is printing unredacted output. apt puts it at `/usr/bin/node`, which a non-interactive `ssh picklelab ...` finds; a node installed through mise or nvm would not be on that PATH. The redactor's tests pass on 18.19.1.

**gitleaks:** pulled once as an image, pinned by digest:

```bash
ssh picklelab 'docker pull zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f'
```

`docker run` would pull it on first use anyway; doing it up front keeps the first call fast. The wrapper scans its own output with this image (`--network none`) as a backstop for secrets the redactor missed. Bumping gitleaks means changing the tag and digest in `scripts/openclaw-ro/openclaw-ro` in `pickleclaw`.

gitleaks runs only as this image, by decision, so the version is identical on picklelab, the dev VM and in tests. The apt `gitleaks` package is **not** used: Ubuntu 24.04 ships 8.16.0, which has no `stdin` command (it spells that `detect --pipe`) and predates a lot of detection rules. It was installed on this host on 2026-10-02 and should be removed (`sudo apt remove gitleaks`) so nobody reaches for the wrong one.
