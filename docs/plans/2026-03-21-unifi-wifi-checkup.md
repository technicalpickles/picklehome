# UniFi WiFi Checkup Enhancements: Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add four usability improvements to `unifi-wifi.py`: `--summary` flag for rfscan, `--sort` flag for aps, bare `roaming` for watched devices, and a composite `checkup` command.

**Architecture:** All changes are in `network/unifi-wifi.py` (CLI + functions) with one env var addition (`UNIFI_WATCHED_DEVICES`) wired through the existing 1Password → `.env` pattern. Each feature builds on existing functions. `checkup` composes the others.

**Tech Stack:** Python 3, requests, argparse, python-dotenv, 1Password CLI (`op inject`)

---

### Task 1: Add `UNIFI_WATCHED_DEVICES` to env template

**Files:**
- Modify: `.env.template:23` (append new entry)

**Step 1: Add the env var reference**

Add to `.env.template` after the Ambient Weather section:

```
# Watched WiFi devices for roaming checks (comma-separated hostnames; 1Password item: picklehome/UniFi)
UNIFI_WATCHED_DEVICES={{ op://picklehome/UniFi/watched_devices }}
```

**Step 2: Add the field in 1Password**

Manual step: the user must add a `watched_devices` text field to the `UniFi` item in the `picklehome` vault with value `iPickleX-2,raisynglsiPhone`.

**Step 3: Regenerate .env**

Run: `just dotenv`

**Step 4: Verify**

Run: `grep UNIFI_WATCHED_DEVICES .env`
Expected: `UNIFI_WATCHED_DEVICES=iPickleX-2,raisynglsiPhone`

**Step 5: Commit**

```bash
git add .env.template
git commit -m "feat: add UNIFI_WATCHED_DEVICES to env template for roaming checks"
```

---

### Task 2: Add `--summary` flag to `rfscan`

**Files:**
- Modify: `network/unifi-wifi.py:403` (`cmd_rfscan` function)
- Modify: `network/unifi-wifi.py:661` (argparse for rfscan)

**Step 1: Add `--summary` argument to argparse**

At line 663 (after the `--fresh` argument), add:

```python
p2.add_argument("--summary", action="store_true", help="Show only the channel congestion summary, skip full neighbor table")
```

**Step 2: Thread the parameter through to `cmd_rfscan`**

Change the function signature at line 403:

```python
def cmd_rfscan(s, include_own=False, fresh_minutes=None, summary_only=False):
```

**Step 3: Skip the full neighbor table when `summary_only=True`**

In the `for label, band_aps` loop (line 446), the channel congestion summary prints first (lines 450–460), then the full neighbor table (lines 462–478). Wrap the full neighbor table block in a guard:

```python
        if summary_only:
            continue

        # Full neighbor table
        print()
        # ... (existing code unchanged)
```

**Step 4: Wire up in the dispatch block**

At line 693, change:

```python
    elif args.cmd == "rfscan":
        cmd_rfscan(s, include_own=args.own, fresh_minutes=args.fresh, summary_only=args.summary)
```

**Step 5: Test**

Run: `just unifi-wifi rfscan --summary --fresh 60`
Expected: Only the channel congestion summary tables (2.4 GHz + 5 GHz), no full neighbor listing.

Run: `just unifi-wifi rfscan --fresh 60`
Expected: Same output as before (summary + full table).

**Step 6: Commit**

```bash
git add network/unifi-wifi.py
git commit -m "feat: add --summary flag to rfscan for concise channel congestion view"
```

---

### Task 3: Add `--sort` flag to `aps`

**Files:**
- Modify: `network/unifi-wifi.py:87` (`cmd_aps` function)
- Modify: `network/unifi-wifi.py:653` (argparse for aps)

**Step 1: Replace the plain `add_parser` with one that accepts `--sort`**

At line 653, change:

```python
sub.add_parser("aps", help="All APs: radio config, channel utilization, client counts")
```

to:

```python
p_aps = sub.add_parser("aps", help="All APs: radio config, channel utilization, client counts")
p_aps.add_argument("--sort", choices=["name", "retries", "utilization"], default="name", help="Sort APs by field (default: name)")
```

**Step 2: Thread sort parameter into `cmd_aps`**

Change function signature:

```python
def cmd_aps(s, sort_by="name"):
```

**Step 3: Implement sorting**

After line 91 (`aps = [d for d in devices if d.get("type") == "uap"]`), replace the existing sort (line 97) with:

```python
    def ap_sort_key(d):
        if sort_by == "retries":
            # Max retry % across radios, descending (negate for reverse sort)
            rts = {r["radio"]: r for r in d.get("radio_table_stats", [])}
            max_retry = max((rts.get(k, {}).get("tx_retries_pct", 0) or 0) for k in ("ng", "na"))
            return -max_retry
        elif sort_by == "utilization":
            rts = {r["radio"]: r for r in d.get("radio_table_stats", [])}
            max_cu = max((rts.get(k, {}).get("cu_total", 0) or 0) for k in ("ng", "na"))
            return -max_cu
        return d.get("name", "")

    aps.sort(key=ap_sort_key)
```

**Step 4: Wire up in dispatch**

At the `elif args.cmd == "aps"` line, change:

```python
    elif args.cmd == "aps":
        cmd_aps(s, sort_by=args.sort)
```

**Step 5: Test**

