# UniFi CLI Reorganization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reorganize the three UniFi CLI scripts (`unifi-wifi.py`, `usg.py`, `unifi-api.py`) into a single `unifi` entrypoint with `wifi` and `usg` subcommand groups, plus top-level commands for general client/device management.

**Architecture:** Create `network/unifi_cli.py` as the single entrypoint with nested argparse subparsers. Move command functions into focused modules under `network/unifi/` — `wifi.py` for RF/AP commands, `usg.py` for gateway commands, and the shared helpers + top-level commands stay in `unifi_cli.py` itself. The existing `network/unifi.py` (auth/session) becomes `network/unifi/__init__.py`. The old `network/unifi-wifi.py`, `network/usg.py`, and `network/unifi-api.py` files are deleted after migration.

**Tech Stack:** Python 3, argparse (nested subparsers), requests, paramiko (SSH commands)

**Target CLI structure:**
```
unifi clients                          # all WiFi clients (was: unifi-wifi clients)
unifi client <query>                   # detail for one client (was: unifi-wifi client)
unifi rename <query> "Name"            # set alias (was: unifi-wifi rename)
unifi devices                          # adopted infrastructure (was: usg devices)
unifi topology [--format ...]          # network tree (was: usg topology)
unifi checkup [--sessions N]           # composite health (was: unifi-wifi checkup)
unifi api get|put <path> [body]        # raw API wrapper (was: unifi-api get|put)

unifi wifi aps [--sort ...]            # AP radio stats
unifi wifi config                      # SSID/radio config
unifi wifi rfscan [--own] [--fresh N]  # RF neighbor scan
unifi wifi roaming [device]            # AP transition history
unifi wifi set-power <ap> <band> ...   # TX power
unifi wifi set-channel <ap> <band> ... # channel change
unifi wifi locate <ap>                 # flash AP LED

unifi usg stats                        # CPU/mem/uplink
unifi usg wan                          # WAN interface definitions
unifi usg wan-detail                   # rich WAN details
unifi usg dns                          # dnsmasq config (SSH)
unifi usg resolve <host>               # DNS comparison (SSH)
```

---

### Task 1: Convert `network/unifi.py` to `network/unifi/__init__.py`

The shared auth module needs to become a package so we can add `wifi.py` and `usg.py` submodules.

**Files:**
- Delete: `network/unifi.py`
- Create: `network/unifi/__init__.py` (same content)

**Step 1: Create the package directory and move the file**

```bash
mkdir -p network/unifi_pkg
cp network/unifi.py network/unifi_pkg/__init__.py
```

We can't just `mkdir network/unifi` because `network/unifi.py` exists at that path. We need to remove the file first, then create the directory.

```bash
git rm network/unifi.py
mkdir -p network/unifi
mv network/unifi_pkg/__init__.py network/unifi/__init__.py
rmdir network/unifi_pkg
```

**Step 2: Verify imports still work**

Run: `uv run python -c "from network.unifi import LEGACY, session; print('OK')"`
Expected: `OK`

**Step 3: Verify existing scripts still work**

Run: `uv run network/unifi-wifi.py clients 2>&1 | head -5`
Expected: Normal client list output (imports from `network.unifi` resolve to package `__init__.py`)

Run: `uv run network/usg.py devices 2>&1 | head -5`
Expected: Normal device list output

**Step 4: Commit**

```bash
git add network/unifi/__init__.py
git commit -m "refactor(network): convert unifi module to package for submodules"
```

---

### Task 2: Create `network/unifi/wifi.py` — move WiFi-specific commands

Move the RF/AP-specific command functions out of `unifi-wifi.py` into the new submodule.

**Files:**
- Create: `network/unifi/wifi.py`
- Reference: `network/unifi-wifi.py` (source of functions to move)

**Step 1: Create `network/unifi/wifi.py`**

Move these functions from `network/unifi-wifi.py` into `network/unifi/wifi.py`:
- `cmd_aps(s, sort_by="name")`
- `cmd_config(s)`
- `cmd_rfscan(s, include_own=False, fresh_minutes=None, summary_only=False)`
- `cmd_roaming(s, query, num_sessions=1)`
- `cmd_set_channel(s, ap_query, band, channel, yes=False)`
- `cmd_set_power(s, ap_query, band, mode, tx_power=None, yes=False)`
- `cmd_locate(s, ap_query, duration=None)`

