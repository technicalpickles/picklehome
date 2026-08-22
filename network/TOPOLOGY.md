# Network Topology

Last updated: 2026-03-21

## Physical Layout

```
AT&T Fiber
    │
    ▼
AT&T BGW320 (fiber gateway)
    192.168.8.254  (admin UI: http://192.168.8.254)
    WAN: public AT&T IP (AS7018)
    │
    │  (double-NAT: BGW is NOT in IP passthrough mode)
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

## Tailscale Overlay Network

Tailscale mesh VPN connects devices across the home LAN and external networks.
All devices are on the same tailnet with MagicDNS enabled, so they can reach each
other by hostname (e.g. `picklelab`) or Tailscale IP (`100.x.y.z`).

| Device | Tailscale IP | OS | Role |
|---|---|---|---|
| joshs-macbook-pro | 100.120.123.117 | macOS | Primary workstation |
| picklelab | 100.123.122.68 | linux | Home server (runs climate-auto-switch) |
| iphone182 | 100.125.174.38 | iOS | Josh's iPhone |

To expose a service on one device to another, bind to `0.0.0.0` (not `127.0.0.1`)
and access via Tailscale hostname or IP. No port forwarding or firewall changes needed.

```bash
just tailscale           # show all tailnet devices + status
tailscale ip             # show this device's Tailscale IP
```

## Hardware Inventory

### Infrastructure

| Device | Model | IP | Firmware | Notes |
|---|---|---|---|---|
| AT&T BGW320 | BGW320-505 | 192.168.8.254 | n/a | Fiber gateway; WiFi disabled; admin UI at `http://192.168.8.254` |
| USG 3P | USG 3P | 192.168.8.65 (WAN) / 192.168.1.1 (LAN) | 4.4.57 | Router/firewall |
| CloudKey G2 Plus | n/a | 192.168.1.57 | Network 10.1.85 | UniFi controller; UI at `https://192.168.1.57` |

### Switches

| Name | Model | IP | Firmware | Notes |
|---|---|---|---|---|
| US 8 PoE 150W | US 8 PoE 150W | 192.168.1.134 | 7.0.50 | Main PoE switch: powers all APs |
| US 24 | US 24 | 192.168.1.99 | 7.0.50 | |
| US 8 | US 8 | 192.168.1.17 | 7.0.50 | |
| US 8 | US 8 | 192.168.1.25 | 5.76.7 | **Offline** |

### Access Points

Five UniFi APs, all wired via ethernet (no wireless uplink/mesh). All PoE from the US 8 PoE 150W.

| Name | Model Code | Model | IP | Firmware | Floor | Mount | Antenna | Notes |
|---|---|---|---|---|---|---|---|---|
| Living Room AC LR | U7LR | AC Long Range | 192.168.1.42 | 6.6.65 | 1st | Floor, facing up | High-gain focused beam | Central AP, most clients; open stairwell nearby |
| Upstairs AC HD | U7HD | AC High Density | 192.168.1.103 | 6.6.65 | 2nd | Ceiling | Wide uniform | Above/near the stairwell opening |
| Josh Office AC Pro | U7PG2 | AC Pro | 192.168.1.22 | 6.6.65 | 1st | Floor under desk, facing up | Standard omni | Same room as Porch AP (co-located) |
| Tracy Office AC Pro | U7PG2 | AC Pro | 192.168.1.194 | 6.6.65 | 1st | Floor, facing up | Standard omni | Converted carport; brick wall between it and main house |
| Porch AC LR | U7LR | AC Long Range | 192.168.1.16 | 6.6.65 | 1st | Was: exterior wall, horizontal, facing backyard | High-gain focused beam | **Offline**: currently in Josh's office; pending relocation; see `docs/outdoor-wifi-research.md` |

> **Live state:** Run `just unifi topology` for the full device tree with uplink ports and radio state.
> Run `just unifi wifi aps` for current channels, utilization, retries, and tx power.
> Run `just unifi wifi config` for SSID settings and per-AP power mode.
> Run `just unifi devices` for all adopted devices with firmware versions.
> Use `just unifi topology --format mermaid` to generate a diagram for docs.

