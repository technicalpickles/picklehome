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

### `diag.sh` — curl-based per-host diagnostics

Shell script for curl-based TCP connect timing to a list of hosts. No dependencies.

### `mtr-capture.sh` — mtr batch capture

Runs mtr to multiple targets and saves results to `network-diag-results/mtr/`.

## Known Issue: AT&T → Cloudflare Peering

~47% packet loss at `108.162.235.x` (AT&T AS7018 → Cloudflare AS13335 peering, Atlanta).
All Cloudflare-hosted sites are affected; non-Cloudflare CDNs work normally.
See `notes.md` for full investigation details and evidence.

Key test IPs:
- `104.16.99.29` — Cloudflare (cfl.dropboxstatic.com) — **affected**
- `3.161.193.123` — CloudFront (fjord.dropboxstatic.com) — working (control)
- `8.8.8.8` — Google DNS — baseline
