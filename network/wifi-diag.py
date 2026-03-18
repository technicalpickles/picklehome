#!/usr/bin/env python3
"""
wifi-diag.py — Client-side WiFi and connectivity diagnostic

Run on any Mac in the home network to gather WiFi signal metrics, which AP
you're connected to, local/internet latency, traceroute, and download speed.

Usage:
    uv run --with requests network/wifi-diag.py
    uv run --with requests network/wifi-diag.py --no-trace
    uv run --with requests network/wifi-diag.py --no-trace --no-speed

The AP (BSSID) field identifies exactly which physical access point the device
is connected to. Cross-reference with: UniFi UI → Clients → <device> → AP.
"""

import argparse
import json
import platform
import re
import subprocess
import sys
import time
from datetime import datetime

import requests

AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
GATEWAY = "192.168.1.1"
INTERNET_TARGET = "8.8.8.8"
SPEED_URL = "https://speed.cloudflare.com/__down?bytes=25000000"  # 25 MB

SEP = "─" * 60

# Known IPs for annotating traceroute hops
KNOWN_HOSTS = {
    "192.168.1.1":    "USG 3P (LAN gateway)",
    "192.168.8.65":   "USG 3P (WAN)",
    "192.168.8.254":  "AT&T BGW320 (fiber gateway)",
    "192.168.1.57":   "CloudKey G2 Plus",
}


def section(title):
    print(f"\n{title}")
    print(SEP)


