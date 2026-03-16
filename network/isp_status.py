#!/usr/bin/env python3
"""
ISP and CDN status checker — surfaces outages relevant to this network.

Checks:
  - Cloudflare status (overall + nearby colos + active incidents)
  - Cloudflare trace (which colo your traffic is routing through)
  - Cloudflare Radar BGP events (hijacks + leaks for AS7018/AT&T)
  - Cloudflare Radar NetFlows traffic trend for AT&T (AS7018)
  - RIPE BGP state: your IP's current ASN + Cloudflare/Google prefix health
  - AT&T outage lookup by ZIP code (requires --zip, uses Playwright)
  - DownDetector AT&T report status (manual URL — bot-protected)

Usage:
    uv run --with requests --with python-dotenv network/isp_status.py
    uv run --with requests --with python-dotenv --with playwright network/isp_status.py --zip 30318

Requires CLOUDFLARE_RADAR_API_TOKEN in .env (Account > Radar: Read scope).
"""

import argparse
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

RADAR_BASE = "https://api.cloudflare.com/client/v4/radar"
ATT_ASN = 7018
BGP_HIJACK_MIN_CONFIDENCE = 4  # 1-3=low, 4-7=medium, 8+=high

CLOUDFLARE_STATUS_API = "https://www.cloudflarestatus.com/api/v2"
CLOUDFLARE_TRACE_URL = "https://one.one.one.one/cdn-cgi/trace"

# Components of interest by name fragment
INTERESTING_COLOS = ["ATL", "Atlanta", "IAH", "Houston", "DFW", "Dallas"]

MANUAL_URLS = [
    # BGP.he.net and PeeringDB omitted — HTML-only, no useful API; RIPE Stat covers the same signals
    ("DownDetector — AT&T", "https://downdetector.com/status/att/"),
]

RIPE_STAT = "https://stat.ripe.net/data"

# Prefixes to watch for origin/visibility changes
WATCH_PREFIXES = [
    ("Cloudflare", "1.1.1.0/24",  13335),
    ("Google DNS", "8.8.8.0/24",  15169),
]

SEP = "─" * 60


def get_json(url: str) -> dict | None:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [error] {url}: {e}")
        return None


def get_text(url: str) -> str | None:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"  [error] {url}: {e}")
        return None


def check_cloudflare_status():
    print("Cloudflare Status")
    print(SEP)

    data = get_json(f"{CLOUDFLARE_STATUS_API}/summary.json")
    if not data:
        return

    # Overall indicator
    status = data["status"]
    indicator = status["indicator"]   # none / minor / major / critical
    desc = status["description"]
    flag = "✓" if indicator == "none" else "!"
    print(f"  [{flag}] Overall: {desc}  ({indicator})")
    print()

    # Components matching colos of interest
    matches = [
        c for c in data["components"]
        if any(colo in c["name"] for colo in INTERESTING_COLOS)
    ]
    if matches:
        print("  Nearby colos:")
        for c in matches:
            s = c["status"]
            flag = "✓" if s == "operational" else "!"
            print(f"    [{flag}] {c['name']}: {s}")
        print()


def check_cloudflare_incidents():
    print("Cloudflare Active Incidents")
    print(SEP)

    data = get_json(f"{CLOUDFLARE_STATUS_API}/incidents/unresolved.json")
    if not data:
        return

    incidents = data.get("incidents", [])
    if not incidents:
        print("  [✓] No active incidents")
    else:
        for inc in incidents:
            print(f"  [!] {inc['name']}  (impact: {inc['impact']})")
            latest = inc.get("incident_updates", [{}])[0]
            if latest.get("body"):
                print(f"      {latest['body'][:200]}")
    print()


def check_cloudflare_trace():
    print("Cloudflare Trace  (routing from this machine)")
    print(SEP)

    text = get_text(CLOUDFLARE_TRACE_URL)
    if not text:
        return

    fields = dict(line.split("=", 1) for line in text.strip().splitlines() if "=" in line)
    colo = fields.get("colo", "?")
    ip = fields.get("ip", "?")
    loc = fields.get("loc", "?")

    print(f"  Colo:     {colo}")
    print(f"  Your IP:  {ip}  ({loc})")
    print()