Also move these helpers that are only used by wifi commands:
- `snr_label(snr)`
- `signal_label(dbm)`
- `retry_label(pct)`
- `band(radio)`
- `kbps_to_mbps(kbps)`
- `fmt_age(ts)` (if it exists, used by rfscan)

The file should import `get` and `section` from the parent — but since those are simple, just copy them or import from the cli module. Cleanest: define `get` and `section` in `network/unifi/__init__.py` as shared utilities, since both wifi and top-level commands need them.

Add to `network/unifi/__init__.py`:

```python
SEP = "─" * 70

def get(s, path):
    """GET from legacy API endpoint and return data array."""
    r = s.get(f"{LEGACY}{path}", timeout=10)
    r.raise_for_status()
    return r.json().get("data", [])

def section(title):
    print(f"\n{title}")
    print(SEP)
```

Then `network/unifi/wifi.py` starts with:

```python
"""UniFi WiFi commands — RF/AP-specific diagnostics and configuration."""

from datetime import datetime, timezone

from network.unifi import LEGACY, get, section
```

Copy all the WiFi command functions and their helpers verbatim from `unifi-wifi.py`.

**Step 2: Verify the module imports**

Run: `uv run python -c "from network.unifi.wifi import cmd_aps; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add network/unifi/__init__.py network/unifi/wifi.py
git commit -m "refactor(network): extract WiFi commands to unifi/wifi.py"
```

---

### Task 3: Create `network/unifi/usg.py` — move gateway-specific commands

Move gateway-specific commands from the old `network/usg.py` into `network/unifi/usg.py`.

**Files:**
- Create: `network/unifi/usg.py`
- Reference: `network/usg.py` (source of functions to move)

**Step 1: Create `network/unifi/usg.py`**

Move these functions:
- `cmd_stats(s)`
- `cmd_wan(s)`
- `cmd_wan_detail(s)`
- `cmd_dns()`
- `cmd_resolve(host)`
- `ssh_run(commands)`
- `get_site_id(s)` (used by stats and wan)

Also move the `get` helper that uses `BASE` (not `LEGACY`):

```python
from network.unifi import BASE, LEGACY, session

def get(s, path, **kwargs):
    """GET from new integration API."""
    r = s.get(f"{BASE}{path}", timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()

def get_legacy(s, path, **kwargs):
    """GET from legacy API (returns full response JSON, not just data array)."""
    r = s.get(f"{LEGACY}{path}", timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()
```

Note: `usg.py` has its own `get()` that uses `BASE` (not `LEGACY`) and returns the full JSON (not `.get("data", [])`). This is different from the wifi `get()`. Keep them separate.

**Step 2: Verify the module imports**

Run: `uv run python -c "from network.unifi.usg import cmd_stats; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add network/unifi/usg.py
git commit -m "refactor(network): extract USG commands to unifi/usg.py"
```

---

### Task 4: Move top-level commands (devices, topology) into `network/unifi/` package

`devices` and `topology` are general infrastructure commands, not USG-specific. They should be importable from the package for the top-level CLI.

**Files:**
- Create: `network/unifi/devices.py`
- Reference: `network/usg.py` (source — `cmd_devices`, `cmd_topology` + topology renderers)

**Step 1: Create `network/unifi/devices.py`**

Move these functions from `network/usg.py`:
- `cmd_devices(s)`
- `cmd_topology(s, fmt="text")`
- `_topology_text(...)`
- `_topology_mermaid(...)`
- `_topology_dot(...)`

These use both `BASE` (via `get_site_id`) and `LEGACY` (via `get_legacy` for topology). Import what's needed:

```python
"""UniFi device inventory and topology commands."""

from network.unifi import LEGACY, get, section
from network.unifi.usg import get as get_base, get_site_id, get_legacy
```

Actually, `cmd_devices` uses the new API (`BASE`), so it needs `get_site_id` + the base `get`. And `cmd_topology` uses the legacy API. Rather than tangled cross-imports, just define the helpers locally or import the raw constants.

Simpler approach: keep `cmd_devices` and `cmd_topology` directly in the top-level CLI file (`unifi_cli.py`) since they're top-level commands. No new file needed. They can import what they need from `network.unifi.usg` for the API helpers.

