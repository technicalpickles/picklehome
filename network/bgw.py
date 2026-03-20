#!/usr/bin/env python3
"""
AT&T BGW router diagnostic tool — pulls fiber status, broadband stats,
and runs traceroute/ping/nslookup directly from the BGW WAN interface.

Status commands use requests (fast, no browser needed).
Diag commands use playwright to handle the BGW's progressive streaming output.

Usage:
    uv run --with requests --with playwright network/bgw.py fiber
    uv run --with requests --with playwright network/bgw.py broadband
    uv run --with requests --with playwright network/bgw.py trace <host_or_ip>
    uv run --with requests --with playwright network/bgw.py ping <host_or_ip>
    uv run --with requests --with playwright network/bgw.py nslookup <host>
"""

import argparse
import re
import sys

import requests

BGW = "http://192.168.8.254"
SESSION = requests.Session()


def get(path, **kwargs):
    return SESSION.get(f"{BGW}/cgi-bin/{path}", timeout=10, **kwargs)


def parse_table_pairs(html: str) -> dict[str, str]:
    """Extract label→value pairs from <th>label</th><td>value</td> rows."""
    pairs = {}
    for m in re.finditer(
        r"<th[^>]*>\s*(.*?)\s*</th>\s*<td[^>]*>\s*(.*?)\s*</td>", html, re.DOTALL
    ):
        key = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        val = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if key and val:
            pairs[key] = val
    return pairs


def extract_optical_metrics(html: str) -> list[tuple[str, int]]:
    """Extract the 'Currently X' values from <h1> headings (uses &nbsp; as separator)."""
    # Headings look like: <h1>Tx Power&nbsp;&nbsp;Currently 25</h1>
    plain = html.replace("&nbsp;", " ")
    return [
        (name, int(val))
        for name, val in re.findall(
            r"(Temperature|Vcc|Tx Bias|Tx Power|Rx Power)\s+Currently\s+([-\d]+)", plain
        )
    ]


def fmt_metric(name: str, raw: int) -> str:
    if name in ("Tx Power", "Rx Power"):
        # Help text confirms: "one-tenth of a dBm"
        return f"{raw / 10:.1f} dBm"
    elif name == "Temperature":
        return f"{raw} °C"
    elif name == "Vcc":
        # BGW heading shows integer volts (3 ≈ 3.3V, display is truncated)
        return f"~{raw} V"
    elif name == "Tx Bias":
        # BGW heading shows integer mA (truncated)
        return f"~{raw} mA"
    return str(raw)


def cmd_fiber():
    r = get("fiberstat.ha")
    html = r.text
    pairs = parse_table_pairs(html)
    metrics = extract_optical_metrics(html)

    print("Fiber Status")
    print("─" * 50)
    for key in [
        "Optical WAN Operational Status",
        "Link State",
        "Wave Length",
        "Tx Fault State",
        "Rx LOS State",
        "Vendor Name",
        "Vendor PN",
        "Vendor SN",
        "Vendor Date Code",
    ]:
        if key in pairs:
            print(f"  {key:<35} {pairs[key]}")

    if metrics:
        print()
        print("Optical Metrics")
        print("─" * 50)
        for name, raw in metrics:
            print(f"  {name:<35} {fmt_metric(name, raw)}  (raw: {raw})")


def cmd_broadband():
    r = get("broadbandstatistics.ha")
    html = r.text
    pairs = parse_table_pairs(html)

    print("Broadband Status")
    print("─" * 50)
    for key in [
        "Broadband Connection Source",
        "Broadband Connection",
        "Broadband Network Type",
        "Broadband IPv4 Address",
        "Gateway IPv4 Address",
        "MTU",
    ]:
        if key in pairs:
            print(f"  {key:<35} {pairs[key]}")


def cmd_wifi():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{BGW}/cgi-bin/home.ha")
        page.wait_for_load_state("networkidle")
        text = page.inner_text("body")
        browser.close()

    print("BGW WiFi Status")
    print("─" * 50)

    for band in ("2.4 GHz", "5 GHz"):
        # In the rendered text, look for "<band> Frequency Status  Enabled/Disabled"
        m = re.search(
            rf"{re.escape(band)} Frequency Status\s+(Enabled|Disabled)",
            text, re.IGNORECASE
        )
        freq_status = m.group(1) if m else "unknown"

        # SSID appears as "Network Name (SSID)  <value>" in the text block for each band
        # Find the band section and extract SSID from it
        band_section = text[m.start():m.start() + 500] if m else text
        ssid_m = re.search(r"Network Name \(SSID\)\s+(\S+)", band_section)
        ssid = ssid_m.group(1) if ssid_m else "—"

        status_icon = "✓" if freq_status.lower() == "disabled" else "⚠"
        print(f"  {band:<8}  Radio: {freq_status:<10}  SSID: {ssid}  {status_icon}")


# Maps CLI action name → (form button selector, completion marker in output)
DIAG_ACTIONS = {
    "trace":    ("input[name='Trace']",  "test done"),
    "ping":     ("input[name='Ping']",   "packet loss"),
    "nslookup": ("input[name='Lookup']", "Address:"),
}


def cmd_diag(action: str, target: str, ipv6: bool = False):
    from playwright.sync_api import sync_playwright

    btn_selector, done_marker = DIAG_ACTIONS[action]
    proto = "IPv6" if ipv6 else "IPv4"
    label = {"trace": "Traceroute", "ping": "Ping", "nslookup": "NSLookup"}[action]

    print(f"Running {label} to {target} from BGW WAN ({proto})...")
    print("─" * 50)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        page.goto(f"{BGW}/cgi-bin/diag.ha")
        page.fill("input[name='WebAddress']", target)

        if ipv6:
            page.check("input[value='IPv6']")

        page.click(btn_selector)

        # BGW streams output into a textarea; wait until the completion marker appears
        page.wait_for_function(
            f"document.querySelector('textarea') && "
            f"document.querySelector('textarea').value.includes({done_marker!r})",
            timeout=120_000,
        )

        result = page.locator("textarea").input_value()
        browser.close()

    print(result.strip())


def main():
    parser = argparse.ArgumentParser(description="AT&T BGW diagnostic tool")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("fiber",     help="Fiber signal / optical status")
    sub.add_parser("broadband", help="Broadband WAN connection status")
    sub.add_parser("wifi",      help="BGW WiFi radio status (both bands)")

    for cmd, desc in [
        ("trace", "Traceroute from BGW WAN interface"),
        ("ping", "Ping from BGW WAN interface"),
        ("nslookup", "DNS lookup from BGW"),
    ]:
        p = sub.add_parser(cmd, help=desc)
        p.add_argument("target", help="IP address or hostname")
        p.add_argument("--ipv6", action="store_true", help="Use IPv6")

    args = parser.parse_args()

    if args.cmd == "fiber":
        cmd_fiber()
    elif args.cmd == "broadband":
        cmd_broadband()
    elif args.cmd == "wifi":
        cmd_wifi()
    else:
        cmd_diag(args.cmd, args.target, getattr(args, "ipv6", False))


if __name__ == "__main__":
    main()
