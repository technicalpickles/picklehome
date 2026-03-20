# Network Topology

Last updated: 2026-03-20

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
| Living Room | U7LR (AC LR) | 192.168.1.42 | 6 / 20MHz | 149 / 40MHz | Central AP, most clients |
| Upstairs | U7HD (AC HD) | 192.168.1.103 | 6 / 20MHz | 157 / 40MHz | |
| Porch | U7LR (AC LR) | 192.168.1.16 | 11 / 20MHz | 48 / 40MHz | **Offline** — pending relocation; see `docs/outdoor-wifi-research.md` |
| Office (main / Josh) | U7PG2 (AC Pro) | 192.168.1.22 | 1 / 20MHz | 40 / 40MHz | |
| Office (far side / Tracy) | U7PG2 (AC Pro) | 192.168.1.194 | 1 / 20MHz | 48 / 40MHz | Separated from Josh Office by full house; wired uplink confirmed clean |

### Channel Plan Notes

2.4GHz uses only the three non-overlapping channels (1 / 6 / 11) — correct. However:
- Living Room and Upstairs both on **ch 6** — they compete with each other
- Porch and Office (far side) both on **ch 11** — same issue

5GHz (as of 2026-03-19 after optimization):
- Living Room on **ch 149** (moved from 157 to avoid co-channel with Upstairs)
- Upstairs on **ch 157**
- Porch on **ch 48** (offline — pending relocation)
- Office (Tracy) on **ch 48** (moved from 40 on 2026-03-20 to reduce roaming churn)
- Office (Josh) on **ch 40**

Channel utilization as observed (2026-03-16): Living Room 2.4G at 51% (highest), all 5GHz radios under 10%.

**RF scan summary (2026-03-20):** 2.4GHz heavily congested on all three non-overlapping channels (146–157 neighbors each) — dense neighborhood, nothing actionable. 5GHz neighbor counts:
- ch 40: 17 neighbors, strongest −86 dBm (cleanest)
- ch 149: 30 neighbors, strongest −79 dBm (moderate — Living Room is here)
- ch 157: 12 neighbors, strongest −70 dBm (reasonable)

**Channel change history:** Tracy Office moved from ch 44 → ch 40 on 2026-03-19. Both offices share ch 40 but are on opposite sides of the house — no co-channel concern.

### Changing Channels

```bash
# See current channels and RF environment
just unifi-wifi aps
just unifi-wifi rfscan

# Change a channel (prompts for confirmation unless --yes)
just unifi-wifi set-channel "tracy" 5 36
just unifi-wifi set-channel "porch" 5 48 --yes

# Validate the change took (config vs. live stats may lag by ~30s)
just unifi-api get /stat/device | python3 -c "
import json, sys
for d in json.load(sys.stdin)['data']:
    if d.get('type') == 'uap':
        cfg  = {r['radio']: r.get('channel') for r in d.get('radio_table', [])}
        live = {r['radio']: r.get('channel') for r in d.get('radio_table_stats', [])}
        print(d['name'], '| config:', cfg, '| live:', live)
"
```

**Important:** `just unifi-wifi aps` reads `radio_table_stats` (live observed), which lags after a change. Use `just unifi-api get /stat/device` and compare `radio_table` (config) vs `radio_table_stats` (live) to confirm the change was accepted before the radio fully transitions.

**Confirmed valid 5GHz channels** (tested via API): 40, 44, 48, 157. Channels 36 and 149 are untested with the current AP models (U7LR, U7PG2, U7HD).

## BGW320

Hardware details and CGI endpoint reference: [`docs/bgw-reference.md`](docs/bgw-reference.md).

### Resolved: WiFi "Disabled" but still beaconing (2026-03-18, resolved 2026-03-20)

Both radios set to Disabled via `wconfig_unified.ha`. UI and `just bgw wifi` confirm
Disabled, but `ATTt6kgiKH` (BSSID `bc:9a:8e:ed:fe:ec`) continued beaconing on 5GHz
ch 149 at -50 dBm after a full restart — confirmed via `just unifi-wifi rfscan --fresh 5`.
Channel also shifted from ch 48 → ch 149 while "disabled," indicating the radio is still
active. Resolved without factory reset — 2026-03-20 RF scan shows no trace of the SSID
or BSSID. The disable eventually propagated (possibly after the BGW restart settled).

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
just unifi-wifi rfscan                      # neighboring APs by channel — congestion summary
just unifi-wifi set-channel <ap> <band> <ch> [--yes]  # change AP radio channel

# Raw UniFi API — for debugging/exploration
just unifi-api get /stat/device
just unifi-api get /stat/sta
just unifi-api put /rest/device/<id> '{"radio_table": [...]}'

# ISP and CDN status (Cloudflare + Radar BGP/traffic + RIPE BGP state + AT&T outage by ZIP)
just network-status
just network-status 30318
```
