# CLAUDE.md — network/

Network diagnostic tooling for investigating ISP/CDN connectivity issues.

## Scripts

### `bgw.py` — AT&T BGW gateway diagnostics

Queries the AT&T BGW router admin interface (`http://192.168.8.254`) directly.
Uses `requests` for status pages, `playwright` for diag commands (which stream output progressively).

```bash
uv run --with requests --with playwright network/bgw.py fiber       # fiber signal / optical metrics
uv run --with requests --with playwright network/bgw.py broadband   # WAN connection status
uv run --with requests --with playwright network/bgw.py trace <ip>  # traceroute from BGW WAN
uv run --with requests --with playwright network/bgw.py ping <ip>   # ping from BGW WAN
uv run --with requests --with playwright network/bgw.py nslookup <host>
```

The traceroute/ping/nslookup commands run from the BGW's WAN interface, bypassing the USG entirely — useful for isolating whether issues are in the LAN/USG or in the AT&T network.

### `profile.py` — Playwright network profiler

Visits a URL with a headless browser and reports per-hostname request stats (latency, errors, pending requests).

```bash
uv run --with playwright network/profile.py https://example.com
uv run --with playwright network/profile.py https://example.com --slow-ms 1000 --timeout 15
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
just unifi-wifi aps                    # all APs: channel, utilization, client count, retries
just unifi-wifi clients                # all WiFi clients: AP, signal, SNR, rates, satisfaction
just unifi-wifi client <hostname|ip>   # detail for one client (partial hostname OK)
```

Key fields: `signal` (dBm from AP), `noise`, `SNR`, `tx_rate`, `wifi_tx_retries_percentage`,
`satisfaction` (UniFi composite score 0–100), `cu_total` (channel utilization %).

Note: UniFi's `rssi` field is a normalized 0–95 scale, NOT dBm. Use `signal` for real diagnostics.

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
Past investigations are in `investigations/`.

## Deep Reference Docs (`network/docs/`)

Read these when working on a specific tool — do not load by default.

| File | When to read |
|---|---|
| `docs/bgw-reference.md` | Working on `bgw.py` or BGW WiFi config — CGI endpoints, auth model, `home.ha` scraping |
