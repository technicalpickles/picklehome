#!/usr/bin/env python3
"""
unifi_cli.py — Unified UniFi CLI

Top-level: clients, client, rename, devices, topology, checkup, api
WiFi group: aps, config, rfscan, roaming, set-power, set-channel, locate
USG group: stats, wan, wan-detail, dns, resolve

Usage:
    uv run network/unifi_cli.py clients
    uv run network/unifi_cli.py wifi aps
    uv run network/unifi_cli.py usg stats
    uv run network/unifi_cli.py devices
    uv run network/unifi_cli.py checkup
"""

import argparse
import os
import re
import sys

from network.unifi import LEGACY, get, section, session, cmd_devices, cmd_topology
from network.unifi.wifi import (
    cmd_aps, cmd_clients, cmd_client, cmd_config, cmd_rfscan,
    cmd_roaming, cmd_set_channel, cmd_set_power, cmd_locate,
)
from network.unifi.usg import cmd_stats, cmd_wan, cmd_wan_detail, cmd_dns, cmd_resolve


def watched_devices():
    """Load watched device names from UNIFI_WATCHED_DEVICES env var (comma or newline separated)."""
    raw = os.environ.get("UNIFI_WATCHED_DEVICES", "")
    return [d.strip() for d in re.split(r"[,\n]", raw) if d.strip()]


def cmd_checkup(s, num_sessions=1):
    """Composite network health check: AP retries, RF neighbors, watched device roaming."""
    cmd_aps(s, sort_by="retries")
    cmd_rfscan(s, fresh_minutes=60, summary_only=True)
    devices = watched_devices()
    if devices:
        for device in devices:
            cmd_roaming(s, device, num_sessions=num_sessions)
    else:
        print("\n  (UNIFI_WATCHED_DEVICES not set — skipping roaming section)")


def cmd_rename(s, query, new_name):
    section(f"Rename Client — {query}")

    # Search live clients first, then all-time user list for offline devices
    clients = get(s, "/stat/sta")
    q = query.lower()
    matches = [
        c for c in clients
        if q in (c.get("hostname") or "").lower()
        or q in (c.get("name") or "").lower()
        or q == (c.get("ip") or "").lower()
        or q == (c.get("last_ip") or "").lower()
        or q == (c.get("mac") or "").lower()
    ]

    if not matches:
        # Fall back to all-time user list (offline devices)
        users = get(s, "/rest/user")
        matches = [
            u for u in users
            if q in (u.get("hostname") or "").lower()
            or q in (u.get("name") or "").lower()
            or q == (u.get("mac") or "").lower()
        ]

    if not matches:
        print(f"  No client matching '{query}'")
        return
    if len(matches) > 1:
        print(f"  Ambiguous — '{query}' matches multiple clients:")
        for c in matches:
            h = c.get("name") or c.get("hostname") or c.get("mac", "?")
            print(f"    {h}  ({c.get('mac', '?')})")
        return

    client = matches[0]
    user_id = client.get("_id")
    old_name = client.get("name") or client.get("hostname") or client.get("mac", "?")
    mac = client.get("mac", "?")

    print(f"  Client:    {old_name}")
    print(f"  MAC:       {mac}")
    print(f"  New name:  {new_name}")
    print()

    r = s.put(
        f"{LEGACY}/rest/user/{user_id}",
        json={"name": new_name},
        timeout=10,
    )
    result = r.json()
    meta = result.get("meta", {})
    if meta.get("rc") == "ok":
        print(f"  Done — renamed to '{new_name}'")
    else:
        print(f"  Error: {meta.get('msg', 'unknown')} (rc={meta.get('rc')})")