**Revised approach:** Don't create `devices.py`. Instead, in Task 5, the top-level `unifi_cli.py` will import `cmd_devices` and `cmd_topology` directly from `network.usg` initially, then inline them after the old file is removed.

Actually the cleanest: put `cmd_devices` and `cmd_topology` (with all the topology renderers) in `network/unifi/__init__.py` alongside `get`, `section`, etc. They're general-purpose UniFi commands that don't belong to wifi or usg.

**Step 1: Add to `network/unifi/__init__.py`**

After the existing `get()` and `section()` functions, add:
- `cmd_devices(s)` — copied from `network/usg.py`, using the BASE API
- `cmd_topology(s, fmt="text")` — copied from `network/usg.py`, using LEGACY API
- All `_topology_*` helper functions

These need both the BASE and LEGACY API helpers. Add `get_base` and `get_legacy` to `__init__.py`:

```python
def get_base(s, path, **kwargs):
    """GET from new integration API (returns full JSON)."""
    r = s.get(f"{BASE}{path}", timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()

def get_site_id(s):
    data = get_base(s, "/sites")
    sites = data.get("data", [])
    if not sites:
        import sys
        sys.exit("No sites found")
    site = sites[0]
    return site["id"], site.get("name", site["id"])
```

Then `cmd_devices` and `cmd_topology` + renderers.

**Step 2: Verify**

Run: `uv run python -c "from network.unifi import cmd_devices, cmd_topology; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add network/unifi/__init__.py
git commit -m "refactor(network): move devices and topology to unifi package"
```

---

### Task 5: Create `network/unifi_cli.py` — the unified entrypoint

Build the new CLI with nested subparsers. Top-level commands live here; wifi and usg commands are imported from their modules.

**Files:**
- Create: `network/unifi_cli.py`

**Step 1: Create `network/unifi_cli.py`**

```python
#!/usr/bin/env python3
"""
unifi — unified UniFi network management CLI

Usage:
    uv run network/unifi_cli.py clients
    uv run network/unifi_cli.py client <query>
    uv run network/unifi_cli.py rename <query> "Friendly Name"
    uv run network/unifi_cli.py devices
    uv run network/unifi_cli.py topology [--format text|mermaid|dot]
    uv run network/unifi_cli.py checkup [--sessions N]
    uv run network/unifi_cli.py api get|put <path> [body]
    uv run network/unifi_cli.py wifi aps|config|rfscan|roaming|set-power|set-channel|locate
    uv run network/unifi_cli.py usg stats|wan|wan-detail|dns|resolve
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from network.unifi import (
    LEGACY, get, section, session,
    cmd_devices, cmd_topology, get_site_id,
)
from network.unifi.wifi import (
    cmd_aps, cmd_clients, cmd_client, cmd_config,
    cmd_rfscan, cmd_roaming, cmd_set_channel, cmd_set_power,
    cmd_locate,
)
from network.unifi.usg import (
    cmd_stats, cmd_wan, cmd_wan_detail, cmd_dns, cmd_resolve,
)
```

Top-level command functions (`cmd_checkup`, `cmd_rename`, `cmd_api_get`, `cmd_api_put`) are defined in this file.

`cmd_clients` and `cmd_client` move to `wifi.py` since they filter to WiFi clients, but are wired as top-level commands in the CLI. (Or they could move to `__init__.py` if we want them to include wired clients later.)

For now, keep `cmd_clients` and `cmd_client` in `wifi.py` but wire them at the top level. Same for `cmd_roaming` — it's WiFi-flavored but useful enough as a top-level concept.

Wait — re-reading the agreed structure: `clients`, `client`, and `rename` are top-level. `roaming` stays under `wifi`. Let's keep that.

`cmd_checkup` is the composite command. Currently it calls `cmd_aps`, `cmd_rfscan`, and `cmd_roaming`. It should stay in the top-level CLI file since it crosses domains. Import what it needs from wifi.

