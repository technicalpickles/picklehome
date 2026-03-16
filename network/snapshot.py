#!/usr/bin/env python3
"""
Network snapshot — captures a full point-in-time summary of the home network:
  - BGW fiber signal and broadband status
  - USG WAN IP, gateway, DNS servers
  - USG dnsmasq forwarder config
  - DNS resolution check across all resolvers
  - Traceroute to a Cloudflare IP (peering health check)

Usage:
    uv run --with requests --with python-dotenv --with paramiko --with dnspython --with playwright network/snapshot.py
    uv run --with requests --with python-dotenv --with paramiko --with dnspython --with playwright network/snapshot.py --no-trace
"""

import argparse
import datetime
import sys
import warnings

import requests
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

BGW = "http://192.168.8.254"
CLOUDKEY = "https://192.168.1.57"

# Cloudflare test IP (cfl.dropboxstatic.com — known affected during peering issues)
CF_TEST_IP = "104.16.99.29"

SEP = "─" * 60


def section(title):
    print(f"\n{title}")
    print(SEP)


# ── BGW ────────────────────────────────────────────────────────────────────────

def bgw_fiber():
    import re
    try:
        r = requests.get(f"{BGW}/cgi-bin/fiberstat.ha", timeout=10)
        html = r.text
        plain = html.replace("&nbsp;", " ")
        metrics = re.findall(
            r"(Temperature|Tx Power|Rx Power)\s+Currently\s+([-\d]+)", plain
        )
        pairs = {}
        for m in re.finditer(
            r"<th[^>]*>\s*(.*?)\s*</th>\s*<td[^>]*>\s*(.*?)\s*</td>", html, re.DOTALL
        ):
            key = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            val = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if key and val:
                pairs[key] = val

        status = pairs.get("Optical WAN Operational Status", "?")
        link = pairs.get("Link State", "?")
        print(f"  Status          {status}  (link: {link})")
        for name, raw in metrics:
            raw = int(raw)
            if name in ("Tx Power", "Rx Power"):
                print(f"  {name:<16} {raw / 10:.1f} dBm")
            elif name == "Temperature":
                print(f"  {name:<16} {raw} °C")
    except Exception as e:
        print(f"  (error: {e})")


def bgw_broadband():
    import re
    try:
        r = requests.get(f"{BGW}/cgi-bin/broadbandstatistics.ha", timeout=10)
        html = r.text
        pairs = {}
        for m in re.finditer(
            r"<th[^>]*>\s*(.*?)\s*</th>\s*<td[^>]*>\s*(.*?)\s*</td>", html, re.DOTALL
        ):
            key = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            val = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if key and val:
                pairs[key] = val
        for key in ("Broadband Connection", "Broadband IPv4 Address", "Gateway IPv4 Address", "MTU"):
            if key in pairs:
                print(f"  {key:<35} {pairs[key]}")
    except Exception as e:
        print(f"  (error: {e})")


# ── USG ────────────────────────────────────────────────────────────────────────

def usg_wan():
    import os
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        print("  (UNIFI_API_KEY not set)")
        return
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    try:
        legacy = f"{CLOUDKEY}/proxy/network/api/s/default"
        data = s.get(f"{legacy}/stat/device", timeout=10).json()
        usg = next((d for d in data.get("data", []) if d.get("model", "").startswith(("USG", "UGW"))), None)
        if not usg:
            print("  (USG not found)")
            return
        for wan_key in ("wan1", "wan2"):
            wan = usg.get(wan_key)
            if not wan or not wan.get("up"):
                continue
            print(f"  {wan_key.upper()}  {wan.get('ifname')}  up={wan.get('up')}")
            for field in ("ip", "gateway", "dns"):
                val = wan.get(field)
                if val:
                    print(f"    {field:<12} {val}")
    except Exception as e:
        print(f"  (error: {e})")


def usg_dns():
    import os
    try:
        import paramiko
    except ImportError:
        print("  (paramiko not available)")
        return

    user = os.environ.get("UNIFI_ADMIN_USERNAME")
    passwd = os.environ.get("UNIFI_ADMIN_PASSWORD")
    if not user or not passwd:
        print("  (UNIFI_ADMIN_USERNAME / UNIFI_ADMIN_PASSWORD not set)")
        return
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect("192.168.1.1", username=user, password=passwd, timeout=10)
        _, out, _ = client.exec_command("cat /etc/dnsmasq.conf")
        conf = out.read().decode().strip()
        client.close()
        for line in conf.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and any(
                kw in line for kw in ("server=", "resolv-file", "all-servers", "no-resolv")
            ):
                print(f"  {line}")
    except Exception as e:
        print(f"  (error: {e})")


# ── DNS resolution ─────────────────────────────────────────────────────────────

def dns_check():
    try:
        import dns.resolver
        import dns.exception
    except ImportError:
        print("  (dnspython not available)")
        return

    nameservers = {
        "8.8.8.8  (Google)   ": "8.8.8.8",
        "1.1.1.1  (Cloudflare)": "1.1.1.1",
        "192.168.1.1 (USG)   ": "192.168.1.1",
    }
    host = "cloudflare.com"
    print(f"  Resolving {host}:")
    for label, ns in nameservers.items():
        r = dns.resolver.Resolver(configure=False)
        r.nameservers = [ns]
        r.timeout = 3.0
        r.lifetime = 3.0
        try:
            answers = sorted(str(rr) for rr in r.resolve(host, "A"))
            print(f"    {label}  {', '.join(answers)}")
        except dns.exception.Timeout:
            print(f"    {label}  (timeout)")
        except Exception as e:
            print(f"    {label}  (error: {e})")


# ── Peering trace ──────────────────────────────────────────────────────────────

def bgw_trace(target):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (playwright not available)")
        return

    print(f"  Traceroute to {target} from BGW WAN:")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"{BGW}/cgi-bin/diag.ha")
            page.fill("input[name='WebAddress']", target)
            page.click("input[name='Trace']")
            page.wait_for_function(
                f"document.querySelector('textarea') && "
                f"document.querySelector('textarea').value.includes('test done')",
                timeout=60_000,
            )
            result = page.locator("textarea").input_value()
            browser.close()
        for line in result.strip().splitlines():
            print(f"    {line}")
    except Exception as e:
        print(f"  (error: {e})")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Home network snapshot")
    parser.add_argument("--no-trace", action="store_true", help="Skip BGW traceroute (slow)")
    args = parser.parse_args()

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Network Snapshot  —  {ts}")
    print("=" * 60)

    section("BGW Fiber Signal")
    bgw_fiber()

    section("BGW Broadband (WAN)")
    bgw_broadband()

    section("USG WAN")
    usg_wan()

    section("USG DNS Forwarders (dnsmasq)")
    usg_dns()

    section("DNS Resolution Check")
    dns_check()

    if not args.no_trace:
        section(f"Peering Health — traceroute to {CF_TEST_IP} (Cloudflare)")
        bgw_trace(CF_TEST_IP)
    else:
        print("\n(traceroute skipped — use without --no-trace to include)")

    print(f"\n{'=' * 60}")
    print("Snapshot complete.")


if __name__ == "__main__":
    main()
