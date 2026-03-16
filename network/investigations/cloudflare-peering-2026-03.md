# Investigation: AT&T → Cloudflare Peering Loss (2026-03)

**Status:** Resolved ~2026-03-16 — cause of resolution unclear.
**Period:** 2026-03-12 to ~2026-03-16.
**Finding:** ~47% packet loss at `108.162.235.59` (AT&T AS7018 → Cloudflare AS13335 peering, Atlanta), affecting all Cloudflare-hosted sites and `1.1.1.1` DNS.
**Resolution ambiguity:** Two things happened around the same time — AT&T may have fixed the peering session, and USG DNS was switched from `1.1.1.1` to `8.8.8.8`. Since `1.1.1.1` is Cloudflare-hosted and was also affected, the DNS switch may have masked the issue rather than the peering actually being fixed.
**Outcome:** USG DNS permanently switched from `1.1.1.1` to `8.8.8.8` regardless.

---

## Environment

- **ISP:** AT&T Fiber, AS7018
- **Public IP:** redacted (southeastern US AT&T)
- **AT&T gateway (BGW):** on a private subnet — this is the fiber modem/ONT router
- **USG (UniFi Security Gateway):** sits behind the BGW, doing double-NAT
- **Client LAN:** behind USG, or directly on BGW subnet for diagnostics

### Topology

```
Client → USG → AT&T BGW → AT&T backbone → Internet
```

Note: AT&T BGW is NOT in IP passthrough mode, so USG gets a private WAN IP (double-NAT).
Not the cause of the Cloudflare issue, but worth fixing eventually.

---

## Symptoms

Users experience timeouts and very slow page loads on:
- Canva (canva.com and CDN subdomains)
- Notion (stillinfinite.notion.site)
- Dropbox
- Claude.ai

---

## Diagnosis: AT&T ↔ Cloudflare Peering Issue

### Key Finding

**All affected content is hosted on Cloudflare (AS13335).** Non-Cloudflare CDNs work fine.

| Host | CDN | Status |
|---|---|---|
| `cfl.dropboxstatic.com` | Cloudflare `104.16.x.x` | BROKEN — 84% of requests never complete |
| `chunk-composing.canva.com` | Cloudflare `104.16.x.x` | BROKEN — 3–7s TCP connect |
| `static.canva.com` | Cloudflare `104.16.x.x` | BROKEN — TLS stalls 3s+ |
| `claude.ai` | Cloudflare | BROKEN — challenge page hangs |
| `fjord.dropboxstatic.com` | AWS CloudFront `3.161.x.x` | WORKING — 100% complete |
| `dropbox.com` | Dropbox own infra | WORKING — 7ms connect |
| `stillinfinite.notion.site` | Fastly `208.103.x.x` | Partial — initial page loads, JS assets hang |

### The Smoking Gun (Dropbox A/B)

Dropbox uses two CDNs for static assets:
- `cfl.dropboxstatic.com` → Cloudflare → **84% requests pending**
- `fjord.dropboxstatic.com` → CloudFront → **100% complete**

Same company, same app, same domain suffix. Only variable is the CDN.

### Traceroute Path to Cloudflare

```
1   <AT&T BGW>          ~1ms    (AT&T BGW / local)
2   107.223.196.1       ~2ms    (AT&T first public hop)
3   76.239.207.188      ~2ms    (AT&T backbone)
4   12.242.113.40       ~3ms    (AT&T backbone)
5   [* * *]                     (silent — AT&T peering boundary)
6   108.162.235.x      ~60ms   (Cloudflare backbone — PEERING HOP)
7   104.16.x.x         ~59ms   (Cloudflare destination)
```

The jump from AT&T at ~3ms to Cloudflare at ~60ms indicates AT&T is handing off
Cloudflare traffic at a distant peering point rather than locally in Atlanta.

### MTU

All packet sizes (1200–1472 bytes) pass cleanly. MTU is NOT the issue.

### IPv4 / IPv6

IPv6 is not the issue. IPv4-forced connections show the same behavior.

---

## Round 1 vs Round 2 (Direct to BGW)

Round 2 = machine connected directly to AT&T BGW, USG bypassed.

| Host | Connect R1 | Connect R2 | Change |
|---|---|---|---|
| `cfl.dropboxstatic.com` | 1,064ms | **66ms** | Much better |
| `claude.ai` | 323ms | **62ms** | Much better |
| `www.canva.com` | 63ms | **1,089ms** | Much worse |
| `chunk-composing.canva.com` | 3,062ms | **4,066ms** | Worse |
| `static.canva.com` | 65ms connect | **timeout** | Much worse |