### Room Registry

Stable room IDs, so docs/investigations/floorplan annotations can reference an exact
room instead of an ambiguous name (e.g. "TV room" wasn't documented anywhere before the
2026-08-20 investigation, and turned out to be a distinct room between Living Room and
Josh Office, not a synonym for either). Format: `<floor>-<kebab-case-slug>`. IDs are
assigned once and never renumbered or reused, same rule as taskwarrior UUIDs and plan
step slugs — if a room needs splitting later (e.g. "upstairs" turns out to be three
rooms), give the new rooms new IDs rather than repurposing the old one.

Floors: `1` = ground floor (same level as the garage/entry), `2` = upper floor.

| Room ID | Common name | Floor | Notes | Status |
|---|---|---|---|---|
| `1-living-room` | Living Room | 1 | Has Living Room AC LR; L-shaped, runs from TV Room past the stairwell nook to Kitchen/Dining/Entry | confirmed |
| `1-josh-office` | Josh's Office | 1 | Has Josh Office AC Pro + offline Porch AC LR (co-located) | confirmed |
| `1-tracy-office` | Tracy's Office | 1 | Converted carport; brick wall between it and main house | confirmed |
| `1-tv-room` | TV Room | 1 | Between Living Room and Josh's Office; single doorway to Living Room; site of the 2026-08-20 roaming investigation | confirmed |
| `1-porch` | Porch / backyard | 1 (exterior) | Porch AC LR's original/intended mount location, facing backyard; currently offline, relocation pending | confirmed |
| `1-gym-bathroom` | Gym Bathroom | 1 | Spans the front of the house above/beside Josh's Office; largest 1st-floor room (214.69 sqft) | confirmed |
| `1-kitchen` | Kitchen | 1 | Open to Living Room, no dividing wall | confirmed |
| `1-dining-room` | Dining Room | 1 | Open to Kitchen/Living Room | confirmed |
| `1-entry` | Entry | 1 | Front door, off the angled bay window nook east of Living Room | confirmed |
| `2-hallway` | Upstairs Hallway | 2 | Central 2nd-floor room (211.66 sqft); has Upstairs AC HD, ceiling-mounted. Its NW corner (just below `2-bathroom`) lines up with the upper part of `1-living-room` (open concept), which contains the stairwell landing. Resolves former `2-upstairs-tbd` placeholder | confirmed (user-verified corner alignment) |
| `2-bathroom` | Bathroom above Josh's Office | 2 | Footprint sits above `1-gym-bathroom` + `1-josh-office`; referenced in `CHANGELOG.md` (2026-03-20 Tracy Office channel note) as a spot with 3 distinct 5GHz APs in range. Resolves former `2-bathroom-above-office` placeholder | confirmed (floorplan-estimated alignment, see Room Layout below) |
| `2-bedroom` | Primary Bedroom | 2 | Above `1-tv-room`'s footprint; NE corner matches `1-tv-room`'s NE corner (same orientation, user-verified); largest 2nd-floor room (237.98 sqft) | confirmed (user-verified corner alignment) |
| `2-alex-bedroom` | Alex's Bedroom | 2 | Off `2-hallway` | confirmed |
| `2-playroom` | Playroom | 2 | Off `2-hallway` | confirmed |
| `2-laundry` | Laundry | 2 | Off `2-hallway`, near `2-bathroom` | confirmed |
| `2-storage` | Storage | 2 | Off `2-bedroom` | confirmed |

**Alignment caveat:** initially resolved from the MagicPlan "Sketch Files" PNG/SVG
exports (2026-08-22, stored in Dropbox — see Room Layout below) by matching room
footprints and printed dimensions between the two independently-scanned floor images —
a visual estimate, not the precision overlay `docs/floorplan-markup-legend.md` calls
for. Two corners were then user-verified in person against the actual house (not just
the floorplan image): `1-tv-room`'s NE corner = `2-bedroom`'s NE corner (confirms same
orientation), and `2-hallway`'s NW corner (just below `2-bathroom`) lines up with the
upper part of open-concept `1-living-room`. `2-bathroom`'s alignment over
`1-gym-bathroom`/`1-josh-office` is still the unverified visual estimate.

