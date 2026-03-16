# Network Topology

Last updated: 2026-03-16

## Physical Layout

```
AT&T Fiber
    │
    ▼
AT&T BGW320 (fiber gateway)
    192.168.8.254  —  admin UI: http://192.168.8.254
    WAN: public AT&T IP (AS7018)
    │
    │  (double-NAT — BGW is NOT in IP passthrough mode)
    │
    ▼
UniFi USG 3P (router/firewall)
    WAN: 192.168.8.65  (DHCP from BGW)
    LAN: 192.168.1.1   (gateway for home network)
    │
    ▼
UniFi CloudKey G2 Plus (network controller)
    192.168.1.57
    UI: https://192.168.1.57
    UniFi Network: 10.1.85
```

## Access Points

Five UniFi APs, all wired via ethernet (no wireless uplink/mesh). All PoE from a US 8 PoE 150W switch.

| Location | Model | IP | 2.4GHz ch | 5GHz ch | Notes |
|---|---|---|---|---|---|
| Living Room | U7LR (AC LR) | 192.168.1.42 | 6 / 20MHz | 157 / 40MHz | Central AP, most clients |
| Upstairs | U7HD (AC HD) | 192.168.1.103 | 6 / 20MHz | 157 / 40MHz | Shares ch 6 and ch 157 with Living Room |
| Porch | U7LR (AC LR) | 192.168.1.16 | 11 / 20MHz | 44 / 40MHz | Outdoor/front porch |
| Office (main) | U7PG2 (AC Pro) | 192.168.1.22 | 1 / 20MHz | 40 / 40MHz | |
| Office (far side) | U7PG2 (AC Pro) | 192.168.1.194 | 11 / 20MHz | 44 / 40MHz | Separated from living room by brick wall; wired uplink confirmed clean |

### Channel Plan Notes

2.4GHz uses only the three non-overlapping channels (1 / 6 / 11) — correct. However:
- Living Room and Upstairs both on **ch 6** — they compete with each other
- Porch and Office (far side) both on **ch 11** — same issue

5GHz:
- Living Room and Upstairs share **ch 157**
- Porch and Office (far side) share **ch 44**
- Office (main) is on **ch 40** (unique)

Channel utilization as observed (2026-03-16): Living Room 2.4G at 51% (highest), all 5GHz radios under 10%.

## Key IPs

| Device                  | IP               | Notes                        |
|-------------------------|------------------|------------------------------|
| AT&T BGW320             | 192.168.8.254    | Fiber gateway, admin UI      |
| USG 3P WAN              | 192.168.8.65     | DHCP from BGW                |
| USG 3P LAN              | 192.168.1.1      | Home network gateway         |
| CloudKey G2 Plus        | 192.168.1.57     | UniFi controller             |
| LAN subnet              | 192.168.1.0/24   | DHCP range .6–.254           |

## DNS Configuration

### USG dnsmasq forwarders (as of 2026-03-16)
- Primary:   `8.8.8.8`  (Google)
- Secondary: `8.8.4.4`  (Google)
- Auto DNS Server: disabled (manually set in UniFi UI)
- No `resolv-file` fallback to BGW

### How to change WAN DNS
UniFi UI → Settings → Internet → Internet 1 → Advanced → Manual
Uncheck "Auto DNS Server" → set Primary/Secondary Server fields.
Takes effect immediately on next USG provisioning (often automatic within minutes).

### UniFi config override (if UI is insufficient)
Place `config.gateway.json` at:
```
/usr/lib/unifi/data/sites/default/config.gateway.json
```
Then force provision: Devices → USG → Settings → Manage → Force Provision.

Example to fully control dnsmasq forwarders:
```json
{
  "service": {
    "dns": {
      "forwarding": {
        "options": [
          "no-resolv",
          "server=8.8.8.8",
          "server=8.8.4.4",
          "cname=unifi.technicalpickles.xyz,unifi",
          "host-record=unifi,192.168.1.57"
        ]
      }
    }
  }
}
```

