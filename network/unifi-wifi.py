#!/usr/bin/env python3
"""
unifi-wifi.py — UniFi WiFi diagnostics from the AP perspective

Queries the CloudKey legacy API for per-AP radio stats and per-client WiFi
metrics (signal, noise, SNR, link rates, retries, satisfaction score).

Useful for confirming which AP a client is on, diagnosing signal quality from
the AP's perspective, and spotting channel congestion across all radios.

Requires UNIFI_API_KEY in .env (generate at Network → Integrations).

Usage:
    uv run --with requests --with python-dotenv network/unifi-wifi.py aps
    uv run --with requests --with python-dotenv network/unifi-wifi.py clients
    uv run --with requests --with python-dotenv network/unifi-wifi.py client <hostname|ip|mac>

Notes on UniFi signal fields:
  signal  — actual RSSI in dBm (negative)       e.g. -62
  noise   — noise floor in dBm                  e.g. -104
  SNR     — signal - noise                       e.g. 42 dB
  rssi    — normalized 0-95 scale (NOT dBm)     ignore for diagnostics
  tx_rate / rx_rate — in Kbps from the API
  satisfaction — UniFi composite quality score 0-100 (signal + retries + latency)
"""

import argparse
import os
import sys
import warnings
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CLOUDKEY = "https://192.168.1.57"
LEGACY = f"{CLOUDKEY}/proxy/network/api/s/default"
SEP = "─" * 70


def session():
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        sys.exit("UNIFI_API_KEY not set — add it to .env")
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    return s


def get(s, path):
    r = s.get(f"{LEGACY}{path}", timeout=10)
    r.raise_for_status()
    return r.json().get("data", [])


def section(title):
    print(f"\n{title}")
    print(SEP)


# ── Signal quality helpers ────────────────────────────────────────────────────

def snr_label(snr):
    if snr >= 30:
        return "excellent"
    elif snr >= 20:
        return "good"
    elif snr >= 15:
        return "fair"
    return "poor"


def signal_label(dbm):
    if dbm >= -67:
        return "good"
    elif dbm >= -75:
        return "marginal"
    return "weak"


def retry_label(pct):
    if pct < 5:
        return "ok"
    elif pct < 15:
        return "elevated"
    return "high"


def band(radio):
    return "5GHz" if radio == "na" else "2.4GHz"


def kbps_to_mbps(kbps):
    return f"{kbps / 1000:.0f}" if kbps else "?"


# ── APs command ───────────────────────────────────────────────────────────────

def cmd_aps(s):
    section("Access Points — Radio Stats")

    devices = get(s, "/stat/device")
    aps = [d for d in devices if d.get("type") == "uap"]

    if not aps:
        print("  No APs found")
        return

    aps.sort(key=lambda d: d.get("name", ""))

    for ap in aps:
        name   = ap.get("name", ap.get("mac", "?"))
        model  = ap.get("model", "?")
        ip     = ap.get("ip", "?")
        state  = ap.get("state", 0)
        status = "online" if state == 1 else "offline"

        print(f"\n  {name}  ({model})  {ip}  [{status}]")

        rt  = {r["radio"]: r for r in ap.get("radio_table", [])}
        rts = {r["radio"]: r for r in ap.get("radio_table_stats", [])}

        for radio_key in ("ng", "na"):
            cfg  = rt.get(radio_key)
            stat = rts.get(radio_key)
            if not cfg and not stat:
                continue

            b       = band(radio_key)
            channel = (stat or cfg or {}).get("channel", "?")
            bw      = (stat or cfg or {}).get("bw", "?")
            cu      = stat.get("cu_total", "?") if stat else "?"
            cu_rx   = stat.get("cu_self_rx", "?") if stat else "?"
            cu_tx   = stat.get("cu_self_tx", "?") if stat else "?"
            num_sta = stat.get("num_sta", 0) if stat else 0
            sat     = stat.get("satisfaction", -1) if stat else -1
            retries = stat.get("tx_retries_pct", None) if stat else None
            tx_pow  = stat.get("tx_power", "?") if stat else "?"

            sat_str = f"{sat}" if sat >= 0 else "—"
            ret_str = f"{retries:.1f}%" if retries is not None else "?"

            print(f"    {b:<7}  ch {channel:<5} {bw}MHz   "
                  f"clients: {num_sta:<3}  "
                  f"utilization: {cu}% (rx {cu_rx}% / tx {cu_tx}%)   "
                  f"satisfaction: {sat_str}   retries: {ret_str}   tx_power: {tx_pow} dBm")


# ── Clients command ───────────────────────────────────────────────────────────

def cmd_clients(s):
    section("WiFi Clients — All Connected")

    clients = get(s, "/stat/sta")
    # Only WiFi clients (wired devices can appear in /stat/sta if previously wireless)
    clients = [c for c in clients if not c.get("is_wired") and c.get("signal") is not None]
    # Sort: by AP name, then signal strength ascending (weakest last)
    clients.sort(key=lambda c: (c.get("last_uplink_name", ""), c.get("signal", 0)))

    print(f"  {'Hostname':<28} {'IP':<16} {'AP':<24} {'Band':<6} {'Ch':>4}  {'Sig':>5}  {'SNR':>4}  {'TxMbps':>7}  {'Sat':>4}  {'Retry%':>7}")
    print(f"  {'─'*28} {'─'*16} {'─'*24} {'─'*6} {'─'*4}  {'─'*5}  {'─'*4}  {'─'*7}  {'─'*4}  {'─'*7}")

    for c in clients:
        hostname = (c.get("hostname") or c.get("mac", "?"))[:28]
        ip       = c.get("ip", c.get("last_ip", "?"))
        ap_name  = (c.get("last_uplink_name") or c.get("ap_mac", "?"))[:24]
        radio    = c.get("radio", "?")
        b        = "5G" if radio == "na" else "2.4G"
        channel  = c.get("channel", "?")
        sig      = c.get("signal", None)
        noise    = c.get("noise", None)
        tx_rate  = kbps_to_mbps(c.get("tx_rate"))
        sat      = c.get("satisfaction", -1)
        retries  = c.get("wifi_tx_retries_percentage", None)

        sig_str = f"{sig}" if sig is not None else "?"
        snr_str = f"{sig - noise}" if sig is not None and noise is not None else "?"
        sat_str = f"{sat}" if sat >= 0 else "—"
        ret_str = f"{retries:.1f}" if retries is not None else "?"

        print(f"  {hostname:<28} {ip:<16} {ap_name:<24} {b:<6} {str(channel):>4}  {sig_str:>5}  {snr_str:>4}  {tx_rate:>7}  {sat_str:>4}  {ret_str:>7}")


