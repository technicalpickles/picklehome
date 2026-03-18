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
    uv run --with requests --with python-dotenv network/unifi-wifi.py rfscan
    uv run --with requests --with python-dotenv network/unifi-wifi.py set-channel "tracy" 5 36

Notes on UniFi signal fields:
  signal  — actual RSSI in dBm (negative)       e.g. -62
  noise   — noise floor in dBm                  e.g. -104
  SNR     — signal - noise                       e.g. 42 dB
  rssi    — normalized 0-95 scale (NOT dBm)     ignore for diagnostics
  tx_rate / rx_rate — in Kbps from the API
  satisfaction — UniFi composite quality score 0-100 (signal + retries + latency)
"""

import argparse
import sys
from datetime import datetime, timezone

from network.unifi import LEGACY, session

SEP = "─" * 70


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


# ── Config command ────────────────────────────────────────────────────────────

def cmd_config(s):
    section("WiFi Configuration — Roaming & Power-Save Settings")

    # SSID settings
    wlans = get(s, "/rest/wlanconf")
    wlans = [w for w in wlans if w.get("enabled")]

    print()
    for w in wlans:
        print(f"  SSID: {w.get('name', '?')}")
        print(f"    Security:        {w.get('wpa_mode','?')}  wpa3={w.get('wpa3_support',False)}  wpa3_transition={w.get('wpa3_transition',False)}")
        print(f"    Fast Roaming:    {w.get('fast_roaming_enabled', False)}  (802.11r)")
        print(f"    BSS Transition:  {w.get('bss_transition', False)}  (802.11v steering hints)")
        print(f"    UAPSD:           {w.get('uapsd_enabled', False)}  (AP buffers frames for sleeping clients)")

        dtim_mode = w.get('dtim_mode', 'default')
        dtim_ng   = w.get('dtim_ng', '?')
        dtim_na   = w.get('dtim_na', '?')
        print(f"    DTIM:            mode={dtim_mode}  2.4GHz={dtim_ng}  5GHz={dtim_na}  (wake interval for PSM clients)")

        min_rssi         = w.get('minrate_na_enabled') or w.get('min_rssi_enabled')
        min_rssi_val     = w.get('min_rssi', '—')
        print(f"    Min RSSI:        enabled={min_rssi}  value={min_rssi_val}  (kicks clients below threshold)")

        band_steering = w.get('band_steering_mode', w.get('no2ghz_oui', '—'))
        print(f"    Band Steering:   {band_steering}")
        print()

    # Per-AP transmit power
    devices = get(s, "/stat/device")
    aps = sorted([d for d in devices if d.get("type") == "uap"], key=lambda d: d.get("name", ""))

    print(f"  {'AP':<24}  {'Band':<6}  {'Ch':>4}  {'TxPow':>6}  {'MaxPow':>7}  {'Mode':<8}  {'Clients':>7}")
    print(f"  {'─'*24}  {'─'*6}  {'─'*4}  {'─'*6}  {'─'*7}  {'─'*8}  {'─'*7}")

    for ap in aps:
        name = ap.get("name", ap.get("mac", "?"))
        rt   = {r["radio"]: r for r in ap.get("radio_table", [])}
        rts  = {r["radio"]: r for r in ap.get("radio_table_stats", [])}

        for radio_key in ("ng", "na"):
            cfg  = rt.get(radio_key)
            stat = rts.get(radio_key)
            if not cfg and not stat:
                continue
            b         = "5GHz" if radio_key == "na" else "2.4GHz"
            channel   = (stat or cfg or {}).get("channel", "?")
            tx_power      = stat.get("tx_power", "?") if stat else "?"
            max_power     = cfg.get("max_txpower", "?") if cfg else "?"
            tx_power_mode = cfg.get("tx_power_mode", "max") if cfg else "max"
            num_sta       = stat.get("num_sta", 0) if stat else 0
            at_max        = "  ← max" if tx_power_mode in ("max", "high") or (tx_power_mode == "max" and isinstance(tx_power, int) and isinstance(max_power, int) and tx_power >= max_power) else ""
            print(f"  {name:<24}  {b:<6}  {str(channel):>4}  {str(tx_power):>5} dBm  {str(max_power):>5} dBm  {tx_power_mode:<8}  {num_sta:>7}{at_max}")
        name = ""  # only print AP name on first radio row


# ── Roaming history command ───────────────────────────────────────────────────

def cmd_roaming(s, query, num_sessions=1):
    section(f"Roaming History — {query}")

    # Resolve query to a MAC. Check currently connected clients first, then
    # all-user history so offline clients work too.
    mac = None
    q = query.lower()

    clients = get(s, "/stat/sta")
    for c in clients:
        if (q in (c.get("hostname") or "").lower()
                or q == (c.get("ip") or "").lower()
                or q == (c.get("mac") or "").lower()):
            mac = c["mac"]
            break

    if not mac:
        all_users = get(s, "/stat/alluser")
        for c in all_users:
            if (q in (c.get("hostname") or "").lower()
                    or q == (c.get("last_ip") or "").lower()
                    or q == (c.get("mac") or "").lower()):
                mac = c["mac"]
                break

    if not mac:
        print(f"  No client found matching '{query}'")
        return

    # Build AP MAC → name map
    devices = get(s, "/stat/device")
    ap_names = {d["mac"]: d.get("name", d["mac"]) for d in devices if d.get("type") == "uap"}

    # Fetch session history
    r = s.get(f"{LEGACY}/stat/session", params={"mac": mac}, timeout=10)
    r.raise_for_status()
    sessions = r.json().get("data", [])[:num_sessions]

    if not sessions:
        print(f"  No session history found for {mac}")
        return

    for i, sess in enumerate(sessions):
        sess_start = datetime.fromtimestamp(sess["assoc_time"]).strftime("%Y-%m-%d %H:%M:%S")
        duration_s = sess.get("duration", 0)
        h, rem = divmod(duration_s, 3600)
        m, s_ = divmod(rem, 60)
        dur_str = f"{h}h {m}m {s_}s" if h else f"{m}m {s_}s"

        ap_name = ap_names.get(sess.get("ap_mac", ""), sess.get("ap_mac", "?"))
        print(f"\n  Session {i+1}  started {sess_start}  duration {dur_str}  sat_avg={sess.get('satisfaction_avg', '?')}")
        print()

        segments = sess.get("roaming_sessions", [])
        if not segments:
            print(f"    (no per-segment roaming data)")
            continue

        print(f"  {'Time':<10}  {'AP':<24}  {'Duration':>9}  {'Sat':>4}  {'Band'}")
        print(f"  {'─'*10}  {'─'*24}  {'─'*9}  {'─'*4}  {'─'*6}")

        for seg in segments:
            t = datetime.fromtimestamp(seg["start_time"]).strftime("%H:%M:%S")
            ap = ap_names.get(seg.get("ap_mac", ""), seg.get("ap_mac", "?"))
            d = seg.get("duration", 0)
            dm, ds = divmod(d, 60)
            d_str = f"{dm}m {ds}s" if dm else f"{ds}s"
            sat = seg.get("satisfaction", "?")
            band_key = seg.get("radio_band", "?")
            b = "5 GHz" if band_key == "na" else "2.4 GHz" if band_key == "ng" else band_key

            sat_flag = "  ←" if isinstance(sat, int) and sat < 90 else ""
            print(f"  {t:<10}  {ap:<24}  {d_str:>9}  {sat:>4}{sat_flag}")


# ── RF Scan command ───────────────────────────────────────────────────────────

def cmd_rfscan(s, include_own=False, fresh_minutes=None):
    section("RF Scan — Neighboring APs (passive scan results)")

    neighbors = get(s, "/stat/rogueap")
    if not neighbors:
        print("  No scan data available (APs may not have run a scan yet)")
        return

    # Collect our own AP MACs so we can exclude them from the neighbor view
    own_macs = set()
    if not include_own:
        devices = get(s, "/stat/device")
        for d in devices:
            if d.get("type") == "uap":
                own_macs.add(d.get("mac", "").lower())
                for vap in d.get("vap_table", []):
                    own_macs.add(vap.get("bssid", "").lower())
        neighbors = [n for n in neighbors if n.get("bssid", "").lower() not in own_macs]

    now = datetime.now(timezone.utc).timestamp()

    if fresh_minutes is not None:
        cutoff = now - fresh_minutes * 60
        neighbors = [n for n in neighbors if (n.get("last_seen") or 0) >= cutoff]
        if not neighbors:
            print(f"  No neighbors seen in the last {fresh_minutes} minutes")
            return

    def fmt_age(ts):
        if not ts:
            return "?"
        diff = now - ts
        if diff < 60:
            return "<1m ago"
        elif diff < 3600:
            return f"{int(diff / 60)}m ago"
        else:
            return f"{diff / 3600:.1f}h ago"

    # Separate 2.4 GHz (ch 1-14) from 5 GHz (ch 36+)
    ghz24 = [n for n in neighbors if n.get("channel", 0) <= 14]
    ghz5  = [n for n in neighbors if n.get("channel", 0) > 14]

    for label, band_aps in (("2.4 GHz", ghz24), ("5 GHz", ghz5)):
        if not band_aps:
            continue

        # Channel congestion summary
        by_channel = {}
        for n in band_aps:
            ch = n.get("channel", "?")
            by_channel.setdefault(ch, []).append(n.get("signal", -100))

        print(f"\n  {label} — channel congestion summary:")
        for ch in sorted(by_channel, key=lambda x: (x == "?", x)):
            sigs = by_channel[ch]
            strongest = max(sigs)
            print(f"    ch {str(ch):<5}  {len(sigs):>3} neighbor(s)   strongest: {strongest} dBm")

        # Full neighbor table
        print()
        print(f"  {label} — all neighbors:")
        print(f"  {'SSID':<32} {'BSSID':<18} {'Ch':>4}  {'Sig':>5}  {'Last Seen':>9}  {'Heard by'}")
        print(f"  {'─'*32} {'─'*18} {'─'*4}  {'─'*5}  {'─'*9}  {'─'*24}")

        band_aps.sort(key=lambda n: (n.get("channel", 0), -(n.get("signal") or -100)))
        for n in band_aps:
            ssid     = (n.get("essid") or "<hidden>")[:32]
            bssid    = n.get("bssid", "?")
            ch       = n.get("channel", "?")
            sig      = n.get("signal", None)
            sig_str  = f"{sig}" if sig is not None else "?"
            age_str  = fmt_age(n.get("last_seen"))
            # reported_by is a list of AP MACs that heard this neighbor
            heard    = ", ".join(n.get("ap_mac", [n.get("ap_mac", "?")])) if isinstance(n.get("ap_mac"), list) else (n.get("ap_mac") or "?")
            print(f"  {ssid:<32} {bssid:<18} {str(ch):>4}  {sig_str:>5}  {age_str:>9}  {heard}")


# ── Set-channel command ───────────────────────────────────────────────────────

def cmd_set_channel(s, ap_query, band, channel, yes=False):
    radio_key = "na" if band == "5" else "ng"

    devices = get(s, "/stat/device")
    aps = [d for d in devices if d.get("type") == "uap"]
    q = ap_query.lower()
    matches = [d for d in aps if q in d.get("name", "").lower()]

    if not matches:
        print(f"  No AP matching '{ap_query}'")
        print(f"  Known APs: {', '.join(d.get('name', '?') for d in aps)}")
        return
    if len(matches) > 1:
        print(f"  Ambiguous — '{ap_query}' matches: {', '.join(d.get('name') for d in matches)}")
        return

    ap = matches[0]
    name  = ap.get("name", "?")
    ap_id = ap["_id"]

    # Find current channel for display
    rt = {r["radio"]: r for r in ap.get("radio_table", [])}
    current = rt.get(radio_key, {}).get("channel", "?")

    band_label = "5 GHz" if band == "5" else "2.4 GHz"
    print(f"\n  AP:      {name}")
    print(f"  Band:    {band_label}")
    print(f"  Current: ch {current}")
    print(f"  New:     ch {channel}")
    print()

    if not yes:
        confirm = input("  This will briefly disconnect clients on this radio. Proceed? [y/N] ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            return

    radio_entry = rt.get(radio_key, {})
    radio_name = radio_entry.get("name", "wifi1" if radio_key == "na" else "wifi0")
    r = s.put(
        f"{LEGACY}/rest/device/{ap_id}",
        json={"radio_table": [{"radio": radio_key, "name": radio_name, "channel": channel}]},
        timeout=10,
    )
    result = r.json()
    meta = result.get("meta", {})
    if meta.get("rc") == "ok":
        print(f"  Done — {name} {band_label} set to ch {channel}")
        print("  (AP radio restarting; clients will reconnect in ~5–15s)")
    else:
        print(f"  Error: {meta.get('msg', 'unknown')} (rc={meta.get('rc')})")


# ── Locate command ────────────────────────────────────────────────────────────

def cmd_locate(s, ap_query, duration=None):
    devices = get(s, "/stat/device")
    aps = [d for d in devices if d.get("type") == "uap"]
    q = ap_query.lower()
    matches = [d for d in aps if q in d.get("name", "").lower()]

    if not matches:
        print(f"  No AP matching '{ap_query}'")
        print(f"  Known APs: {', '.join(d.get('name', '?') for d in aps)}")
        return
    if len(matches) > 1:
        print(f"  Ambiguous — '{ap_query}' matches: {', '.join(d.get('name') for d in matches)}")
        return

    ap = matches[0]
    name = ap.get("name", "?")
    mac  = ap["mac"]

    def locate_cmd(cmd):
        r = s.post(f"{LEGACY}/cmd/devmgr", json={"cmd": cmd, "mac": mac}, timeout=10)
        r.raise_for_status()
        return r.json().get("meta", {})

    meta = locate_cmd("set-locate")
    if meta.get("rc") != "ok":
        print(f"  Error: {meta.get('msg', 'unknown')} (rc={meta.get('rc')})")
        return

    print(f"  {name} LED is now flashing")

    try:
        if duration:
            import time
            print(f"  Auto-stopping in {duration}s... (Ctrl-C to stop early)")
            time.sleep(duration)
        else:
            input("  Press Enter to stop locating...")
    except KeyboardInterrupt:
        print()
    finally:
        locate_cmd("unset-locate")
        print(f"  {name} LED locate stopped")


# ── Set-power command ─────────────────────────────────────────────────────────

def cmd_set_power(s, ap_query, band, mode, tx_power=None, yes=False):
    radio_key = "na" if band == "5" else "ng"

    devices = get(s, "/stat/device")
    aps = [d for d in devices if d.get("type") == "uap"]
    q = ap_query.lower()
    matches = [d for d in aps if q == "all" or q in d.get("name", "").lower()]

    if not matches:
        print(f"  No AP matching '{ap_query}'")
        print(f"  Known APs: {', '.join(d.get('name', '?') for d in aps)}")
        return
    if q != "all" and len(matches) > 1:
        print(f"  Ambiguous — '{ap_query}' matches: {', '.join(d.get('name') for d in matches)}")
        return

    band_label = "5 GHz" if band == "5" else "2.4 GHz"
    print(f"\n  Band:    {band_label}")
    print(f"  Mode:    {mode}" + (f"  ({tx_power} dBm)" if mode == "custom" else ""))
    print()
    print(f"  {'AP':<24}  {'Current TxPow':>13}  {'Max':>5}")
    print(f"  {'─'*24}  {'─'*13}  {'─'*5}")

    for ap in matches:
        name = ap.get("name", "?")
        rts  = {r["radio"]: r for r in ap.get("radio_table_stats", [])}
        rt   = {r["radio"]: r for r in ap.get("radio_table", [])}
        cur  = rts.get(radio_key, {}).get("tx_power", "?")
        mx   = rt.get(radio_key, {}).get("max_txpower", "?")
        print(f"  {name:<24}  {str(cur):>10} dBm  {str(mx):>3} dBm")

    print()
    if not yes:
        ap_desc = "all APs" if q == "all" else f"{len(matches)} AP(s)"
        confirm = input(f"  Set {band_label} tx power to {mode} on {ap_desc}? [y/N] ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            return

    payload_extra = {"tx_power": tx_power} if mode == "custom" else {}

    for ap in matches:
        name  = ap.get("name", "?")
        ap_id = ap["_id"]
        rt    = {r["radio"]: r for r in ap.get("radio_table", [])}
        radio_entry = rt.get(radio_key, {})
        radio_name  = radio_entry.get("name", "wifi1" if radio_key == "na" else "wifi0")

        r = s.put(
            f"{LEGACY}/rest/device/{ap_id}",
            json={"radio_table": [{"radio": radio_key, "name": radio_name,
                                   "tx_power_mode": mode, **payload_extra}]},
            timeout=10,
        )
        result = r.json()
        meta = result.get("meta", {})
        if meta.get("rc") == "ok":
            print(f"  {name}: done")
        else:
            print(f"  {name}: error — {meta.get('msg', 'unknown')} (rc={meta.get('rc')})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="UniFi WiFi diagnostics — AP radio stats and client signal metrics"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("aps",     help="All APs: radio config, channel utilization, client counts")
    sub.add_parser("clients", help="All WiFi clients: AP, signal, SNR, rates, satisfaction")
    sub.add_parser("config",  help="SSID roaming/power-save settings and per-AP transmit power")
    p = sub.add_parser("client",  help="Detail for one client (hostname, IP, or MAC)")
    p.add_argument("query", help="Hostname, IP, or MAC address (partial hostname match OK)")
    p_roam = sub.add_parser("roaming", help="Roaming history for one client: which APs, when, how long, satisfaction")
    p_roam.add_argument("query", help="Hostname, IP, or MAC address (partial hostname match OK)")
    p_roam.add_argument("--sessions", type=int, default=1, metavar="N", help="Number of past sessions to show (default: 1)")
    p2 = sub.add_parser("rfscan", help="Neighboring APs from passive RF scan — channel congestion summary")
    p2.add_argument("--own", action="store_true", help="Include your own APs in results")
    p2.add_argument("--fresh", type=int, metavar="MINUTES", default=None, help="Only show neighbors seen within the last N minutes")
    p4 = sub.add_parser("set-power", help="Set transmit power mode on an AP or all APs")
    p4.add_argument("ap",   help="AP name (partial match OK), or 'all' for every AP")
    p4.add_argument("band", choices=["2.4", "5"], help="Radio band")
    p4.add_argument("mode", choices=["auto", "low", "medium", "high", "custom"], help="Power mode")
    p4.add_argument("--dbm", type=int, default=None, help="dBm value when mode=custom")
    p4.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    p3 = sub.add_parser("set-channel", help="Set radio channel on an AP (disconnects clients briefly)")
    p3.add_argument("ap",      help="AP name (partial match OK)")
    p3.add_argument("band",    choices=["2.4", "5"], help="Radio band to change")
    p3.add_argument("channel", help="Channel number, or 'auto'")
    p3.add_argument("--yes",   action="store_true", help="Skip confirmation prompt")
    p5 = sub.add_parser("locate", help="Flash an AP's LED to physically identify it")
    p5.add_argument("ap", help="AP name (partial match OK)")
    p5.add_argument("--duration", type=int, default=None, metavar="SECONDS", help="Auto-stop after N seconds (default: wait for Enter)")

    args = parser.parse_args()
    s = session()

    if args.cmd == "config":
        cmd_config(s)
    elif args.cmd == "aps":
        cmd_aps(s)
    elif args.cmd == "clients":
        cmd_clients(s)
    elif args.cmd == "client":
        cmd_client(s, args.query)
    elif args.cmd == "roaming":
        cmd_roaming(s, args.query, num_sessions=args.sessions)
    elif args.cmd == "rfscan":
        cmd_rfscan(s, include_own=args.own, fresh_minutes=args.fresh)
    elif args.cmd == "set-power":
        if args.mode == "custom" and args.dbm is None:
            parser.error("--dbm required when mode=custom")
        cmd_set_power(s, args.ap, args.band, args.mode, tx_power=args.dbm, yes=args.yes)
    elif args.cmd == "set-channel":
        ch = args.channel if args.channel == "auto" else int(args.channel)
        cmd_set_channel(s, args.ap, args.band, ch, yes=args.yes)
    elif args.cmd == "locate":
        cmd_locate(s, args.ap, duration=args.duration)


if __name__ == "__main__":
    main()
