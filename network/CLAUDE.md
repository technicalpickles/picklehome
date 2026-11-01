# CLAUDE.md: network/

Network diagnostic tooling for investigating ISP/CDN connectivity issues.

## When a site or service is slow or broken

Diagnose **top-down**; stop at the layer that's actually failing. Don't open with `mtr`/`curl` just because a past investigation did.

1. **Browser view first** — `just network-profile <url>` (run OUTSIDE the sandbox; uses a headless browser). Reports per-hostname latency, errors, and pending requests as a real browser sees them. A 403/401 plus hung `blob:` challenge requests is Cloudflare bot detection, not a network fault. Slow or pending *real* requests = keep going down.
2. **TLS + TCP timing** — `curl -o /dev/null -w 'tcp=%{time_connect} tls=%{time_appconnect} total=%{time_total}\n' https://<host>` (run outside the sandbox; in-sandbox curl routes through the proxy and the timing is meaningless). Healthy TLS handshake is <100ms; seconds means a path problem.
3. **Packet loss** — `ping -c 15 <ip>` to the destination IP plus a control (`8.8.8.8`). Loss to the target but not the control isolates the path.
4. **Find the hop** — `sudo mtr --report --report-cycles 30 <ip>`, or `just bgw trace <ip>` / `just bgw ping <ip>` to test from the AT&T WAN side with the USG bypassed (also needs the sandbox off). Identifies where loss starts.
5. **Peering / CDN health** — `just network-status` for Cloudflare status + AT&T↔Cloudflare (AS7018↔AS13335) Radar/BGP signals.

**CDN fate-sharing:** Cloudflare-hosted sites (Canva, Claude.ai, Notion, Dropbox CDN, `1.1.1.1`) share a path. If one is slow on this connection, check whether a *non*-Cloudflare CDN is fine to isolate an AT&T↔Cloudflare peering problem, the exact failure mode in `investigations/cloudflare-peering-2026-03.md` (~47% loss at the peering hop, March 2026).

## Scripts

`network/README.md` maps each script to its `just` recipe, `just --list` shows the recipes, and each script's `--help` lists its subcommands and flags. What those don't say:

- `bgw.py` and `profile.py` need the sandbox off (`bgw.py`'s diag commands drive a headless browser).
- `isp_status.py` needs `CLOUDFLARE_RADAR_API_TOKEN` in `.env` (Cloudflare dashboard, `Account > Radar: Read`; free tier is fine).
- `unifi_cli.py` needs `UNIFI_API_KEY`. The SSH-backed commands (`usg dns`, `usg resolve`) also need `UNIFI_ADMIN_USERNAME` and `UNIFI_ADMIN_PASSWORD`. `wifi set-channel` and `wifi set-power` mutate and prompt for confirmation.
- `unifi_cli.py api get|put` paths are relative to `/proxy/network/api/s/default`; omit that prefix.
- UniFi's `rssi` field is a normalized 0–95 scale, NOT dBm. Use `signal` for real diagnostics.

Tailscale: `just tailscale` wraps `tailscale status`, and `just tailscale-audit` is the read-only key-expiry check (its docstring has the rules). `TOPOLOGY.md` has the device table.

## Reference

See `TOPOLOGY.md` for network layout, key IPs, DNS configuration, and issue history.
See `CHANGELOG.md` for configuration changes, rationale, and pending follow-up checks.
Past investigations are in `investigations/`.

## Deep Reference Docs (`network/docs/`)

Read these when working on a specific tool; do not load by default.

| File | When to read |
|---|---|
| `docs/bgw-reference.md` | Working on `bgw.py` or BGW WiFi config: CGI endpoints, auth model, `home.ha` scraping |
| `docs/wifi-ios-unifi.md` | Diagnosing iPhone WiFi issues: iOS PSM/roaming behavior, UniFi settings that affect it, diagnostic workflow, current network config snapshot |
| `docs/outdoor-wifi-research.md` | Outdoor backyard coverage: hardware comparison (U7LR vs U7 Outdoor), mounting orientation, TX power/channel starting config, decision gate criteria, measurement protocol |
| `docs/wifi-survey-tools.md` | WiFi survey and floor plan tools: WiFiMan (free, LiDAR heatmap), NetSpot (paid, multi-metric), Design Center (free, simulated), InnerSpace (live coverage); recommended workflow and comparison |
| `docs/24ghz-power-tuning.md` | 2.4 GHz TX power research: near-far problem, AP model antenna characteristics, why medium beats max in multi-floor homes, before/after data |
| `docs/cloud-gateway-upgrade-research.md` | Replacing CloudKey Gen2 + USG with a Cloud Gateway: model comparison (UDM Pro/SE/Pro Max), migration process, features unlocked, WiFi 7 AP lineup |
| `docs/floorplan-capture-checklist.md` | Annotating the MagicPlan floorplan with network-relevant info: what to capture (AP positions, room adjacency, wall/floor materials, measured distances) so RF reasoning stops relying on assumptions about range |
| `docs/floorplan-markup-legend.md` | How to mark up the exported floorplan: symbols/colors for AP position, wall material, floor penetrations, room IDs, and the floor-alignment method. Room IDs themselves are canonical in `TOPOLOGY.md`'s Room Registry |
| `docs/floorplan-geojson-schema.md` | Machine-readable counterpart to the visual markup: GeoJSON feature types (room, wall, opening, ap, rf_hostile) and coordinate convention for `network/floorplan/*.geojson`, modeled on IMDF |
