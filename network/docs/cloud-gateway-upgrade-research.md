# Cloud Gateway Upgrade Research

Research on replacing CloudKey Gen2 Plus + USG with a unified Cloud Gateway.
Conducted 2026-03-20.

---

## Context

- **Current gear:** CloudKey Gen2 Plus (rack-mounted, controller) + USG (original, gateway)
- **Age:** ~5 years without hardware upgrade
- **Goal:** Single rack-mountable device replacing both, unlocking modern UniFi features
  (WiFiMan Floor Plan, InnerSpace, usable IDS/IPS, WireGuard VPN)
- **Constraint:** Must be rack-mountable (1U preferred)

---

## Bottom Line

**UDM SE ($499) is the best fit.** It's 1U rack-mount, replaces CloudKey + USG + potentially
a PoE switch in one box, and unlocks all modern UniFi features. The built-in 8-port PoE
switch (180W) can power APs directly. Migration is backup → restore → swap cables.

---

## Rack-Mountable Cloud Gateways (1U)

All three replace both CloudKey and USG. All include: 10G SFP+ WAN, 2.5GbE WAN,
8x GbE LAN, 10G SFP+ LAN, built-in NVR for Protect.

| Model | Price | CPU | RAM | IDS/IPS | PoE | HDD Bays | Best For |
|---|---|---|---|---|---|---|---|
| **UDM Pro** | $379 | ARM A57 1.7GHz | 4 GB | 3.5 Gbps | No | 1x 3.5" | Budget rack option |
| **UDM SE** | $499 | ARM A57 1.7GHz | 4 GB | 3.5 Gbps | **Yes** (8-port, 180W) | 1x 3.5" | Home rack with PoE |
| **UDM Pro Max** | $599 | ARM A57 2.0GHz | 8 GB | 5 Gbps | No | 2x 3.5" (RAID) | Max headroom / RAID |

### UDM SE PoE Details

8 LAN ports total: 6x PoE (802.3af), 2x PoE+ (802.3at), 180W total budget.
Enough for several APs and a few cameras without a separate PoE switch.

### Why Not the Others

- **UDM Pro ($379):** $120 less but no PoE, so you need to keep or buy a separate PoE switch.
- **UDM Pro Max ($599):** Faster CPU, more RAM, RAID HDD, 5 Gbps IPS, but no PoE.
  Extra horsepower is unnecessary for a home network with <30 devices.

---

## Non-Rack Cloud Gateways (small box)

These work but need a third-party rack shelf or bracket.

| Model | Price | IDS/IPS | LAN Ports | Notable |
|---|---|---|---|---|
| **UCG-Ultra** | $129 | 1 Gbps | 4x GbE | Cheapest Cloud Gateway |
| **UCG-Max** | $199-279 | 2.3 Gbps | 4x 2.5GbE | NVMe slot for storage |
| **UCG-Fiber** | $279 | 5 Gbps | 3x 2.5GbE | 2x 10G SFP+ WAN |

No PoE, no HDD bays (UCG-Max/Fiber have NVMe), smaller device/client limits.

---

## Features Unlocked by Upgrading

### Blocked on CloudKey + USG (available on Cloud Gateways)

- **WiFiMan Floor Plan Mapper**: LiDAR-based walk survey heatmaps (see wifi-survey-tools.md)
- **InnerSpace**: floor plan with live WiFi coverage from real devices
- **Usable IDS/IPS**: USG maxes out at ~85 Mbps with IDS/IPS; Cloud Gateways do 3.5-5 Gbps
- **WireGuard VPN**: fast built-in VPN (replaces L2TP/IPsec on USG)
- **Teleport VPN**: one-tap remote access from UniFi mobile app
- **Site Magic**: multi-site VPN mesh

### General Ecosystem Improvements (last ~5 years)

- **UniFi OS**: unified platform, all apps run as containers (Network, Protect, etc.)
- **Network Application 9.x**: improved dashboard, topology views, client insights, DPI
- **Protect**: AI smart detections (person, vehicle, animal, package), better timeline/search
- **WiFi 7 APs**: current generation (U7 series), tri-band with 6 GHz, MLO

---

## WiFi 7 AP Lineup (current generation)

Not required for the gateway upgrade, but relevant context for future planning.

| Model | Price | Bands | Streams | Notable |
|---|---|---|---|---|
| U7 Lite | ~$99-139 | Dual-band | 4 | Budget |
| **U7 Pro** | $189 | **Tri-band (6 GHz)** | 6 | Sweet spot |
| U7 Pro Max | ~$249 | Tri-band (6 GHz) | 8 | Dedicated scanning radio |
| U7 Pro Wall | $199 | Tri-band (6 GHz) | 6 | In-wall, 2.5GbE passthrough |
| U7 Pro Outdoor | ~$299 | Tri-band (6 GHz) | 6 | IP67, outdoor |

Existing WiFi 5/6 APs continue to work; upgrade is optional and incremental.

---

## Migration: CloudKey Gen2 + USG → Cloud Gateway

### Process

1. Update CloudKey to latest UniFi OS and Network Application version
2. Create backup: Settings → System → Backups → Download
3. Set up new Cloud Gateway, update firmware to same or newer Network version
4. Restore backup: Settings → System → Backups → Import
5. Swap WAN cable from USG to new gateway, connect LAN port to existing switch
6. APs and switches should re-adopt automatically (they retain inform URL)
7. If gateway IP changed, SSH into devices and run `set-inform`

### Gotchas

- **Protect recordings do NOT transfer.** HDD starts fresh on the new device. Keep
  CloudKey powered on temporarily if you need access to old footage.
- **Camera re-adoption** can be finicky; some may need factory reset to connect to
  Protect on the new gateway.
- **New gateway must run UniFi OS 3.1+** for cross-device backup restore.
- **Gateway IP should match.** If USG was 192.168.1.1, new gateway should be too.
  The backup should handle this, but verify.
- **No multi-site on Cloud Gateways.** One site per device (fine for home use).
- **WireGuard/Teleport VPN** are new features; set up fresh after migration.

---

## References

- [UniFi Gateway Comparison 2026, iFeeltech](https://ifeeltech.com/blog/unifi-gateway-comparison-guide)
- [UDM Pro Max Review, Dong Knows Tech](https://dongknows.com/ubiquiti-dream-machine-pro-max-udm-pro-max-review/)
- [Cloud Gateway Max Review, Dong Knows Tech](https://dongknows.com/ubiquiti-cloud-gateway-max-review/)
- [UniFi Cloud Gateways Tech Specs](https://techspecs.ui.com/unifi/cloud-gateways/compare)
- [Migrate CloudKey & USG to UDM-Pro, TechBits](https://techbits.io/migrate-unifi-cloudkey-usg-udm-pro/)
- [Migrate CloudKey and USG to UCG-Max, Edd Grant](https://www.eddgrant.com/blog/2025/09/10/migrating-unifi-cloud-key-and-usg-to-ucg-max)
- [Backups and Migration in UniFi, Ubiquiti Help](https://help.ui.com/hc/en-us/articles/360008976393-Backups-and-Migration-in-UniFi)