### Room Layout

From the MagicPlan "Sketch Files" export (both floors, dimensioned; captured 2026-08-22,
stored in `~/Dropbox/2108 Marann Dr Floor Plans/` rather than the vault — see Storage
note in `docs/floorplan-markup-legend.md`). No wall-material or floor-penetration
markup pass has been done yet (per `docs/floorplan-capture-checklist.md`); this is
adjacency + rough distance only.

**1st floor:** `1-gym-bathroom` spans the front of the house. Below/beside it,
`1-josh-office` (+ a small bathroom/shower) sits on the west side and `1-tv-room` on
the east side, connected to `1-living-room` by a single doorway (no other wall between
them). `1-living-room` is L-shaped, running from `1-tv-room` past a central stairwell
nook down to `1-kitchen`/`1-dining-room`/`1-entry`. `1-tracy-office` is a separate wing
(converted carport) off the south end, with the already-documented brick dividing wall.

**2nd floor:** footprint sits only over the `1-gym-bathroom` / `1-josh-office` /
`1-tv-room` block, not over the kitchen/dining/entry/Tracy-office wing (those read as
single-story from the floorplan extents). `2-bathroom` (top-left) lines up over
`1-gym-bathroom` + `1-josh-office` (visual estimate, unverified). `2-bedroom` (top-right)
lines up over `1-tv-room` — user-verified: their NE corners are the same corner, same
orientation. `2-hallway`'s NW corner (just below `2-bathroom`) lines up with the upper
part of `1-living-room` — also user-verified. `1-living-room` is open concept, so this
is the same stairwell-landing/Upstairs-AC-HD area the AP table's "open stairwell
connects Living Room and Upstairs" note and `docs/24ghz-power-tuning.md` already
describe, now with a confirmed corner instead of a guess.

**TV Room finding (reopens the 2026-08-20 open question):** `1-tv-room` is a short
hop from Living Room AC LR, roughly 10-15 ft through a single doorway, both rooms part
of the same open ground-floor pod — not a long-range or heavy-material path. That means
the observed -64 to -75 dBm in `1-tv-room` is **not** well explained by simple
distance/wall-material path loss. The more likely explanation: Living Room AC LR is
floor-mounted facing up with a high-gain *focused* beam, tuned (per
`docs/24ghz-power-tuning.md`) for vertical throw up through the open stairwell to reach
`2-hallway` — that vertical focus plausibly trades off horizontal spread through
`1-tv-room`'s doorway, producing a real coverage gap despite the short physical
distance, not measurement noise.

This reframes the two still-open threads from the 2026-08-20 investigation as separate
problems: leveling Josh Office AC Pro's tx power (task 385's follow-up) addresses
*roaming* onto a weaker AP, not `1-tv-room`'s baseline weak signal from Living Room AC
LR — that's an antenna-pattern/coverage problem, closer to task 386 (an AP better
angled to cover `1-tv-room`, e.g. redeploying Porch AC LR to an interior wall aimed
into `1-tv-room`/`1-living-room` instead of outdoors) than a tx-power tweak.

### AP Model Characteristics

| Model | 2.4 GHz Max | 5 GHz Max | Design Intent |
|---|---|---|---|
| U7LR (AC Long Range) | 24 dBm | 22 dBm | Focused high-gain antenna for long range; reaches further than needed in a home |
| U7HD (AC High Density) | 25 dBm | 25 dBm | Wide coverage for many clients in smaller area; highest raw power |
| U7PG2 (AC Pro) | 22 dBm | 22 dBm | Balanced omnidirectional; lowest max power of the three |

---

## Channel & Power Plan

**This section documents _why_ the current configuration exists.** Update entries in-place
when making changes, don't append. For change history, see `CHANGELOG.md`.