The USG was adding latency for some Cloudflare routes but was incidentally helping others
(possibly due to routing or NAT behavior). Eliminating it is not the solution.

---

## What to Do

### Immediate: mtr from directly-connected machine

Run from a machine directly on the BGW subnet (USG bypassed):

```bash
for ip in 104.16.99.29 3.161.193.123 104.16.102.112 8.8.8.8; do
    sudo mtr --report --report-cycles 30 --no-dns $ip > network/diag-results/mtr/$ip.txt 2>&1 &
done; wait; cat network/diag-results/mtr/*.txt
```

Targets:
- `104.16.99.29`   — Cloudflare (cfl.dropboxstatic.com) — BROKEN
- `3.161.193.123`  — CloudFront (fjord.dropboxstatic.com) — WORKING (control)
- `104.16.102.112` — Cloudflare (static.canva.com) — BROKEN
- `8.8.8.8`        — Google DNS — baseline

### From USG (SSH)

```bash
ssh admin@<USG-IP>
mtr --report --report-cycles 30 104.16.99.29
mtr --report --report-cycles 30 3.161.193.123
```

Running from the USG eliminates all client-side variables.
USG runs EdgeOS (Vyatta-based) — standard Linux networking tools available.

### Check AT&T BGW admin panel

Access the AT&T fiber gateway admin UI (typically at its LAN IP, e.g. http://192.168.8.1):
- Check fiber signal levels (optical Rx/Tx power)
- Check WAN error counters
- Check uptime / connection events

If fiber signal is degraded, that's a physical issue AT&T fixes on-site.

### Report to AT&T

Key evidence for AT&T NOC ticket:
- All Cloudflare IPs (AS13335) have 1–7 second TCP connect times from this connection
- Non-Cloudflare CDNs on the same network connect in <100ms
- Traceroute shows AT&T → Cloudflare peering via `108.162.235.x` with 60ms RTT
- mtr shows X% packet loss at AT&T peering boundary (fill in after running mtr)
- AS7018 (AT&T) → AS13335 (Cloudflare) peering session needs investigation

### IP Passthrough (optional, not urgent)

Configure AT&T BGW to put USG in DMZ / IP passthrough mode so USG gets the real
public IP. Eliminates double-NAT. Not the cause of the Cloudflare issue but cleaner.
Common AT&T setup with UniFi: search "AT&T BGW IP passthrough UniFi".

---

## mtr Results (captured 2026-03-15, directly connected to AT&T BGW)

### Cloudflare — cfl.dropboxstatic.com (104.16.99.29)
```
1  <AT&T BGW>        80.0%  ← ICMP rate-limiting on BGW, not real loss
2  107.223.196.1      0.0%
3  76.239.207.188     0.0%
4  12.242.113.40      0.0%
5  ???              100.0%  ← silent hop, normal
6  108.162.235.59   46.7%  ← AT&T → Cloudflare PEERING HOP, 60-86ms
7  104.16.99.29     46.7%  ← Cloudflare destination
```

### Cloudflare — static.canva.com (104.16.102.112)
```
6  108.162.235.87   46.7%  ← same peering subnet, same loss
7  104.16.102.112   46.7%
```

### CloudFront — fjord.dropboxstatic.com (3.161.193.123) — CONTROL
```
2-11  ???   (intermediate hops block ICMP — normal AWS behavior)
12    3.161.193.123   0.0%  ← destination reached with ZERO loss
```

### Google — 8.8.8.8 — BASELINE
```
9  8.8.8.8   0.0%  ← destination reached with ZERO loss
```

### Conclusion

**~47% packet loss at `108.162.235.x` (AT&T → Cloudflare peering, Atlanta)**

- AT&T backbone (hops 2-4): 0% loss
- CloudFront destination: 0% loss
- Google destination: 0% loss
- Cloudflare destination: **46.7% loss**, originating at peering hop `108.162.235.x`

This is the evidence for AT&T: AS7018 → AS13335 peering session is dropping ~47% of packets.

---

## Open Questions

- [ ] AT&T BGW admin: what do fiber signal levels show?
- [ ] Does the issue occur 24/7 or at specific times of day? (congestion vs. peering config)
- [x] ~~mtr results: what % packet loss at which hop?~~ → 46.7% at 108.162.235.x (Cloudflare peering)
- [ ] Does a VPN (bypasses AT&T peering) fix the Cloudflare sites? (quick confirmation test)