def check_att_outages(zip_code: str):
    """Check AT&T outage status for a ZIP code using Playwright."""
    from playwright.sync_api import sync_playwright

    print("AT&T Outage Status")
    print(SEP)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto("https://www.att.com/outages/", timeout=20000)
            page.fill('input[placeholder="Enter Zip code"]', zip_code)
            page.evaluate(
                "Array.from(document.querySelectorAll('button'))"
                ".find(b => b.textContent.trim() === 'Check for outages').click()"
            )
            page.wait_for_selector(".rad-chk-txt", timeout=10000)

            labels = page.eval_on_selector_all(
                ".rad-chk-txt",
                "els => els.map(e => e.textContent.trim())"
            )
            zip_status = labels[0] if labels else "(no status found)"
            outage = "Heads up" in zip_status
            flag = "!" if outage else "✓"
            print(f"  [{flag}] ZIP {zip_code}: {zip_status}")
        except Exception as e:
            print(f"  [error] {e}")
        finally:
            browser.close()
    print()



def _sparkline(values: list[float]) -> str:
    """
    Render a list of 0.0–1.0 normalized floats as a Unicode block sparkline.

    Values come from Cloudflare's MIN0_MAX normalization — 0.0 is the window
    minimum, 1.0 is the window maximum. Maps each float to one of 9 block
    characters: ' ' (0.0) through '█' (1.0).
    """
    BLOCKS = " ▁▂▃▄▅▆▇█"
    return "".join(BLOCKS[min(8, int(v * 9))] for v in values)


