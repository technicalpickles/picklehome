"""UniFi USG gateway commands: stats, WAN, DNS, topology."""

import os
import sys

from network.unifi import BASE, LEGACY


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


def cmd_stats(s):
    site_id, site_name = get_site_id(s)
    devices = get(s, f"/sites/{site_id}/devices").get("data", [])

    # Find gateway device (USG): match by model prefix, then fall back to no uplink
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
