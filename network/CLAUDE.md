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
Cloudflare trace endpoint (which colo your traffic routes through), and optionally
AT&T outage status by ZIP code (via Playwright). Prints manual-check URLs for BGP tools.

```bash
uv run --with requests network/isp_status.py                          # Cloudflare only
uv run --with requests --with playwright network/isp_status.py --zip 30318  # + AT&T check
```

### `diag.sh` — curl-based per-host diagnostics

Shell script for curl-based TCP connect timing to a list of hosts. No dependencies.

### `mtr-capture.sh` — mtr batch capture

Runs mtr to multiple targets and saves results to `network-diag-results/mtr/`.

## Reference

See `TOPOLOGY.md` for network layout, key IPs, DNS configuration, and issue history.
Past investigations are in `investigations/`.