def _radar_get(token: str, path: str, params: dict = None) -> dict | None:
    try:
        r = requests.get(
            f"{RADAR_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params={**(params or {}), "format": "json"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("result", {})
    except Exception as e:
        print(f"  [error] Radar {path}: {e}")
        return None


def check_radar_bgp(token: str):
    print("Cloudflare Radar — BGP Events (AT&T AS7018)")
    print(SEP)

    # Hijacks
    result = _radar_get(token, "/bgp/hijacks/events", {"involvedAsn": ATT_ASN, "per_page": 20})
    if result is not None:
        active = [
            e for e in result.get("events", [])
            if not e.get("is_stale") and e.get("tags") and
            any(t.get("score", 0) >= BGP_HIJACK_MIN_CONFIDENCE for t in e.get("tags", []))
        ]
        if active:
            for e in active[:3]:
                prefixes = ", ".join(e.get("prefixes", []))
                hijacker = e.get("hijacker_asn")
                ts = e.get("min_hijack_ts", "")[:16]
                print(f"  [!] Hijack: AS{hijacker} → {prefixes}  ({ts})")
        else:
            print("  [✓] No active BGP hijacks")

    # Leaks
    result = _radar_get(token, "/bgp/leaks/events", {"involvedAsn": ATT_ASN, "per_page": 20})
    if result is not None:
        active = [e for e in result.get("events", []) if not e.get("finished")]
        if active:
            for e in active[:3]:
                seg = " → ".join(f"AS{a}" for a in e.get("leak_seg", []))
                ts = e.get("detected_ts", "")[:16]
                print(f"  [!] Leak: {seg}  ({ts})")
        else:
            print("  [✓] No active BGP route leaks")

    print()


def check_radar_traffic(token: str):
    print("Cloudflare Radar — AT&T (AS7018) Traffic Trend  (last 24h)")
    print(SEP)

    result = _radar_get(token, "/netflows/timeseries", {
        "asn": ATT_ASN, "product": "ALL",
        "dateRange": "1d", "aggInterval": "1h",
    })
    if not result:
        return

    serie = result.get("serie_0", {})
    timestamps = serie.get("timestamps", [])
    raw_values = [float(v) for v in serie.get("values", [])]

    if not raw_values:
        print("  (no data)")
        print()
        return

    spark = _sparkline(raw_values)

    # Last 3 hours vs peak — flag a sustained drop
    recent_avg = sum(raw_values[-3:]) / 3
    peak = max(raw_values)
    pct = int(recent_avg / peak * 100) if peak else 0

    start_ts = timestamps[0][11:16] if timestamps else "?"
    end_ts = timestamps[-1][11:16] if timestamps else "?"
    updated = result.get("meta", {}).get("lastUpdated", "")[:16].replace("T", " ")
    print(f"  {start_ts}Z ┤{spark}├ {end_ts}Z  (data as of {updated}Z)")
    print(f"  Recent avg (last 3h): {pct}% of 24h peak", end="")
    if pct < 40:
        print("  [?] Low vs peak — may just be overnight hours (threshold needs tuning)")
    else:
        print()
    print()


def check_ripe_routing():
    print("RIPE — BGP Routing State")
    print(SEP)

    # Look up your public IP's ASN — dynamic, not hardcoded
    your_ip = None
    trace = get_text(CLOUDFLARE_TRACE_URL)
    if trace:
        fields = dict(line.split("=", 1) for line in trace.strip().splitlines() if "=" in line)
        your_ip = fields.get("ip")

    if your_ip:
        data = get_json(f"{RIPE_STAT}/prefix-overview/data.json?resource={your_ip}")
        if data:
            asns = data.get("data", {}).get("asns", [])
            if asns:
                a = asns[0]
                flag = "✓" if a["asn"] == ATT_ASN else "?"
                print(f"  [{flag}] Your IP {your_ip} → AS{a['asn']} ({a['holder']})")
            else:
                print(f"  [?] Your IP {your_ip} → ASN unknown")

    # Prefix visibility + origin for watched prefixes
    for name, prefix, expected_origin in WATCH_PREFIXES:
        data = get_json(f"{RIPE_STAT}/routing-status/data.json?resource={prefix}")
        if not data:
            continue
        d = data.get("data", {})
        vis = d.get("visibility", {}).get("v4", {})
        seeing = vis.get("ris_peers_seeing", 0)
        total = vis.get("total_ris_peers", 1)
        origins = [o["origin"] for o in d.get("origins", [])]
        pct = int(seeing / total * 100)
        origin_str = ", ".join(f"AS{o}" for o in origins)
        flag = "✓" if pct >= 90 and expected_origin in origins else "!"
        print(f"  [{flag}] {name} ({prefix}): origin {origin_str}, {seeing}/{total} peers ({pct}%)")

    print()


def print_manual_urls():
    print("Manual Check URLs")
    print(SEP)
    for label, url in MANUAL_URLS:
        print(f"  {label:<24}  {url}")
    print()


def main():
    parser = argparse.ArgumentParser(description="ISP and CDN status checker")
    parser.add_argument("--zip", metavar="ZIP", help="ZIP code for AT&T outage lookup (falls back to HOME_ZIP_CODE env var)")
    args = parser.parse_args()

    zip_code = args.zip or os.environ.get("HOME_ZIP_CODE") or None
    use_playwright = bool(zip_code)
    radar_token = os.environ.get("CLOUDFLARE_RADAR_API_TOKEN")

    print()
    check_cloudflare_status()
    check_cloudflare_incidents()
    check_cloudflare_trace()

    if radar_token:
        check_radar_bgp(radar_token)
        check_radar_traffic(radar_token)
    else:
        print("Cloudflare Radar  (set CLOUDFLARE_RADAR_API_TOKEN in .env to enable)")
        print(SEP)
        print()

    if use_playwright:
        check_att_outages(zip_code)
    else:
        print("AT&T Outage  (pass --zip XXXXX to check with Playwright)")
        print(SEP)
        print("  https://www.att.com/outages/")
        print()

    check_ripe_routing()
    if MANUAL_URLS:
        print_manual_urls()


if __name__ == "__main__":
    main()