## ISP

- Provider: AT&T Fiber
- ASN: AS7018
- Region: southeastern US (Atlanta area)
- Known peering: AT&T → Cloudflare (AS13335) at `108.162.235.x` (Atlanta)

## Known Issues / History

### AT&T → Cloudflare peering (2026-03-12 to ~2026-03-16) — resolved
See [`investigations/cloudflare-peering-2026-03.md`](investigations/cloudflare-peering-2026-03.md).
Permanent outcome: USG DNS switched from `1.1.1.1` to `8.8.8.8` (also a Cloudflare IP, so switching may have masked the issue rather than AT&T fixing the peering).

## External Status Resources

### ISP / CDN status pages

| Service | URL | What to check |
|---|---|---|
| AT&T | https://www.att.com/outages/ | Broadband outages by address |
| Cloudflare | https://www.cloudflarestatus.com/ | Global / regional incidents |
| Cloudflare Radar | https://radar.cloudflare.com/ | Traffic anomalies, AS-level trends |
| DownDetector (AT&T) | https://downdetector.com/status/att/ | Crowdsourced outage reports |

### BGP / routing tools

| Tool | URL | What to check |
|---|---|---|
| RIPE Stat | https://stat.ripe.net/ | BGP state, prefix visibility, origin ASN — **automated via `just network-status`** |
| BGPview | https://bgpview.io/ | Peering relationships, prefix announcements (manual deep-dive only) |

### Looking glass / traceroute

| Tool | URL | What to check |
|---|---|---|
| AT&T Looking Glass | https://www.att.com/ipservices/lookingglass/ | Route from AT&T's perspective |
| Cloudflare Trace | https://one.one.one.one/cdn-cgi/trace | Your IP, colo, Cloudflare routing |

## Diagnostic Tools

```bash
# Client WiFi and connectivity diagnostic (run on any Mac in the house)
just wifi-diag
just wifi-diag --no-trace --no-speed   # quick version

# UniFi WiFi diagnostics — AP radio stats and per-client signal from the AP side
just unifi-wifi aps                         # all APs: channel, utilization, client count, retries
just unifi-wifi clients                     # all WiFi clients: AP, signal, SNR, rates, satisfaction
just unifi-wifi client <hostname|ip>        # detail for one client

# ISP and CDN status (Cloudflare + Radar BGP/traffic + RIPE BGP state + AT&T outage by ZIP)
just network-status
just network-status 30318

# or directly:
uv run --with requests --with python-dotenv network/isp_status.py
uv run --with requests --with python-dotenv --with playwright network/isp_status.py --zip 30318

# Full network snapshot (BGW + USG + DNS + peering trace)
uv run --with requests --with python-dotenv --with paramiko --with dnspython --with playwright network/snapshot.py
uv run --with requests --with python-dotenv --with paramiko --with dnspython --with playwright network/snapshot.py --no-trace

# BGW diagnostics
uv run --with requests --with playwright network/bgw.py fiber
uv run --with requests --with playwright network/bgw.py broadband
uv run --with requests --with playwright network/bgw.py trace <ip>
uv run --with requests --with playwright network/bgw.py ping <ip>

# USG diagnostics
uv run --with requests --with python-dotenv network/usg.py devices
uv run --with requests --with python-dotenv network/usg.py wan-detail
uv run --with requests --with python-dotenv --with paramiko network/usg.py dns

# DNS comparison across resolvers
uv run --with dnspython network/resolve.py <hostname> [<hostname> ...]

# Profile all requests a browser makes to load a URL — per-hostname latency, errors, pending
# Useful for spotting which CDN/host is slow or failing when a site feels broken
uv run --with playwright network/profile.py <url>
uv run --with playwright network/profile.py <url> --slow-ms 1000 --timeout 15
```
