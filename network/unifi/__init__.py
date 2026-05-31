"""Shared UniFi CloudKey authentication."""

import os
import sys
import warnings

import requests
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CLOUDKEY = "https://192.168.1.57"
LEGACY = f"{CLOUDKEY}/proxy/network/api/s/default"
BASE = f"{CLOUDKEY}/proxy/network/integration/v1"


def session() -> requests.Session:
    """Return an authenticated requests.Session for the UniFi CloudKey API."""
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        sys.exit("UNIFI_API_KEY not set: add it to .env")
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    return s


SEP = "─" * 70


def get(s, path):
    """GET from legacy API endpoint and return data array."""
    r = s.get(f"{LEGACY}{path}", timeout=10)
    r.raise_for_status()
    return r.json().get("data", [])


def section(title):
    print(f"\n{title}")
    print(SEP)


def get_base(s, path):
    """GET from integration API endpoint and return full JSON."""
    r = s.get(f"{BASE}{path}", timeout=10)
    r.raise_for_status()
    return r.json()


def get_legacy(s, path, **kwargs):
    """GET from legacy API endpoint and return full JSON (not just .data)."""
    r = s.get(f"{LEGACY}{path}", timeout=10, **kwargs)
    r.raise_for_status()
    return r.json()


def get_site_id(s):
    data = get_base(s, "/sites")
    sites = data.get("data", [])
    if not sites:
        sys.exit("No sites found")
    # Use first site (most home setups have one)
    site = sites[0]
    return site["id"], site.get("name", site["id"])


def cmd_devices(s):
    site_id, site_name = get_site_id(s)
    data = get_base(s, f"/sites/{site_id}/devices")
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