### 2.4 GHz Channel Assignments

Only three non-overlapping channels exist: **1, 6, 11**. Dense neighborhood means all three
are congested with 70-110 external neighbors each. Channel selection is about minimizing
*internal* co-channel between our own APs, not avoiding neighbors.

| Channel | APs | Why |
|---|---|---|
| **1** | Josh Office, Tracy Office | Offices are on opposite sides of the house, so co-channel is acceptable at this distance |
| **6** | Living Room | Only AP on ch 6 after Upstairs moved to ch 11 (2026-03-21) |
| **11** | Upstairs | Moved from ch 6 to eliminate co-channel with Living Room through open stairwell. **Porch will conflict when it comes back**: re-plan at that point (only 3 channels for 5 APs) |

### 5 GHz Channel Assignments

5 GHz is much cleaner: shorter range through walls means fewer neighbor conflicts.

| Channel | APs | Why |
|---|---|---|
| **40** | Josh Office | Cleanest 5 GHz channel (fewest neighbors, all weak) |
| **48** | Tracy Office, Porch (offline) | Clean since BGW WiFi was disabled (was interfering at -13 dBm). Tracy moved here from ch 40 (2026-03-20) so phones in the bathroom above Josh's office see three distinct channels and roam cleanly |
| **149** | Living Room | Moved from ch 157 (2026-03-16) to avoid co-channel with Upstairs. Moderate neighbor count but low utilization |
| **157** | Upstairs | Low neighbor count, reasonable interference levels |

### 2.4 GHz Power Plan

| AP | Mode | Actual | Why |
|---|---|---|---|
| Living Room AC LR | medium | ~15 dBm | Reduced from max/17 dBm (2026-03-21): LR's high-gain antenna was pushing signal through open stairwell into Upstairs zone; all 2.4 GHz clients have strong signal. See `docs/24ghz-power-tuning.md` |
| Upstairs AC HD | medium | ~16 dBm | Reduced from max/19 dBm (2026-03-21): was blasting down through stairwell; only 1-2 clients on this radio |
| Josh Office AC Pro | max | 15 dBm | Left at max: AC Pro max (22 dBm) produces only 15 dBm; already moderate |
| Tracy Office AC Pro | max | 15 dBm | Same as Josh Office: AC Pro's max is naturally lower than LR/HD |

### 5 GHz Power Plan

All APs set to **medium** (2026-03-17). Reduced from max to limit cell overlap and
reduce iPhone roaming churn: Tracy's phone was showing 11 roam segments/hour at max power.
See CHANGELOG.md 2026-03-17 entry.

| AP | Actual (medium) | Max |
|---|---|---|
| Josh Office AC Pro | 14 dBm | 22 dBm |
| Living Room AC LR | 13 dBm | 22 dBm |
| Tracy Office AC Pro | 14 dBm | 22 dBm |
| Upstairs AC HD | 16 dBm | 25 dBm |

### Constraints & Trade-offs

- **Only 3 non-overlapping 2.4 GHz channels for 5 APs**: co-channel is unavoidable somewhere.
  Current strategy: pair APs that are physically distant on the same channel.
- **Open stairwell** between Living Room (1st floor) and Upstairs (2nd floor) means RF
  travels freely between floors, so power reduction and channel separation both matter here.
- **AC-LR "Long Range" antenna** on Living Room is a liability: its focused beam amplifies
  vertical leakage through the stairwell. Would benefit from replacement with an AC Pro or
  similar omnidirectional AP if other changes are being made.
- **Porch AP return will force a re-plan**: it was on ch 11 (2.4 GHz) and ch 48 (5 GHz).
  Ch 11 now conflicts with Upstairs; ch 48 shares with Tracy Office.

### Inspecting & Changing Configuration

```bash
# Current state
just unifi wifi aps                              # channels, power, utilization, retries
just unifi wifi config                           # SSID settings + per-AP power mode
just unifi wifi rfscan --summary --fresh 60      # neighbor congestion per channel

# Make changes (prompts for confirmation unless --yes)
just unifi wifi set-channel "tracy" 5 36
just unifi wifi set-power "living" 2.4 medium --yes
```