```python
def watched_devices():
    """Load watched device names from UNIFI_WATCHED_DEVICES env var."""
    import re
    raw = os.environ.get("UNIFI_WATCHED_DEVICES", "")
    return [d.strip() for d in re.split(r"[,\n]", raw) if d.strip()]


def cmd_checkup(s, num_sessions=1):
    """Composite network health check."""
    cmd_aps(s, sort_by="retries")
    cmd_rfscan(s, fresh_minutes=60, summary_only=True)
    devices = watched_devices()
    if devices:
        for device in devices:
            cmd_roaming(s, device, num_sessions=num_sessions)
    else:
        print("\n  (UNIFI_WATCHED_DEVICES not set — skipping roaming section)")


def cmd_rename(s, query, new_name):
    # ... (copied from unifi-wifi.py)


def cmd_api(s, method, path, body=None):
    """Raw API wrapper."""
    url = f"{LEGACY}{path}"
    if method == "get":
        r = s.get(url, timeout=10)
    elif method == "put":
        r = s.put(url, json=body, timeout=10)
    print(json.dumps(r.json(), indent=2))
```

Argparse structure with nested subparsers:

```python
def main():
    parser = argparse.ArgumentParser(
        description="UniFi network management — clients, devices, WiFi, and gateway diagnostics"
    )
    sub = parser.add_subparsers(dest="cmd")

    # ── Top-level commands ──
    sub.add_parser("clients", help="All WiFi clients: AP, signal, SNR, rates, satisfaction")
    p_client = sub.add_parser("client", help="Detail for one client (hostname, IP, or MAC)")
    p_client.add_argument("query", help="Hostname, IP, or MAC (partial hostname OK)")

    p_rename = sub.add_parser("rename", help="Set a friendly alias for a client device")
    p_rename.add_argument("query", help="Hostname, IP, or MAC of the client to rename")
    p_rename.add_argument("name", help="New friendly name (alias) for the client")

    sub.add_parser("devices", help="All adopted UniFi devices with firmware versions")
    p_topo = sub.add_parser("topology", help="Network device tree with uplink ports and radio state")
    p_topo.add_argument("--format", choices=["text", "mermaid", "dot"], default="text")

    p_chk = sub.add_parser("checkup", help="Composite health: AP retries + RF + watched device roaming")
    p_chk.add_argument("--sessions", type=int, default=1, metavar="N")

    # ── API subcommand ──
    p_api = sub.add_parser("api", help="Raw API wrapper for debugging")
    api_sub = p_api.add_subparsers(dest="api_cmd", required=True)
    p_api_get = api_sub.add_parser("get", help="GET an API endpoint")
    p_api_get.add_argument("path", help="Path relative to /api/s/default")
    p_api_put = api_sub.add_parser("put", help="PUT JSON to an API endpoint")
    p_api_put.add_argument("path", help="Path relative to /api/s/default")
    p_api_put.add_argument("body", help="JSON body as a string")

    # ── WiFi subcommand group ──
    p_wifi = sub.add_parser("wifi", help="WiFi AP diagnostics and configuration")
    wifi_sub = p_wifi.add_subparsers(dest="wifi_cmd", required=True)

    p_aps = wifi_sub.add_parser("aps", help="All APs: radio config, channel utilization, retries")
    p_aps.add_argument("--sort", choices=["name", "retries", "utilization"], default="name")

    wifi_sub.add_parser("config", help="SSID roaming/power-save settings and per-AP transmit power")

    p_rfscan = wifi_sub.add_parser("rfscan", help="Neighboring APs — channel congestion")
    p_rfscan.add_argument("--own", action="store_true")
    p_rfscan.add_argument("--fresh", type=int, metavar="MINUTES", default=None)
    p_rfscan.add_argument("--summary", action="store_true")

    p_roam = wifi_sub.add_parser("roaming", help="Roaming history: which APs, when, satisfaction")
    p_roam.add_argument("query", nargs="?", default=None)
    p_roam.add_argument("--sessions", type=int, default=1, metavar="N")

    p_sc = wifi_sub.add_parser("set-channel", help="Set radio channel on an AP")
    p_sc.add_argument("ap", help="AP name (partial match OK)")
    p_sc.add_argument("band", choices=["2.4", "5"])
    p_sc.add_argument("channel", help="Channel number or 'auto'")
    p_sc.add_argument("--yes", action="store_true")

    p_sp = wifi_sub.add_parser("set-power", help="Set transmit power mode")
    p_sp.add_argument("ap", help="AP name or 'all'")
    p_sp.add_argument("band", choices=["2.4", "5"])
    p_sp.add_argument("mode", choices=["auto", "low", "medium", "high", "custom"])
    p_sp.add_argument("--dbm", type=int, default=None)
    p_sp.add_argument("--yes", action="store_true")

    p_loc = wifi_sub.add_parser("locate", help="Flash an AP's LED")
    p_loc.add_argument("ap", help="AP name (partial match OK)")
    p_loc.add_argument("--duration", type=int, default=None, metavar="SECONDS")

    # ── USG subcommand group ──
    p_usg = sub.add_parser("usg", help="Gateway diagnostics")
    usg_sub = p_usg.add_subparsers(dest="usg_cmd", required=True)

    usg_sub.add_parser("stats", help="USG CPU, memory, uplink rates")
    usg_sub.add_parser("wan", help="WAN interface definitions")
    usg_sub.add_parser("wan-detail", help="Rich WAN details: IP, gateway, DNS, port counters")
    usg_sub.add_parser("dns", help="USG dnsmasq config (SSH)")
    p_res = usg_sub.add_parser("resolve", help="DNS resolution comparison (SSH)")
    p_res.add_argument("host", help="Hostname to resolve")

    # ── Dispatch ──
    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        return

    # SSH-only commands (no API session needed)
    if args.cmd == "usg" and args.usg_cmd in ("dns", "resolve"):
        if args.usg_cmd == "dns":
            cmd_dns()
        elif args.usg_cmd == "resolve":
            cmd_resolve(args.host)
        return

    s = session()

    # Top-level commands
    if args.cmd == "clients":
        cmd_clients(s)
    elif args.cmd == "client":
        cmd_client(s, args.query)
    elif args.cmd == "rename":
        cmd_rename(s, args.query, args.name)
    elif args.cmd == "devices":
        cmd_devices(s)
    elif args.cmd == "topology":
        cmd_topology(s, fmt=args.format)
    elif args.cmd == "checkup":
        cmd_checkup(s, num_sessions=args.sessions)

    # API commands
    elif args.cmd == "api":
        if args.api_cmd == "get":
            cmd_api(s, "get", args.path)
        elif args.api_cmd == "put":
            try:
                body = json.loads(args.body)
            except json.JSONDecodeError as e:
                sys.exit(f"Invalid JSON: {e}")
            cmd_api(s, "put", args.path, body)

    # WiFi commands
    elif args.cmd == "wifi":
        if args.wifi_cmd == "aps":
            cmd_aps(s, sort_by=args.sort)
        elif args.wifi_cmd == "config":
            cmd_config(s)
        elif args.wifi_cmd == "rfscan":
            cmd_rfscan(s, include_own=args.own, fresh_minutes=args.fresh, summary_only=args.summary)
        elif args.wifi_cmd == "roaming":
            if args.query:
                cmd_roaming(s, args.query, num_sessions=args.sessions)
            else:
                devices = watched_devices()
                if not devices:
                    print("  No query given and UNIFI_WATCHED_DEVICES not set in .env")
                    print("  Usage: unifi wifi roaming <hostname>")
                    sys.exit(1)
                for device in devices:
                    cmd_roaming(s, device, num_sessions=args.sessions)
        elif args.wifi_cmd == "set-channel":
            ch = args.channel if args.channel == "auto" else int(args.channel)
            cmd_set_channel(s, args.ap, args.band, ch, yes=args.yes)
        elif args.wifi_cmd == "set-power":
            if args.mode == "custom" and args.dbm is None:
                parser.error("--dbm required when mode=custom")
            cmd_set_power(s, args.ap, args.band, args.mode, tx_power=args.dbm, yes=args.yes)
        elif args.wifi_cmd == "locate":
            cmd_locate(s, args.ap, duration=args.duration)

    # USG commands
    elif args.cmd == "usg":
        if args.usg_cmd == "stats":
            cmd_stats(s)
        elif args.usg_cmd == "wan":
            cmd_wan(s)
        elif args.usg_cmd == "wan-detail":
            cmd_wan_detail(s)


if __name__ == "__main__":
    main()
```