# ── Single client command ─────────────────────────────────────────────────────

def cmd_client(s, query):
    section(f"Client Detail — {query}")

    clients = get(s, "/stat/sta")
    q = query.lower()
    matches = [
        c for c in clients
        if q in (c.get("hostname") or "").lower()
        or q == (c.get("ip") or "").lower()
        or q == (c.get("last_ip") or "").lower()
        or q == (c.get("mac") or "").lower()
        or q == (c.get("bssid") or "").lower()
    ]

    if not matches:
        print(f"  No connected client matching '{query}'")
        print("  (client may be offline — use 'clients' to see all connected)")
        return

    for c in matches:
        hostname  = c.get("hostname") or c.get("mac", "?")
        ip        = c.get("ip", c.get("last_ip", "?"))
        mac       = c.get("mac", "?")
        ap_name   = c.get("last_uplink_name") or c.get("ap_mac", "?")
        ap_mac    = c.get("ap_mac", "?")
        bssid     = c.get("bssid", "?")
        radio     = c.get("radio", "?")
        b         = band(radio)
        channel   = c.get("channel", "?")
        ch_width  = c.get("channelWidth", c.get("channel_width", "?"))
        sig       = c.get("signal")
        noise     = c.get("noise")
        tx_rate   = c.get("tx_rate", 0)
        rx_rate   = c.get("rx_rate", 0)
        tx_mcs    = c.get("tx_mcs", "?")
        nss       = c.get("nss", "?")
        sat       = c.get("satisfaction", -1)
        sat_now   = c.get("satisfaction_now", -1)
        retries   = c.get("wifi_tx_retries_percentage")
        uptime    = c.get("uptime", 0)
        assoc_ts  = c.get("latest_assoc_time")
        tx_bytes  = c.get("tx_bytes", 0)
        rx_bytes  = c.get("rx_bytes", 0)
        proto     = c.get("radio_proto", "?")

        snr = (sig - noise) if sig is not None and noise is not None else None

        # Uptime formatting
        days, rem = divmod(uptime, 86400)
        hours, rem = divmod(rem, 3600)
        mins = rem // 60
        uptime_str = f"{days}d {hours}h {mins}m" if days else f"{hours}h {mins}m"

        assoc_str = ""
        if assoc_ts:
            dt = datetime.fromtimestamp(assoc_ts, tz=timezone.utc).astimezone()
            assoc_str = dt.strftime("%Y-%m-%d %H:%M")

        print(f"\n  Hostname:      {hostname}")
        print(f"  IP:            {ip}")
        print(f"  MAC:           {mac}")
        print()
        print(f"  AP:            {ap_name}  ({ap_mac})")
        print(f"  BSSID:         {bssid}  (AP radio MAC)")
        print(f"  Band:          {b}  ({proto})")
        print(f"  Channel:       {channel}  width: {ch_width} MHz")
        print()
        if sig is not None:
            print(f"  Signal:        {sig} dBm  ({signal_label(sig)})")
        if noise is not None:
            print(f"  Noise:         {noise} dBm")
        if snr is not None:
            print(f"  SNR:           {snr} dB  ({snr_label(snr)})")
        print(f"  Tx Rate:       {kbps_to_mbps(tx_rate)} Mbps   MCS {tx_mcs}  NSS {nss}")
        print(f"  Rx Rate:       {kbps_to_mbps(rx_rate)} Mbps")
        print()
        if retries is not None:
            print(f"  TX Retries:    {retries:.1f}%  ({retry_label(retries)})")
        sat_str = f"{sat}" if sat >= 0 else "—"
        sat_now_str = f"{sat_now}" if sat_now >= 0 else "—"
        print(f"  Satisfaction:  {sat_str}  (now: {sat_now_str})")
        print()
        print(f"  Uptime:        {uptime_str}  (last assoc: {assoc_str})")
        print(f"  TX:            {tx_bytes/1_000_000:.1f} MB   RX: {rx_bytes/1_000_000:.1f} MB")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UniFi WiFi diagnostics — AP radio stats and client signal metrics"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("aps",     help="All APs: radio config, channel utilization, client counts")
    sub.add_parser("clients", help="All WiFi clients: AP, signal, SNR, rates, satisfaction")
    p = sub.add_parser("client",  help="Detail for one client (hostname, IP, or MAC)")
    p.add_argument("query", help="Hostname, IP, or MAC address (partial hostname match OK)")

    args = parser.parse_args()
    s = session()

    if args.cmd == "aps":
        cmd_aps(s)
    elif args.cmd == "clients":
        cmd_clients(s)
    elif args.cmd == "client":
        cmd_client(s, args.query)


if __name__ == "__main__":
    main()