**After any change:** update this section's rationale, add a CHANGELOG.md entry, and verify
with `just unifi wifi aps`.

## BGW320

Hardware details and CGI endpoint reference: [`docs/bgw-reference.md`](docs/bgw-reference.md).

### Resolved: WiFi "Disabled" but still beaconing (2026-03-18, resolved 2026-03-20)

Both radios set to Disabled via `wconfig_unified.ha`. UI and `just bgw wifi` confirm
Disabled, but `ATTt6kgiKH` (BSSID `bc:9a:8e:ed:fe:ec`) continued beaconing on 5GHz
ch 149 at -50 dBm after a full restart, confirmed via `just unifi wifi rfscan --fresh 5`.
Channel also shifted from ch 48 → ch 149 while "disabled," indicating the radio is still
active. Resolved without factory reset: 2026-03-20 RF scan shows no trace of the SSID
or BSSID. The disable eventually propagated (possibly after the BGW restart settled).

## Key IPs

| Device                  | IP               | Notes                        |
|-------------------------|------------------|------------------------------|
| AT&T BGW320             | 192.168.8.254    | Fiber gateway, admin UI      |
| USG 3P WAN              | 192.168.8.65     | DHCP from BGW                |
| USG 3P LAN              | 192.168.1.1      | Home network gateway         |
| CloudKey G2 Plus        | 192.168.1.57     | UniFi controller             |
| LAN subnet              | 192.168.1.0/24   | DHCP range .6 to .254        |

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

### AT&T → Cloudflare peering (2026-03-12 to ~2026-03-16): resolved
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
| RIPE Stat | https://stat.ripe.net/ | BGP state, prefix visibility, origin ASN (**automated via `just network-status`**) |
| BGPview | https://bgpview.io/ | Peering relationships, prefix announcements (manual deep-dive only) |

### Looking glass / traceroute

| Tool | URL | What to check |
|---|---|---|
| AT&T Looking Glass | https://www.att.com/ipservices/lookingglass/ | Route from AT&T's perspective |
| Cloudflare Trace | https://one.one.one.one/cdn-cgi/trace | Your IP, colo, Cloudflare routing |

## Diagnostic Tools

> **Note:** The authoritative CLI reference is in `network/CLAUDE.md`. This section is a
> quick-reference subset. When in doubt, check `just --list` or `just unifi --help`.

```bash
# Live topology: device tree with uplink ports and radio state
just unifi topology                              # text tree (default)
just unifi topology --format mermaid             # mermaid diagram for docs
just unifi topology --format dot                 # graphviz DOT

# Quick network health check (AP retries + RF neighbors + watched device roaming)
just unifi checkup
just unifi checkup --sessions 3

# WiFi diagnostics: AP perspective
just unifi wifi aps                              # channels, utilization, retries, power
just unifi wifi aps --sort retries               # worst retries first
just unifi clients                               # all connected WiFi clients
just unifi client <hostname|ip>                  # detail for one client
just unifi wifi roaming                          # roaming for all watched devices
just unifi wifi roaming <hostname> --sessions 5  # roaming for one device
just unifi wifi rfscan --summary --fresh 60      # neighbor congestion summary
just unifi wifi config                           # SSID settings + per-AP power mode

# WiFi diagnostics: client perspective (run on any Mac)
just wifi-diag
just wifi-diag --no-trace --no-speed

# Infrastructure
just unifi devices                               # all adopted devices + firmware
just unifi usg wan-detail                        # WAN IP, gateway, DNS, counters
just bgw fiber                                   # BGW fiber signal / optical metrics
just bgw broadband                               # WAN connection status

# ISP and CDN status
just network-status                              # Cloudflare + Radar BGP + RIPE BGP state
just network-status 30318                        # + AT&T outage check by ZIP

# Raw API: last resort for debugging
just unifi api get /stat/device
just unifi api get /stat/sta
```