**Step 2: Smoke test the new CLI**

Run: `uv run network/unifi_cli.py --help`
Expected: Shows top-level commands + wifi/usg subgroups

Run: `uv run network/unifi_cli.py clients 2>&1 | head -5`
Expected: Client list with friendly names

Run: `uv run network/unifi_cli.py wifi aps 2>&1 | head -5`
Expected: AP radio stats

Run: `uv run network/unifi_cli.py usg stats 2>&1 | head -5`
Expected: USG stats

Run: `uv run network/unifi_cli.py devices 2>&1 | head -5`
Expected: Device inventory

**Step 3: Commit**

```bash
git add network/unifi_cli.py
git commit -m "feat(network): add unified unifi CLI entrypoint with wifi/usg subcommands"
```

---

### Task 6: Update Justfile — replace old tasks with `unifi`

**Files:**
- Modify: `Justfile`

**Step 1: Replace the three old tasks with one `unifi` task**

Remove:
```
usg *ARGS:
    uv run network/usg.py {{ARGS}}

unifi-wifi *ARGS:
    uv run network/unifi-wifi.py {{ARGS}}

unifi-api *ARGS:
    uv run network/unifi-api.py {{ARGS}}
```

Add:
```
# UniFi network management: just unifi clients | wifi aps | usg stats | ...
unifi *ARGS:
    uv run network/unifi_cli.py {{ARGS}}
```