Run: `just unifi-wifi aps --sort retries`
Expected: APs sorted by highest retry rate first (Tracy Office should be near top).

Run: `just unifi-wifi aps`
Expected: Same alphabetical order as before.

**Step 6: Commit**

```bash
git add network/unifi-wifi.py
git commit -m "feat: add --sort flag to aps command (retries, utilization, name)"
```

---

### Task 4: Make `roaming` query optional: show watched devices when bare

**Files:**
- Modify: `network/unifi-wifi.py:326` (`cmd_roaming` function, add multi-device wrapper)
- Modify: `network/unifi-wifi.py:658` (argparse for roaming)

**Step 1: Make `query` optional in argparse**

At line 659, change:

```python
p_roam.add_argument("query", help="Hostname, IP, or MAC address (partial hostname match OK)")
```

to:

```python
p_roam.add_argument("query", nargs="?", default=None, help="Hostname, IP, or MAC (partial OK). Omit to show all watched devices.")
```

**Step 2: Add a helper to load watched devices**

Add near the top of the file (after the `SEP` constant, around line 36):

```python
def watched_devices():
    """Load watched device hostnames from UNIFI_WATCHED_DEVICES env var."""
    raw = os.environ.get("UNIFI_WATCHED_DEVICES", "")
    return [d.strip() for d in raw.split(",") if d.strip()]
```

Also add `import os` at the top (check if already present, it's not currently imported in unifi-wifi.py).

**Step 3: Handle bare roaming in dispatch**

At the roaming dispatch block, change:

```python
    elif args.cmd == "roaming":
        if args.query:
            cmd_roaming(s, args.query, num_sessions=args.sessions)
        else:
            devices = watched_devices()
            if not devices:
                print("  No query given and UNIFI_WATCHED_DEVICES not set in .env")
                print("  Usage: unifi-wifi roaming <hostname>")
                sys.exit(1)
            for device in devices:
                cmd_roaming(s, device, num_sessions=args.sessions)
```

**Step 4: Test**

Run: `just unifi-wifi roaming`
Expected: Roaming history for both iPickleX-2 and raisynglsiPhone (1 session each by default).

Run: `just unifi-wifi roaming iPickleX-2 --sessions 3`
Expected: Same single-device behavior as before.

**Step 5: Commit**

```bash
git add network/unifi-wifi.py
git commit -m "feat: bare roaming command shows all watched devices from env"
```

---

### Task 5: Add `checkup` composite command

**Files:**
- Modify: `network/unifi-wifi.py` (new `cmd_checkup` function + argparse + dispatch)

**Step 1: Add the `cmd_checkup` function**

Add before `main()` (around line 646):

```python
def cmd_checkup(s, num_sessions=1):
    """Composite network health check: AP retries, RF neighbors, watched device roaming."""
    # 1. AP overview: sorted by worst retries
    cmd_aps(s, sort_by="retries")

    # 2. RF scan summary: channel congestion only
    cmd_rfscan(s, fresh_minutes=60, summary_only=True)

    # 3. Roaming for watched devices
    devices = watched_devices()
    if devices:
        section("Roaming: Watched Devices")
        # Remove the extra section header that cmd_roaming prints by calling it directly
        for device in devices:
            cmd_roaming(s, device, num_sessions=num_sessions)
    else:
        print("\n  (UNIFI_WATCHED_DEVICES not set, skipping roaming section)")
```

**Step 2: Add argparse subcommand**

After the existing `sub.add_parser` lines, add:

```python
p_chk = sub.add_parser("checkup", help="Network health: AP retries + RF neighbors + watched device roaming")
p_chk.add_argument("--sessions", type=int, default=1, metavar="N", help="Roaming sessions per device (default: 1)")
```

**Step 3: Add dispatch**

```python
    elif args.cmd == "checkup":
        cmd_checkup(s, num_sessions=args.sessions)
```

**Step 4: Test**

Run: `just unifi-wifi checkup`
Expected: Three sections printed in order:
1. AP radio stats sorted by retry rate
2. RF scan channel congestion summary (last 60 min)
3. Roaming history for each watched device (1 session each)

Run: `just unifi-wifi checkup --sessions 3`
Expected: Same but with 3 roaming sessions per device.

**Step 5: Commit**

```bash
git add network/unifi-wifi.py
git commit -m "feat: add checkup command, composite network health overview"
```

---

### Task 6: Update documentation

**Files:**
- Modify: `network/CLAUDE.md`

**Step 1: Add new commands to CLAUDE.md**

In the `unifi-wifi.py` command reference, add the new commands/flags:

```bash
just unifi-wifi checkup                      # composite: AP retries + RF neighbors + watched device roaming
just unifi-wifi checkup --sessions 3         # with more roaming history per device
just unifi-wifi aps --sort retries           # sort APs by worst retry rate
just unifi-wifi aps --sort utilization       # sort APs by channel utilization
just unifi-wifi rfscan --summary             # channel congestion only, skip full neighbor list
just unifi-wifi roaming                      # roaming history for all watched devices (from .env)
```

Update the "Common diagnostic workflows" section:

```
- "Quick network health check?" → `checkup` (runs aps + rfscan summary + watched device roaming)
```

**Step 2: Commit**

```bash
git add network/CLAUDE.md
git commit -m "docs: add checkup, --summary, --sort, bare roaming to CLAUDE.md"
```
