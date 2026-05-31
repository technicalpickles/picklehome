# network/

Network diagnostic tooling for investigating ISP/CDN connectivity issues.

See `TOPOLOGY.md` for network layout, key IPs, channel plan, DNS config, and issue history.

## Running scripts

The preferred way to run scripts is via `just` (see `just --list`). Scripts can also be run
directly with `uv run --with <deps>` — useful when iterating on a script or running it on
a machine that doesn't have the full repo checked out.

Each script's docstring documents its exact `uv run --with ...` invocation.

### `just` tasks

| Script | `just` task | What it does |
|---|---|---|
| `isp_status.py` | `just network-status [zip]` | ISP + CDN/BGP health check |
| `wifi-diag.py` | `just wifi-diag [args]` | Client-side WiFi + connectivity diagnostic |
| `unifi_cli.py` | `just unifi <subcommand>` | UniFi CloudKey diagnostics (see `CLAUDE.md`) |
| `bgw.py` | `just bgw <subcommand>` | AT&T BGW gateway diagnostics (fiber, broadband, trace, ping, nslookup) |
| `snapshot.py` | `just network-snapshot [args]` | Full network snapshot (BGW + USG + DNS + peering trace) |
| `resolve.py` | `just network-resolve <host> ...` | DNS comparison across resolvers |
| `profile.py` | `just network-profile <url> [args]` | Per-hostname latency/errors for a URL (spot slow CDNs) |

### Running directly (without `just`)

Every script also runs standalone via `uv run --with <deps>` — useful when iterating on a
script or running it on a machine without the full repo checked out. Each script's docstring
documents its exact invocation. Examples:

```bash
uv run --with requests --with playwright network/bgw.py fiber
uv run --with requests --with python-dotenv --with paramiko --with dnspython --with playwright network/snapshot.py --no-trace
uv run --with dnspython network/resolve.py <hostname> [<hostname> ...]
uv run --with playwright network/profile.py <url> --slow-ms 1000 --timeout 15
```

## Secrets

Scripts that talk to the CloudKey or Cloudflare require `.env` (generated via `just dotenv`):

- `UNIFI_API_KEY` — UniFi CloudKey API key (Network → Integrations)
- `CLOUDFLARE_RADAR_API_TOKEN` — Cloudflare dashboard → My Profile → API Tokens → `Account > Radar: Read`
- `UNIFI_ADMIN_USERNAME` / `UNIFI_ADMIN_PASSWORD` — only needed for `just unifi usg dns` (SSH)