Keep `wifi-diag` as-is — it's a standalone client-side tool, not a CloudKey API tool.

**Step 2: Verify**

Run: `just unifi clients 2>&1 | head -5`
Expected: Client list

Run: `just unifi wifi aps 2>&1 | head -5`
Expected: AP stats

Run: `just unifi usg stats 2>&1 | head -5`
Expected: USG stats

Run: `just --list | grep unifi`
Expected: Single `unifi` task (no `unifi-wifi`, `usg`, `unifi-api`)

**Step 3: Commit**

```bash
git add Justfile
git commit -m "refactor(network): replace usg/unifi-wifi/unifi-api Justfile tasks with unified unifi"
```

---

### Task 7: Delete old entrypoint scripts

**Files:**
- Delete: `network/unifi-wifi.py`
- Delete: `network/usg.py`
- Delete: `network/unifi-api.py`

**Step 1: Remove old scripts**

```bash
git rm network/unifi-wifi.py network/usg.py network/unifi-api.py
```

**Step 2: Verify nothing is broken**

Run: `just unifi clients 2>&1 | head -5`
Run: `just unifi wifi aps 2>&1 | head -5`
Run: `just unifi usg stats 2>&1 | head -5`
Run: `just unifi devices 2>&1 | head -5`
Run: `just unifi topology 2>&1 | head -5`
Run: `just unifi checkup --sessions 1 2>&1 | head -10`
Run: `just unifi api get /stat/device 2>&1 | head -5`

All should produce normal output.

**Step 3: Commit**

```bash
git commit -m "refactor(network): remove old unifi-wifi.py, usg.py, unifi-api.py entrypoints"
```

---

### Task 8: Update `network/CLAUDE.md` documentation

**Files:**
- Modify: `network/CLAUDE.md`

**Step 1: Rewrite the CLI reference**

Replace the separate `unifi-wifi.py`, `usg.py`, and `unifi-api.py` sections with a single `unifi` section reflecting the new command structure. Keep all the diagnostic workflow shortcuts but update the commands (e.g., `just unifi-wifi checkup` → `just unifi checkup`).

Update the "Scripts" section header for unifi to reflect the unified CLI. Keep `wifi-diag.py`, `bgw.py`, `isp_status.py`, `snapshot.py`, `profile.py`, `resolve.py` sections unchanged.

**Step 2: Grep for stale command references**

Run: `grep -r "unifi-wifi\|unifi-api" network/CLAUDE.md network/docs/ docs/plans/`

Fix any stale references in docs that people might follow. Plans docs can be left as-is (they're historical).

**Step 3: Commit**

```bash
git add network/CLAUDE.md
git commit -m "docs(network): update CLAUDE.md for unified unifi CLI"
```

---

### Task 9: Update root `CLAUDE.md` if needed

**Files:**
- Check: `CLAUDE.md` (root)

**Step 1: Check for stale references**

Run: `grep -n "unifi-wifi\|unifi-api\|usg" CLAUDE.md`

If any references exist, update them to the new `just unifi ...` form.

**Step 2: Commit (if changes needed)**

```bash
git add CLAUDE.md
git commit -m "docs: update root CLAUDE.md for unified unifi CLI"
```