def cmd_api(s, method, path, body=None):
    import json as json_mod
    url = f"{LEGACY}{path}"
    if method.upper() == "GET":
        r = s.get(url, timeout=10)
    elif method.upper() == "PUT":
        payload = json_mod.loads(body) if body else {}
        r = s.put(url, json=payload, timeout=10)
    elif method.upper() == "POST":
        payload = json_mod.loads(body) if body else {}
        r = s.post(url, json=payload, timeout=10)
    elif method.upper() == "DELETE":
        r = s.delete(url, timeout=10)
    else:
        sys.exit(f"Unsupported method: {method}")
    r.raise_for_status()
    print(json_mod.dumps(r.json(), indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Unified UniFi CLI — WiFi, gateway, and device management"
    )
    sub = parser.add_subparsers(dest="cmd")

    # ── Top-level commands ────────────────────────────────────────────────────
    sub.add_parser("clients", help="All WiFi clients: AP, signal, SNR, rates, satisfaction")

    p_client = sub.add_parser("client", help="Detail for one client (hostname, IP, or MAC)")
    p_client.add_argument("query", help="Hostname, IP, or MAC address (partial hostname match OK)")

    p_rename = sub.add_parser("rename", help="Set a friendly alias for a client device")
    p_rename.add_argument("query", help="Hostname, IP, or MAC of the client to rename")
    p_rename.add_argument("name", help="New friendly name (alias) for the client")

    sub.add_parser("devices", help="List all adopted devices")

    p_topo = sub.add_parser("topology", help="Live network topology: device tree with uplink ports and radio state")
    p_topo.add_argument("--format", choices=["text", "mermaid", "dot"], default="text", help="Output format (default: text)")

    p_chk = sub.add_parser("checkup", help="Network health: AP retries + RF neighbors + watched device roaming")
    p_chk.add_argument("--sessions", type=int, default=1, metavar="N", help="Roaming sessions per device (default: 1)")

    p_api = sub.add_parser("api", help="Raw API call (GET/PUT/POST/DELETE)")
    p_api.add_argument("method", choices=["get", "put", "post", "delete"], help="HTTP method")
    p_api.add_argument("path", help="API path (relative to legacy API base)")
    p_api.add_argument("body", nargs="?", default=None, help="JSON body for PUT/POST")

    # ── WiFi subgroup ─────────────────────────────────────────────────────────
    wifi_parser = sub.add_parser("wifi", help="WiFi commands (aps, config, rfscan, roaming, ...)")
    wifi_sub = wifi_parser.add_subparsers(dest="wifi_cmd")

    p_aps = wifi_sub.add_parser("aps", help="All APs: radio config, channel utilization, client counts")
    p_aps.add_argument("--sort", choices=["name", "retries", "utilization"], default="name", help="Sort APs by field (default: name)")

    wifi_sub.add_parser("config", help="SSID roaming/power-save settings and per-AP transmit power")

    p_rfscan = wifi_sub.add_parser("rfscan", help="Neighboring APs from passive RF scan — channel congestion summary")
    p_rfscan.add_argument("--own", action="store_true", help="Include your own APs in results")
    p_rfscan.add_argument("--fresh", type=int, metavar="MINUTES", default=None, help="Only show neighbors seen within the last N minutes")
    p_rfscan.add_argument("--summary", action="store_true", help="Show only the channel congestion summary, skip full neighbor table")

    p_roam = wifi_sub.add_parser("roaming", help="Roaming history for one client")
    p_roam.add_argument("query", nargs="?", default=None, help="Hostname, IP, or MAC (partial OK). Omit to show all watched devices.")
    p_roam.add_argument("--sessions", type=int, default=1, metavar="N", help="Number of past sessions to show (default: 1)")

    p_sp = wifi_sub.add_parser("set-power", help="Set transmit power mode on an AP or all APs")
    p_sp.add_argument("ap", help="AP name (partial match OK), or 'all' for every AP")
    p_sp.add_argument("band", choices=["2.4", "5"], help="Radio band")
    p_sp.add_argument("mode", choices=["auto", "low", "medium", "high", "custom"], help="Power mode")
    p_sp.add_argument("--dbm", type=int, default=None, help="dBm value when mode=custom")
    p_sp.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    p_sc = wifi_sub.add_parser("set-channel", help="Set radio channel on an AP (disconnects clients briefly)")
    p_sc.add_argument("ap", help="AP name (partial match OK)")
    p_sc.add_argument("band", choices=["2.4", "5"], help="Radio band to change")
    p_sc.add_argument("channel", help="Channel number, or 'auto'")
    p_sc.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    p_loc = wifi_sub.add_parser("locate", help="Flash an AP's LED to physically identify it")
    p_loc.add_argument("ap", help="AP name (partial match OK)")
    p_loc.add_argument("--duration", type=int, default=None, metavar="SECONDS", help="Auto-stop after N seconds (default: wait for Enter)")

    # ── USG subgroup ──────────────────────────────────────────────────────────
    usg_parser = sub.add_parser("usg", help="USG gateway commands (stats, wan, dns, ...)")
    usg_sub = usg_parser.add_subparsers(dest="usg_cmd")

    usg_sub.add_parser("stats", help="Latest USG stats (CPU, mem, uplink rates)")
    usg_sub.add_parser("wan", help="WAN interface definitions")
    usg_sub.add_parser("wan-detail", help="Rich WAN details: IP, gateway, DNS, port counters (legacy API)")
    usg_sub.add_parser("dns", help="USG dnsmasq config: upstream forwarders and fallback resolvers (SSH)")

    p_resolve = usg_sub.add_parser("resolve", help="Resolve hostname via 1.1.1.1 vs BGW DNS and compare (SSH)")
    p_resolve.add_argument("host", help="Hostname to resolve")

    # ── Parse and dispatch ────────────────────────────────────────────────────
    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    # SSH-only commands (no session needed)
    if args.cmd == "usg" and args.usg_cmd == "dns":
        cmd_dns()
        return
    if args.cmd == "usg" and args.usg_cmd == "resolve":
        cmd_resolve(args.host)
        return

    # USG subgroup help
    if args.cmd == "usg" and not args.usg_cmd:
        usg_parser.print_help()
        sys.exit(1)

    # WiFi subgroup help
    if args.cmd == "wifi" and not args.wifi_cmd:
        wifi_parser.print_help()
        sys.exit(1)

    # All other commands need a session
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
    elif args.cmd == "api":
        cmd_api(s, args.method, args.path, body=args.body)

    # WiFi subcommands
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
                devs = watched_devices()
                if not devs:
                    print("  No query given and UNIFI_WATCHED_DEVICES not set in .env")
                    print("  Usage: unifi roaming <hostname>")
                    sys.exit(1)
                for device in devs:
                    cmd_roaming(s, device, num_sessions=args.sessions)
        elif args.wifi_cmd == "set-power":
            if args.mode == "custom" and args.dbm is None:
                parser.error("--dbm required when mode=custom")
            cmd_set_power(s, args.ap, args.band, args.mode, tx_power=args.dbm, yes=args.yes)
        elif args.wifi_cmd == "set-channel":
            ch = args.channel if args.channel == "auto" else int(args.channel)
            cmd_set_channel(s, args.ap, args.band, ch, yes=args.yes)
        elif args.wifi_cmd == "locate":
            cmd_locate(s, args.ap, duration=args.duration)

    # USG subcommands
    elif args.cmd == "usg":
        if args.usg_cmd == "stats":
            cmd_stats(s)
        elif args.usg_cmd == "wan":
            cmd_wan(s)
        elif args.usg_cmd == "wan-detail":
            cmd_wan_detail(s)


if __name__ == "__main__":
    main()
