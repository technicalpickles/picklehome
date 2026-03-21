#!/usr/bin/env python3
"""
UniFi USG diagnostic tool — queries the CloudKey (UniFi OS) Network API
for device details, live stats, and WAN interface information.

Requires UNIFI_API_KEY in .env (generate at Network → Integrations).

Usage:
    uv run --with requests --with python-dotenv network/usg.py devices
    uv run --with requests --with python-dotenv network/usg.py stats
    uv run --with requests --with python-dotenv network/usg.py wan
    uv run --with requests --with python-dotenv network/usg.py wan-detail
    uv run --with requests --with python-dotenv --with paramiko network/usg.py dns

SSH commands (dns) require UNIFI_ADMIN_USERNAME and UNIFI_ADMIN_PASSWORD in .env.
"""

import argparse
import os
import sys

from network.unifi import BASE, LEGACY, session


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
    gw = next((d for d in devices if d.get("model", "").startswith(("USG", "UGW"))), None)
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


def get_legacy(s, path, **kwargs):
    r = s.get(f"{LEGACY}{path}", timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()


def cmd_wan_detail(s):
    """Pull rich WAN details from the legacy API (IP, gateway, DNS, interface stats)."""
    data = get_legacy(s, "/stat/device")
    devices = data.get("data", [])
    usg = next((d for d in devices if d.get("model", "").startswith(("USG", "UGW"))), None)
    if usg is None:
        sys.exit("USG not found in legacy device stats")

    print(f"WAN Detail: {usg.get('name', usg.get('mac'))}  ({usg.get('model')})")
    print("─" * 60)

    for wan_key in ("wan1", "wan2"):
        wan = usg.get(wan_key)
        if not wan:
            continue
        label = wan_key.upper()
        print(f"\n  {label}: {wan.get('ifname')}  up={wan.get('up')}  {wan.get('speed')}Mbps")
        for field in ("ip", "netmask", "gateway", "dns"):
            val = wan.get(field)
            if val is not None:
                print(f"    {field:<12} {val}")
        rx_r = wan.get("rx_bytes-r", 0)
        tx_r = wan.get("tx_bytes-r", 0)
        print(f"    {'rx rate':<12} {rx_r/1_000_000:.2f} Mbps")
        print(f"    {'tx rate':<12} {tx_r/1_000_000:.2f} Mbps")
        print(f"    {'rx dropped':<12} {wan.get('rx_dropped', 0):,}")
        print(f"    {'rx errors':<12} {wan.get('rx_errors', 0):,}")

    # port_table has live counters per physical port
    print("\n  Port Stats:")
    print(f"    {'Port':<6} {'Name':<18} {'RX bytes':>14} {'TX bytes':>14} {'RX err':>8} {'TX err':>8} {'RX drop':>8}")
    print(f"    {'─'*6} {'─'*18} {'─'*14} {'─'*14} {'─'*8} {'─'*8} {'─'*8}")
    for port in usg.get("port_table", []):
        name = port.get("name", "?")
        idx = port.get("port_idx", port.get("ifname", "?"))
        rx_bytes = port.get("rx_bytes", 0)
        tx_bytes = port.get("tx_bytes", 0)
        rx_err = port.get("rx_errors", 0)
        tx_err = port.get("tx_errors", 0)
        rx_drop = port.get("rx_dropped", 0)
        print(f"    {str(idx):<6} {name:<18} {rx_bytes:>14,} {tx_bytes:>14,} {rx_err:>8,} {tx_err:>8,} {rx_drop:>8,}")


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


def ssh_run(commands: list[str]) -> dict[str, str]:
    """SSH to the USG and run a list of shell commands. Returns {cmd: output}."""
    import paramiko

    user = os.environ.get("UNIFI_ADMIN_USERNAME")
    passwd = os.environ.get("UNIFI_ADMIN_PASSWORD")
    if not user or not passwd:
        sys.exit("UNIFI_ADMIN_USERNAME / UNIFI_ADMIN_PASSWORD not set in .env")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.1.1", username=user, password=passwd, timeout=10)

    results = {}
    for cmd in commands:
        _, out, _ = client.exec_command(cmd)
        results[cmd] = out.read().decode().strip()
    client.close()
    return results


def cmd_dns():
    results = ssh_run([
        "cat /etc/dnsmasq.conf",
        "cat /etc/dnsmasq.d/dnsmasq-dhcp-config.conf",
        "cat /etc/resolv.conf.dhclient-new-eth0",
    ])

    print("USG DNS Forwarder Configuration")
    print("─" * 50)

    dnsmasq = results.get("cat /etc/dnsmasq.conf", "")
    print("\n  /etc/dnsmasq.conf (relevant lines):")
    for line in dnsmasq.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            print(f"    {line}")

    dhcp_conf = results.get("cat /etc/dnsmasq.d/dnsmasq-dhcp-config.conf", "").strip()
    if dhcp_conf:
        print("\n  /etc/dnsmasq.d/dnsmasq-dhcp-config.conf:")
        for line in dhcp_conf.splitlines():
            if line.strip() and not line.startswith("#"):
                print(f"    {line}")

    resolv = results.get("cat /etc/resolv.conf.dhclient-new-eth0", "")
    print("\n  resolv.conf from BGW DHCP (fallback nameservers):")
    for line in resolv.splitlines():
        print(f"    {line}")


def cmd_resolve(host: str):
    """Resolve a hostname via both USG forwarders and compare the IPs returned."""
    nameservers = {
        "1.1.1.1       (Cloudflare)": f"host {host} 1.1.1.1",
        "192.168.8.254 (BGW)       ": f"host {host} 192.168.8.254",
        "127.0.0.1     (USG local) ": f"host {host} 127.0.0.1",
    }
    results = ssh_run(list(nameservers.values()))

    def parse_ips(output):
        ips = []
        for line in output.splitlines():
            if "has address" in line:
                ips.append(line.split("has address")[-1].strip())
        return ips

    print(f"DNS resolution comparison: {host}")
    print("─" * 50)
    all_ips = {}
    for label, cmd in nameservers.items():
        ips = parse_ips(results[cmd])
        all_ips[label] = ips
        print(f"  {label}  {', '.join(ips) or '(no answer)'}")

    ip_sets = [frozenset(v) for v in all_ips.values() if v]
    if len(set(ip_sets)) > 1:
        print("\n  *** IPs DIFFER across nameservers ***")
    else:
        print("\n  IPs consistent across all nameservers")


def cmd_topology(s, fmt="text"):
    """Live network topology from device uplink chain."""
    data = get_legacy(s, "/stat/device")
    devices = data.get("data", [])

    # Build lookup by MAC
    by_mac = {}
    for d in devices:
        mac = d.get("mac", "")
        by_mac[mac] = d

    # Build parent→children map using uplink info
    children = {}  # parent_mac → [(port, child_device)]
    roots = []
    for d in devices:
        uplink = d.get("uplink") or {}
        parent_mac = uplink.get("uplink_mac", "")
        if parent_mac and parent_mac in by_mac:
            children.setdefault(parent_mac, []).append(
                (uplink.get("uplink_remote_port", "?"), d)
            )
        else:
            roots.append(d)

    # Sort children by port number
    for mac in children:
        children[mac].sort(key=lambda x: (int(x[0]) if str(x[0]).isdigit() else 999))

    def device_label(d):
        name = d.get("name", d.get("mac", "?"))
        model = d.get("model_name") or d.get("model", "?")
        ip = d.get("ip", "?")
        state = "online" if d.get("state") == 1 else "offline"
        return name, model, ip, state

    def radio_summary(d):
        """Return radio info lines for APs."""
        if d.get("type") != "uap":
            return []
        lines = []
        for r in d.get("radio_table_stats", []):
            band = "2.4GHz" if r.get("radio") == "ng" else "5GHz"
            ch = r.get("channel", "?")
            tx = r.get("tx_power", "?")
            clients = r.get("num_sta", 0)
            lines.append(f"{band} ch {ch} @ {tx}dBm ({clients} clients)")
        return lines

    def radio_badge(d):
        """Compact radio info for mermaid nodes."""
        if d.get("type") != "uap":
            return ""
        parts = []
        for r in d.get("radio_table_stats", []):
            band = "2.4" if r.get("radio") == "ng" else "5"
            ch = r.get("channel", "?")
            tx = r.get("tx_power", "?")
            parts.append(f"{band}:ch{ch}/{tx}dBm")
        total = sum(r.get("num_sta", 0) for r in d.get("radio_table_stats", []))
        if parts:
            return " ".join(parts) + f" [{total} clients]"
        return ""

    if fmt == "text":
        _topology_text(roots, children, device_label, radio_summary)
    elif fmt == "mermaid":
        _topology_mermaid(roots, children, by_mac, device_label, radio_badge)
    elif fmt == "dot":
        _topology_dot(roots, children, by_mac, device_label, radio_badge)


def _topology_text(roots, children, label_fn, radio_fn):
    """Render topology as indented text tree."""
    def walk(device, prefix="", is_last=True):
        name, model, ip, state = label_fn(device)
        connector = "└─ " if prefix else ""
        if prefix:
            connector = "└─ " if is_last else "├─ "
        state_str = f" [{state}]" if state != "online" else ""
        print(f"{prefix}{connector}{name}  ({model})  {ip}{state_str}")

        radios = radio_fn(device)
        mac = device.get("mac", "")
        kids = children.get(mac, [])
        child_prefix = prefix + ("   " if is_last else "│  ")
        if prefix:
            child_prefix = prefix + ("   " if is_last else "│  ")

        for line in radios:
            print(f"{child_prefix}  {line}")

        for i, (port, child) in enumerate(kids):
            last = i == len(kids) - 1
            port_str = f"[port {port}] " if port != "?" else ""
            name_c, model_c, ip_c, state_c = label_fn(child)
            state_str_c = f" [{state_c}]" if state_c != "online" else ""
            conn = "└─ " if last else "├─ "
            print(f"{child_prefix}{conn}{port_str}{name_c}  ({model_c})  {ip_c}{state_str_c}")

            child_radios = radio_fn(child)
            grand_prefix = child_prefix + ("   " if last else "│  ")
            for line in child_radios:
                print(f"{grand_prefix}  {line}")

            # Recurse into grandchildren
            child_mac = child.get("mac", "")
            grandkids = children.get(child_mac, [])
            for j, (gport, grandchild) in enumerate(grandkids):
                glast = j == len(grandkids) - 1
                walk(grandchild, grand_prefix, glast)

    for root in roots:
        walk(root)


def _topology_mermaid(roots, children, by_mac, label_fn, badge_fn):
    """Render topology as mermaid flowchart."""
    print("```mermaid")
    print("graph TD")

    def node_id(d):
        return d.get("mac", "x").replace(":", "")

    def walk(device):
        nid = node_id(device)
        name, model, ip, state = label_fn(device)
        badge = badge_fn(device)
        label_parts = [f"{name}", f"{model} · {ip}"]
        if badge:
            label_parts.append(badge)
        if state != "online":
            label_parts.append(f"⚠ {state}")
        label = "<br/>".join(label_parts)
        print(f"    {nid}[\"{label}\"]")

        if state != "online":
            print(f"    style {nid} stroke-dasharray: 5 5")

        mac = device.get("mac", "")
        for port, child in children.get(mac, []):
            cid = node_id(child)
            port_label = f"port {port}" if port != "?" else ""
            walk(child)
            if port_label:
                print(f"    {nid} -->|{port_label}| {cid}")
            else:
                print(f"    {nid} --> {cid}")

    for root in roots:
        walk(root)
    print("```")


def _topology_dot(roots, children, by_mac, label_fn, badge_fn):
    """Render topology as graphviz DOT."""
    print("digraph topology {")
    print("    rankdir=TB;")
    print("    node [shape=box, fontname=\"monospace\", fontsize=10];")
    print("    edge [fontname=\"monospace\", fontsize=9];")

    def node_id(d):
        return d.get("mac", "x").replace(":", "")

    def walk(device):
        nid = node_id(device)
        name, model, ip, state = label_fn(device)
        badge = badge_fn(device)
        label_parts = [name, f"{model} · {ip}"]
        if badge:
            label_parts.append(badge)
        label = "\\n".join(label_parts)
        style = ", style=dashed" if state != "online" else ""
        print(f"    {nid} [label=\"{label}\"{style}];")

        mac = device.get("mac", "")
        for port, child in children.get(mac, []):
            cid = node_id(child)
            port_label = f" [label=\"port {port}\"]" if port != "?" else ""
            walk(child)
            print(f"    {nid} -> {cid}{port_label};")

    for root in roots:
        walk(root)
    print("}")


def main():
    parser = argparse.ArgumentParser(description="UniFi USG diagnostic tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices", help="List all adopted devices")
    sub.add_parser("stats", help="Latest USG stats (CPU, mem, uplink rates)")
    sub.add_parser("wan", help="WAN interface definitions")
    sub.add_parser("wan-detail", help="Rich WAN details: IP, gateway, DNS, port counters (legacy API)")
    sub.add_parser("dns", help="USG dnsmasq config: upstream forwarders and fallback resolvers (SSH)")
    p = sub.add_parser("resolve", help="Resolve hostname via 1.1.1.1 vs BGW DNS and compare (SSH)")
    p.add_argument("host", help="Hostname to resolve")
    p_topo = sub.add_parser("topology", help="Live network topology: device tree with uplink ports and radio state")
    p_topo.add_argument("--format", choices=["text", "mermaid", "dot"], default="text", help="Output format (default: text)")

    args = parser.parse_args()

    if args.cmd == "dns":
        cmd_dns()
        return
    elif args.cmd == "resolve":
        cmd_resolve(args.host)
        return

    s = session()
    if args.cmd == "devices":
        cmd_devices(s)
    elif args.cmd == "stats":
        cmd_stats(s)
    elif args.cmd == "wan":
        cmd_wan(s)
    elif args.cmd == "wan-detail":
        cmd_wan_detail(s)
    elif args.cmd == "topology":
        cmd_topology(s, fmt=args.format)


if __name__ == "__main__":
    main()