def run(cmd, timeout=30):
    """Run a command, return stdout or None on error/timeout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None


# ── WiFi Interface Detection ─────────────────────────────────────────────────

def wifi_interface():
    """Return the macOS interface name for Wi-Fi (usually en0 or en1)."""
    out = run(["networksetup", "-listallhardwareports"])
    if out:
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if "Wi-Fi" in line or "AirPort" in line:
                for j in range(i, min(i + 5, len(lines))):
                    m = re.search(r"Device:\s+(\w+)", lines[j])
                    if m:
                        return m.group(1)
    return "en0"


# ── WiFi Association Info ────────────────────────────────────────────────────

def _snr_label(snr):
    if snr >= 30:
        return "excellent"
    elif snr >= 20:
        return "good"
    elif snr >= 15:
        return "fair"
    return "poor — expect retransmits"


def _rssi_label(rssi):
    if rssi >= -70:
        return "good"
    elif rssi >= -80:
        return "marginal"
    return "weak"


def _get_bssid_wdutil():
    """
    Attempt to read BSSID via wdutil (macOS 13+ replacement for airport -I).
    wdutil writes a JSON dump to /var/tmp/wdutil-info-*.json when run as root.
    Without sudo we can't run it, so we try to read any recently written file.
    Falls back to '(requires sudo wdutil info)' if unavailable.
    """
    import glob as _glob
    import os

    # If user ran `sudo wdutil info` recently, a JSON file exists we can read
    candidates = sorted(
        _glob.glob("/var/tmp/wdutil-info-*.json"),
        key=os.path.getmtime,
        reverse=True,
    )
    if candidates:
        try:
            with open(candidates[0]) as f:
                data = json.load(f)
            # Path: WiFi → interfaces → [0] → bssid (structure varies by macOS version)
            wifi = data.get("WiFi", {})
            ifaces = wifi.get("interfaces", [])
            if ifaces:
                bssid = ifaces[0].get("bssid") or ifaces[0].get("BSSID")
                if bssid:
                    return bssid
        except Exception:
            pass

    return "(run 'sudo wdutil info' first to capture BSSID)"


def wifi_info(sp_data):
    section("WiFi — Current Association")

    if not sp_data:
        print("  system_profiler failed — no WiFi info available")
        return

    try:
        iface = sp_data["SPAirPortDataType"][0]["spairport_airport_interfaces"][0]
    except (KeyError, IndexError):
        print("  Could not parse WiFi info from system_profiler")
        return

    current = iface.get("spairport_current_network_information", {})
    if not current:
        print("  Not associated with any network")
        return

    ssid    = current.get("_name", "?")
    channel = current.get("spairport_network_channel", "?")
    phy     = current.get("spairport_network_phymode", "?")
    tx_rate = current.get("spairport_network_rate", "?")
    mcs     = current.get("spairport_network_mcs", "?")
    # macOS 13+: spairport_signal_noise is a compound string "-50 dBm / -89 dBm"
    sig_noise_raw = current.get("spairport_signal_noise", "")
    rssi_int = noise_int = None
    m = re.match(r"(-?\d+)\s*dBm\s*/\s*(-?\d+)\s*dBm", str(sig_noise_raw))
    if m:
        rssi_int, noise_int = int(m.group(1)), int(m.group(2))

    if rssi_int is not None:
        rssi_str = f"{rssi_int} dBm  ({_rssi_label(rssi_int)})  [good > -70, marginal -70–-80, weak < -80]"
    else:
        rssi_str = str(sig_noise_raw) or "?"

    if rssi_int is not None and noise_int is not None:
        snr = rssi_int - noise_int
        snr_str = f"{snr} dB  ({_snr_label(snr)})"
        noise_str = f"{noise_int} dBm"
    else:
        snr_str = "?"
        noise_str = "?"

    # BSSID removed from system_profiler in macOS 13+ (location privacy)
    # Retrieve via wdutil if available (requires sudo)
    bssid = _get_bssid_wdutil()

    print(f"  SSID:         {ssid}")
    print(f"  AP (BSSID):   {bssid}  ← which physical AP you're on")
    print(f"  RSSI:         {rssi_str}")
    print(f"  Noise:        {noise_str}")
    print(f"  SNR:          {snr_str}")
    print(f"  Channel:      {channel}")
    print(f"  PHY Mode:     {phy}")
    print(f"  Tx Rate:      {tx_rate} Mbps   MCS index: {mcs}")


# ── Visible Networks ─────────────────────────────────────────────────────────

def visible_networks(profiler_data):
    """Show nearby networks from already-fetched system_profiler data."""
    section("WiFi — Visible Networks (roaming candidates)")
    print("  (RSSI in dBm — higher/less negative is stronger)")
    print()

    try:
        iface = profiler_data["SPAirPortDataType"][0]["spairport_airport_interfaces"][0]
        # Key was renamed in macOS 15: spairport_network_information_other_local_wireless_networks
        # → spairport_airport_other_local_wireless_networks. Try both for compatibility.
        others = (
            iface.get("spairport_network_information_other_local_wireless_networks")
            or iface.get("spairport_airport_other_local_wireless_networks")
            or []
        )
    except (KeyError, IndexError):
        others = []

    if not others:
        print("  No other networks visible (or not on Wi-Fi)")
        return

    def parse_rssi(net):
        """Extract RSSI int from 'spairport_signal_noise' ('-56 dBm / -95 dBm') or plain int."""
        raw = net.get("spairport_signal_noise", net.get("spairport_network_signal_strength"))
        if raw is None:
            return None, None
        if isinstance(raw, str) and "/" in raw:
            parts = raw.split("/")
            try:
                rssi  = int(parts[0].strip().split()[0])
                noise = int(parts[1].strip().split()[0])
                return rssi, noise
            except (ValueError, IndexError):
                pass
        try:
            return int(raw), None
        except (ValueError, TypeError):
            return None, None

    # Header — omit BSSID (macOS redacts it for neighboring networks)
    print(f"  {'SSID':<32} {'RSSI':>5}  {'Noise':>6}  {'Channel':<16}  PHY")
    print(f"  {'─'*32} {'─'*5}  {'─'*6}  {'─'*16}  {'─'*16}")
    for net in sorted(others, key=lambda n: parse_rssi(n)[0] or -100, reverse=True):
        ssid    = net.get("_name", "?")[:32]
        rssi, noise = parse_rssi(net)
        rssi_str  = f"{rssi}" if rssi is not None else "?"
        noise_str = f"{noise}" if noise is not None else "?"
        channel = net.get("spairport_network_channel", "?")
        phy     = net.get("spairport_network_phymode", "?")
        print(f"  {ssid:<32} {rssi_str:>5}  {noise_str:>6}  {str(channel):<16}  {phy}")


# ── IP / Gateway / DNS ────────────────────────────────────────────────────────

def ip_info(iface):
    section(f"Network — IP / Gateway / DNS  (interface: {iface})")

    ip = run(["ipconfig", "getifaddr", iface])
    print(f"  IP:       {ip.strip() if ip else '(none — not connected?)'}")

    route = run(["route", "-n", "get", "default"])
    gw = "?"
    if route:
        m = re.search(r"gateway:\s+(\S+)", route)
        if m:
            gw = m.group(1)
    print(f"  Gateway:  {gw}")

    dns_out = run(["scutil", "--dns"])
    servers = []
    if dns_out:
        servers = re.findall(r"nameserver\[\d+\]\s*:\s+(\S+)", dns_out)
        servers = list(dict.fromkeys(servers))[:4]  # dedupe, cap at 4
    print(f"  DNS:      {', '.join(servers) if servers else '?'}")


# ── Latency ───────────────────────────────────────────────────────────────────

def latency(target, label, count=10):
    section(f"Latency → {label}  ({target})")

    out = run(["ping", "-c", str(count), "-q", target], timeout=count + 10)
    if not out:
        print(f"  ping {target} timed out or failed")
        return

    m = re.search(
        r"round-trip min/avg/max/stddev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms",
        out,
    )
    loss_m = re.search(r"(\d+\.?\d*)% packet loss", out)

    if m:
        avg = float(m.group(2))
        quality = "good" if avg < 5 else "okay" if avg < 20 else "high"
        print(f"  min / avg / max  =  {m.group(1)} / {m.group(2)} / {m.group(3)} ms  ({quality})")
        print(f"  stddev:  {m.group(4)} ms  (jitter indicator)")
    if loss_m:
        loss = float(loss_m.group(1))
        marker = "  ← packet loss!" if loss > 0 else ""
        print(f"  loss:    {loss:.0f}%{marker}")


# ── Traceroute ────────────────────────────────────────────────────────────────

def annotate_hop(ip):
    """Return a label for a known IP, empty string otherwise."""
    return f"  [{KNOWN_HOSTS[ip]}]" if ip in KNOWN_HOSTS else ""


def traceroute(target=INTERNET_TARGET):
    section(f"Traceroute → {target}")
    print("  (known hops annotated)")
    print()

    out = run(["traceroute", "-w", "2", "-m", "20", target], timeout=90)
    if not out:
        print("  traceroute timed out or failed")
        return

    for line in out.splitlines():
        # Extract first IP-looking thing from the hop line for annotation
        m = re.search(r"\(?([\d]+\.[\d]+\.[\d]+\.[\d]+)\)?", line)
        annotation = annotate_hop(m.group(1)) if m else ""
        print(f"  {line.strip()}{annotation}")


# ── Speed Test ────────────────────────────────────────────────────────────────

def speed_test():
    section("Speed — Internet Download  (Cloudflare, ~25 MB)")

    try:
        print(f"  Downloading from {SPEED_URL} ...")
        start = time.time()
        r = requests.get(SPEED_URL, stream=True, timeout=60)
        r.raise_for_status()
        bytes_dl = 0
        for chunk in r.iter_content(chunk_size=65536):
            bytes_dl += len(chunk)
        elapsed = time.time() - start
        mbps = (bytes_dl * 8) / (elapsed * 1_000_000)
        mb = bytes_dl / 1_000_000
        rating = "fast" if mbps > 200 else "okay" if mbps > 50 else "slow"
        print(f"  Downloaded:  {mb:.1f} MB in {elapsed:.1f}s")
        print(f"  Speed:       {mbps:.0f} Mbps  ({rating})")
    except Exception as e:
        print(f"  Speed test failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Client WiFi and connectivity diagnostic (macOS)"
    )
    parser.add_argument("--no-trace", action="store_true", help="Skip traceroute")
    parser.add_argument("--no-speed", action="store_true", help="Skip speed test")
    parser.add_argument("--no-scan",  action="store_true", help="Skip visible network scan")
    args = parser.parse_args()

    if platform.system() != "Darwin":
        sys.exit("wifi-diag.py currently supports macOS only")

    print(f"wifi-diag  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Host:  {platform.node()}")
    print(f"macOS: {platform.mac_ver()[0]}")

    iface = wifi_interface()

    # Fetch system_profiler once; share between wifi_info and visible_networks
    sp_out = run(["system_profiler", "SPAirPortDataType", "-json"], timeout=20)
    try:
        sp_data = json.loads(sp_out) if sp_out else {}
    except json.JSONDecodeError:
        sp_data = {}

    wifi_info(sp_data)

    if not args.no_scan:
        visible_networks(sp_data)

    ip_info(iface)
    latency(GATEWAY, "LAN gateway (USG)", count=10)
    latency(INTERNET_TARGET, "Internet (Google DNS)", count=5)

    if not args.no_trace:
        traceroute()

    if not args.no_speed:
        speed_test()

    print(f"\n{SEP}")
    print("Done.")


if __name__ == "__main__":
    main()
