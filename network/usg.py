#!/usr/bin/env python3
"""
UniFi USG diagnostic tool — queries the CloudKey (UniFi OS) Network API
for device details, live stats, and WAN interface information.

Requires UNIFI_API_KEY in .env (generate at Network → Integrations).

Usage:
    uv run --with requests --with python-dotenv network/usg.py devices
    uv run --with requests --with python-dotenv network/usg.py stats
    uv run --with requests --with python-dotenv network/usg.py wan
"""

import argparse
import os
import sys
import warnings

import requests
from dotenv import load_dotenv

load_dotenv()

CLOUDKEY = "https://192.168.1.57"
BASE = f"{CLOUDKEY}/proxy/network/integration/v1"

# Suppress InsecureRequestWarning for self-signed cert
warnings.filterwarnings("ignore", message="Unverified HTTPS request")


def session():
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        sys.exit("UNIFI_API_KEY not set — add it to .env")
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    return s


def get(s, path, **kwargs):
    r = s.get(f"{BASE}{path}", timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()


def get_site_id(s):
    data = get(s, "/sites")
    sites = data.get("data", [])
    if not sites:
        sys.exit("No sites found")
    # Use first site (most home setups have one)
    site = sites[0]
    return site["id"], site.get("name", site["id"])


def cmd_devices(s):
    site_id, site_name = get_site_id(s)
    data = get(s, f"/sites/{site_id}/devices")
    devices = data.get("data", [])

    print(f"Devices on site: {site_name}")
    print("─" * 70)
    for d in devices:
        state = d.get("state", "?")
        model = d.get("model", "?")
        ip = d.get("ipAddress", "?")
        fw = d.get("firmwareVersion", "?")
        name = d.get("name") or d.get("macAddress", "?")
        print(f"  {name:<25} {model:<12} {ip:<17} {state:<10} fw:{fw}")
        print(f"  {'':25} id: {d['id']}")


def cmd_stats(s):
    site_id, site_name = get_site_id(s)
    devices = get(s, f"/sites/{site_id}/devices").get("data", [])

    # Find gateway device (USG) — match by model prefix, then fall back to no uplink
    gw = next((d for d in devices if d.get("model", "").startswith("USG")), None)
    if gw is None:
        gw = next((d for d in devices if not (d.get("uplink") or {}).get("deviceId")), None)
    if gw is None and devices:
        gw = devices[0]
    if gw is None:
        sys.exit("No devices found")

    device_id = gw["id"]
    name = gw.get("name") or gw.get("macAddress")

    stats = get(s, f"/sites/{site_id}/devices/{device_id}/statistics/latest")

    print(f"Stats: {name}  ({gw.get('model', '?')}  {gw.get('ipAddress', '?')})")
    print("─" * 50)
    uptime = stats.get("uptimeSec", 0)
    days, rem = divmod(uptime, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    print(f"  Uptime         {days}d {hours}h {mins}m")
    print(f"  CPU            {stats.get('cpuUtilizationPct', '?'):.1f}%")
    print(f"  Memory         {stats.get('memoryUtilizationPct', '?'):.1f}%")
    print(f"  Load (1/5/15)  {stats.get('loadAverage1Min','?')} / {stats.get('loadAverage5Min','?')} / {stats.get('loadAverage15Min','?')}")

    uplink = stats.get("uplink", {})
    if uplink:
        tx = uplink.get("txRateBps", 0)
        rx = uplink.get("rxRateBps", 0)
        print(f"  Uplink TX      {tx/1_000_000:.2f} Mbps")
        print(f"  Uplink RX      {rx/1_000_000:.2f} Mbps")

    ifaces = stats.get("interfaces", {})
    for iface_type, iface_list in ifaces.items():
        if iface_list:
            print(f"\n  Interfaces ({iface_type}):")
            for iface in iface_list:
                print(f"    {iface}")


def cmd_wan(s):
    site_id, site_name = get_site_id(s)
    data = get(s, f"/sites/{site_id}/wans")
    wans = data.get("data", [])

    print(f"WAN Interfaces on site: {site_name}")
    print("─" * 50)
    if not wans:
        print("  (none)")
        return
    for w in wans:
        print(f"  ID:   {w.get('id')}")
        for k, v in w.items():
            if k != "id":
                print(f"  {k:<20} {v}")
        print()


def main():
    parser = argparse.ArgumentParser(description="UniFi USG diagnostic tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices", help="List all adopted devices")
    sub.add_parser("stats", help="Latest USG stats (CPU, mem, uplink rates)")
    sub.add_parser("wan", help="WAN interface definitions")

    args = parser.parse_args()
    s = session()

    if args.cmd == "devices":
        cmd_devices(s)
    elif args.cmd == "stats":
        cmd_stats(s)
    elif args.cmd == "wan":
        cmd_wan(s)


if __name__ == "__main__":
    main()
