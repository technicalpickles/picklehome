# seapickle: beach house Raspberry Pi

A Raspberry Pi 3B+ at the beach house, reachable over Tailscale, for
monitoring and debugging network and smart-device issues remotely. A sea
pickle is a real marine animal, keeping with the `picklelab` naming theme —
this is the pickle at the sea.

Everything at the beach house is cloud-controlled (Hisense mini-splits via
ConnectLife, Nest, Yale locks), so when something "stops working" the first
question is always "was the internet down?" — and until now there was nothing
on-site to answer it. seapickle is:

1. **A jump box:** SSH over Tailscale (`ssh seapickle.<tailnet>.ts.net`),
   no public exposure, no password auth.
2. **A subnet router:** advertises the beach house LAN over Tailscale so
   local device UIs (router admin page, anything with a local interface)
   are reachable from anywhere.
3. **A debug toolkit:** `mtr`, `iperf3`, `tcpdump`, `nmap`, `arp-scan`,
   `dig`, Ookla `speedtest` — ready to run interactively over SSH.
4. **A connectivity recorder:** a 5-minute probe of the gateway, DNS, and
   the cloud endpoints the smart devices depend on, plus a daily speedtest,
   logged locally. When a device was unreachable at 3am Tuesday, the log
   says whether the internet was up.

## Hardware and OS

- **Hardware:** Raspberry Pi 3B+ (1GB RAM, 100Mbps ethernet). Use ethernet
  if at all possible; the probe data is meaningless if the Pi itself is on
  flaky wifi.
- **OS:** Raspberry Pi OS **Lite 64-bit** (current stable). Headless Lite
  idles around 100–150MB, leaving plenty of the 1GB free for this workload.
  64-bit because modern binaries (Tailscale, Ookla speedtest) all ship
  arm64. No Docker: on 1GB with an SD card, plain apt packages + systemd
  timers are lighter and easier to debug over a remote link.

## Setup

### 1. Flash the SD card

In Raspberry Pi Imager, choose **Raspberry Pi OS Lite (64-bit)** and use the
OS customisation settings:

- Hostname: `seapickle`
- Enable SSH, **public-key auth only** (paste your key — the public key of
  the machine you'll SSH *from*, e.g. `~/.ssh/id_ed25519.pub` on the Mac)
- Username: `pickles` (or whatever — nothing here assumes a name)
- Skip wifi config if the Pi will be on ethernet

#### Flashing from a Steam Deck (Desktop Mode)

No computer with an SD slot handy? The Deck works: SteamOS runs entirely off
internal storage, so its microSD slot is free to use for flashing.

1. Switch to Desktop Mode. Install Raspberry Pi Imager from Discover, or:

   ```bash
   flatpak install flathub org.raspberrypi.rpi-imager
   ```

   Flatpaks install to the home partition, so no `steamos-readonly` fiddling.
   Note this is a community-maintained Flathub package (Raspberry Pi only
   officially ships a .deb); its "Use custom image" option is broken, but the
   normal choose-OS-from-the-list flow used here works fine.
2. Close any running games, eject the games microSD via the Disks & Devices
   tray applet, and swap in the Pi's card. **Label the cards** — Imager
   erases whatever card is inserted. Ignore/dismiss any KDE mount prompts;
   Imager writes to the raw device.
3. Run Imager with the OS choice + customisation settings above. If the
   flatpak can't see the internal card reader, use a USB card reader via a
   dock instead (or fall back to `dd` from Konsole).
4. Eject the flashed card, put the games card back, and only **then** return
   to Game Mode — Game Mode offers to format unrecognised cards, which would
   wipe the freshly flashed Pi card.

### 2. First boot + bootstrap

Boot the Pi on the beach house LAN, find it (`ping seapickle.local` or check
the router's client list), and copy this directory over:

```bash
scp -r homelab/seapickle/ pickles@seapickle.local:
ssh pickles@seapickle.local
sudo ./seapickle/bootstrap.sh 192.168.x.0/24   # the beach house subnet
```

The subnet is passed as an argument (and remembered on the Pi) so it never
lives in git — beach house network details are sensitive per
`docs/CONVENTIONS.md`. Record it in agent memory / 1Password instead.

The script is idempotent — re-run it after changing probe scripts or to
converge a drifted setup. It:

- installs the debug toolkit, Ookla speedtest, and Tailscale
- applies low-RAM / SD-wear tuning (`gpu_mem=16`, zram swap, capped journald)
- enables IP forwarding for subnet routing
- installs the probe scripts + systemd timers and starts them

### 3. Bring up Tailscale

The script prints the exact command; it looks like:

```bash
sudo tailscale up --ssh --advertise-routes=192.168.x.0/24 --hostname=seapickle
```

Then in the [Tailscale admin console](https://login.tailscale.com/admin/machines):

- approve the machine (if device approval is on)
- **approve the advertised subnet route** (Machines → seapickle → Edit route settings)
- disable key expiry for this node (it's a headless appliance)

### 4. Verify from the laptop

```bash
ssh seapickle.tail2023b7.ts.net          # Tailscale SSH
systemctl list-timers 'seapickle-*'      # both timers scheduled
tail /var/log/seapickle/net-probe.jsonl  # entries appearing every 5 min
ping 192.168.x.1                         # beach house router via subnet route
```

## What the probes record

`seapickle-net-probe` (every 5 minutes) appends one JSON line to
`/var/log/seapickle/net-probe.jsonl`:

- ping RTT to the LAN gateway (local network up?)
- ping RTT to 1.1.1.1 (WAN up?)
- DNS resolution (resolver working?)
- HTTPS reachability + latency for the clouds the beach house devices need:
  - `clife-eu-gateway.hijuconn.com` — Hisense mini-splits (ConnectLife)
  - `smartdevicemanagement.googleapis.com` — Nest
  - `api-production.august.com` — Yale locks

`seapickle-speedtest` (daily, randomized hour) appends Ookla JSON to
`/var/log/seapickle/speedtest.jsonl`. Daily only — don't burn unknown beach
house bandwidth on frequent speedtests.

Both logs rotate via logrotate (4 weekly rotations, compressed). Quick looks:

```bash
# probes where the WAN was down
jq -r 'select(.wan_ping_ms == null) | .ts' /var/log/seapickle/net-probe.jsonl

# cloud latency over time for the mini-splits
jq -r '[.ts, .clouds.connectlife.ms] | @tsv' /var/log/seapickle/net-probe.jsonl

# speedtest history
jq -r '[.timestamp, (.download.bandwidth*8/1e6|floor), (.upload.bandwidth*8/1e6|floor)] | @tsv' \
  /var/log/seapickle/speedtest.jsonl
```

## Site survey (fill in on first visit)

Nothing about the beach house network is documented. On the first on-site
visit, record (in agent memory / 1Password — **not** in git):

- [ ] ISP and plan speed
- [ ] Modem/router make + model, admin UI address + credentials (1Password)
- [ ] LAN subnet and gateway IP
- [ ] Wifi SSID(s) and which band(s)
- [ ] `sudo arp-scan --localnet` output: what's on the network (mini-split
      heads, Nest devices, locks bridge, etc.) and whether devices are on
      wifi or ethernet
- [ ] Where the Pi physically lives + how it's powered (UPS? outlet that
      guests might unplug?)

## Files

| File | Purpose |
|------|---------|
| `bootstrap.sh` | Idempotent setup script, run as root on the Pi |
| `net-probe.sh` | 5-minute connectivity probe (installed to `/usr/local/lib/seapickle/`) |
| `speedtest-probe.sh` | Daily speedtest wrapper |
| `seapickle-net-probe.service` / `.timer` | systemd units for the probe |
| `seapickle-speedtest.service` / `.timer` | systemd units for the speedtest |

Unlike `homelab/services/*`, there is no `deploy.sh`/compose here: the Pi is
not on the picklelab deploy path. To update after changing scripts, copy the
directory over again and re-run `bootstrap.sh` (no argument needed — the
subnet is remembered in `/etc/seapickle/subnet`).

## Maybe later (deliberately not in v1)

- Repo checkout + `uv` on the Pi to run the existing CLIs (`just hisense`,
  `just nest`) from inside the beach house LAN
- Uptime Kuma or node_exporter + a scrape from picklelab, if the JSONL logs
  prove too crude
- Shipping probe logs off-box (e.g. rsync to picklelab) so history survives
  SD card death
- Wifi client-mode probe (a USB wifi dongle pinging through the beach house
  wifi, to tell "wifi is bad" apart from "internet is bad")
