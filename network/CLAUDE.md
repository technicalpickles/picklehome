# CLAUDE.md — network/

Network diagnostic tooling for investigating ISP/CDN connectivity issues.

## Scripts

### `bgw.py` — AT&T BGW gateway diagnostics

Queries the AT&T BGW router admin interface (`http://192.168.8.254`) directly.
Uses `requests` for status pages, `playwright` for diag commands (which stream output progressively).

```bash
just bgw fiber               # fiber signal / optical metrics
just bgw broadband           # WAN connection status
just bgw trace <ip>          # traceroute from BGW WAN
just bgw ping <ip>           # ping from BGW WAN
just bgw nslookup <host>
```

The traceroute/ping/nslookup commands run from the BGW's WAN interface, bypassing the USG entirely — useful for isolating whether issues are in the LAN/USG or in the AT&T network.

### `profile.py` — Playwright network profiler

Visits a URL with a headless browser and reports per-hostname request stats (latency, errors, pending requests).

```bash
just network-profile https://example.com
just network-profile https://example.com --slow-ms 1000 --timeout 15
```

### `isp_status.py` — ISP and CDN status checker

Checks Cloudflare's status API (overall + nearby colos + active incidents), the
Cloudflare trace endpoint (which colo your traffic routes through), Cloudflare Radar
BGP hijack/leak events and NetFlows traffic trend for AT&T (AS7018), RIPE BGP state
(your IP's current ASN + Cloudflare/Google prefix health), and optionally AT&T outage
status by ZIP code (via Playwright). Prints manual-check URLs for BGP tools.

The RIPE section uses `stat.ripe.net` (no token needed) and reports dynamically — your
IP's ASN (confirms AT&T / flags if different), and prefix visibility + origin ASN for
key destinations. Useful for detecting hijacks or unexpected origin changes.

Requires `CLOUDFLARE_RADAR_API_TOKEN` in `.env` (Cloudflare dashboard → My Profile →
API Tokens → create token with `Account > Radar: Read` scope; free tier is fine).

```bash
just network-status              # Cloudflare + Radar
just network-status 30318        # + AT&T check by ZIP
```

**Traffic trend note:** The NetFlows sparkline uses `[?]` rather than `[!]` for low recent
traffic — the 24h normalization means overnight lows will always look like drops. The
threshold logic needs further calibration before it's reliable as an alert.

### `unifi-wifi.py` — UniFi WiFi diagnostics (AP perspective)

Queries the CloudKey legacy API for per-AP radio stats and per-client WiFi metrics.
Requires `UNIFI_API_KEY` in `.env`.

```bash
# Quick health check
just unifi-wifi checkup                      # composite: AP retries + RF neighbors + watched device roaming
just unifi-wifi checkup --sessions 3         # with more roaming history per device

# Diagnostics (read-only)
just unifi-wifi aps                          # all APs: channel, utilization, client count, retries
just unifi-wifi aps --sort retries           # sort APs by worst retry rate
just unifi-wifi aps --sort utilization       # sort APs by channel utilization
just unifi-wifi clients                      # all WiFi clients: AP, signal, SNR, rates, satisfaction
just unifi-wifi client <hostname|ip>         # detail for one client (partial hostname OK)
just unifi-wifi roaming                      # roaming history for all watched devices (from .env)
just unifi-wifi roaming <hostname|ip>        # roaming history for a specific device
just unifi-wifi roaming <hostname|ip> --sessions 3  # show last N sessions
just unifi-wifi rfscan                       # neighboring APs from passive RF scan — channel congestion
just unifi-wifi rfscan --summary             # channel congestion only, skip full neighbor list
just unifi-wifi rfscan --fresh 60            # only neighbors seen in last N minutes
just unifi-wifi rfscan --own                 # include own APs in the scan results
just unifi-wifi config                       # SSID roaming/power-save settings + per-AP transmit power

# Actions (mutating — will prompt for confirmation)
just unifi-wifi set-channel <ap> <band> <ch> # change radio channel (e.g. "tracy" 5 36)
just unifi-wifi set-power <ap> <band> <mode> # set tx power mode (auto/low/medium/high/custom)
just unifi-wifi set-power all 2.4 medium     # set all APs at once
just unifi-wifi locate <ap-name>             # flash AP LED to physically identify it (Enter to stop)
just unifi-wifi locate <ap-name> --duration 30  # auto-stop after 30s
```

**Common diagnostic workflows:**
- "Quick network health check?" → `checkup` (AP retries + RF neighbors + watched device roaming in one command)
- "Nosy neighbors / interference?" → `rfscan --fresh 60` for neighbor count per channel, `aps` for RX utilization
- "Phone roaming OK?" → `roaming` (no args = all watched devices), or `roaming <hostname> --sessions 5` for one
- "Current RF config?" → `config` for SSID settings + per-AP tx power, `aps` for live channel/utilization

Key fields: `signal` (dBm from AP), `noise`, `SNR`, `tx_rate`, `wifi_tx_retries_percentage`,
`satisfaction` (UniFi composite score 0–100), `cu_total` (channel utilization %).

Note: UniFi's `rssi` field is a normalized 0–95 scale, NOT dBm. Use `signal` for real diagnostics.

**Roaming history** comes from `/stat/session` → `roaming_sessions` array. Each segment has
`start_time`, `duration`, `ap_mac`, and `satisfaction`. AP MACs are resolved to names via
`/stat/device`. Works for offline clients too (falls back to `/stat/alluser`). Satisfaction
scores < 90 are flagged with `←`. Use this to confirm which AP a client was on before
roaming, diagnose sticky-client behavior, or correlate a complaint with a specific transition.

### `wifi-diag.py` — Client-side WiFi and connectivity diagnostic

Run on any Mac in the home network to diagnose local WiFi issues. Collects:
- WiFi association: SSID, BSSID (which physical AP), RSSI, noise, SNR, channel, link rate
- Nearby visible APs (roaming candidates, relative signal strengths)
- IP / gateway / DNS configuration
- Latency to LAN gateway (USG) and internet (8.8.8.8)
- Traceroute to 8.8.8.8 with known-hop annotations (USG, BGW, etc.)
- Internet download speed via Cloudflare (~25 MB)

The BSSID field identifies exactly which physical AP the device is on — cross-reference
with UniFi UI → Clients → `<device>` → AP, or the AP's radio MAC in UniFi → Devices.

```bash
just wifi-diag
just wifi-diag --no-trace --no-speed   # quick run (skip traceroute + speed test)
```

No `.env` or API keys required — runs standalone on any Mac with `uv` installed.

### `unifi-api.py` — Raw UniFi CloudKey API wrapper

Thin wrapper around the CloudKey legacy API that handles auth and TLS, letting you
explore endpoints without manually managing headers in curl. Requires `UNIFI_API_KEY` in `.env`.

```bash
just unifi-api get /stat/device
just unifi-api get /stat/sta
just unifi-api put /rest/device/<id> '{"radio_table": [...]}'
```

Paths are relative to `/proxy/network/api/s/default` — omit that prefix.

### `diag.sh` — curl-based per-host diagnostics

Shell script for curl-based TCP connect timing to a list of hosts. No dependencies.

### `mtr-capture.sh` — mtr batch capture

Runs mtr to multiple targets and saves results to `network-diag-results/mtr/`.

## Reference

See `TOPOLOGY.md` for network layout, key IPs, DNS configuration, and issue history.
See `CHANGELOG.md` for configuration changes, rationale, and pending follow-up checks.
Past investigations are in `investigations/`.

## Deep Reference Docs (`network/docs/`)

Read these when working on a specific tool — do not load by default.

| File | When to read |
|---|---|
| `docs/bgw-reference.md` | Working on `bgw.py` or BGW WiFi config — CGI endpoints, auth model, `home.ha` scraping |
| `docs/wifi-ios-unifi.md` | Diagnosing iPhone WiFi issues — iOS PSM/roaming behavior, UniFi settings that affect it, diagnostic workflow, current network config snapshot |
| `docs/outdoor-wifi-research.md` | Outdoor backyard coverage — hardware comparison (U7LR vs U7 Outdoor), mounting orientation, TX power/channel starting config, decision gate criteria, measurement protocol |
| `docs/wifi-survey-tools.md` | WiFi survey and floor plan tools — WiFiMan (free, LiDAR heatmap), NetSpot (paid, multi-metric), Design Center (free, simulated), InnerSpace (live coverage); recommended workflow and comparison |
| `docs/24ghz-power-tuning.md` | 2.4 GHz TX power research — near-far problem, AP model antenna characteristics, why medium beats max in multi-floor homes, before/after data |
| `docs/cloud-gateway-upgrade-research.md` | Replacing CloudKey Gen2 + USG with a Cloud Gateway — model comparison (UDM Pro/SE/Pro Max), migration process, features unlocked, WiFi 7 AP lineup |
