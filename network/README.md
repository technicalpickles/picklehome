# network/

Network diagnostic tooling for investigating ISP/CDN connectivity issues.

See `TOPOLOGY.md` for network layout, key IPs, channel plan, DNS config, and issue history.

## Running scripts

The preferred way to run scripts is via `just` (see `just --list`). Scripts can also be run
directly with `uv run --with <deps>` — useful when iterating on a script or running it on
a machine that doesn't have the full repo checked out.

Each script's docstring documents its exact `uv run --with ...` invocation.

### Scripts with `just` tasks

| Script | `just` task |
|---|---|
| `isp_status.py` | `just network-status [zip]` |
| `wifi-diag.py` | `just wifi-diag [args]` |
| `unifi_cli.py` | `just unifi <subcommand>` |

### Scripts without `just` tasks (run directly)

```bash
# BGW gateway diagnostics (fiber signal, WAN status, traceroute from BGW WAN)
uv run --with requests --with playwright network/bgw.py fiber
uv run --with requests --with playwright network/bgw.py broadband
uv run --with requests --with playwright network/bgw.py trace <ip>
uv run --with requests --with playwright network/bgw.py ping <ip>

# Full network snapshot (BGW + USG + DNS + peering trace)
uv run --with requests --with python-dotenv --with paramiko --with dnspython --with playwright network/snapshot.py
uv run --with requests --with python-dotenv --with paramiko --with dnspython --with playwright network/snapshot.py --no-trace

# UniFi diagnostics (use `just unifi <subcommand>` instead when possible)
uv run --with requests --with python-dotenv network/unifi_cli.py devices
uv run --with requests --with python-dotenv network/unifi_cli.py usg wan-detail
uv run --with requests --with python-dotenv --with paramiko network/unifi_cli.py usg dns

# DNS comparison across resolvers
uv run --with dnspython network/resolve.py <hostname> [<hostname> ...]

# Network profiler: per-hostname latency/errors for a URL (useful for spotting slow CDNs)
uv run --with playwright network/profile.py <url>
uv run --with playwright network/profile.py <url> --slow-ms 1000 --timeout 15
```

## Secrets

Scripts that talk to the CloudKey or Cloudflare require `.env` (generated via `just dotenv`):

- `UNIFI_API_KEY` — UniFi CloudKey API key (Network → Integrations)
- `CLOUDFLARE_RADAR_API_TOKEN` — Cloudflare dashboard → My Profile → API Tokens → `Account > Radar: Read`
- `UNIFI_ADMIN_USERNAME` / `UNIFI_ADMIN_PASSWORD` — only needed for `just unifi usg dns` (SSH)
