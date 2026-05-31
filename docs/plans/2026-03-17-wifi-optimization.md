# WiFi Optimization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Disable redundant AT&T BGW WiFi radio, re-scan to validate channel plan, then add read-only BGW WiFi status to `bgw.py`.

**Architecture:** The BGW at 192.168.8.254 has its own WiFi radio which is redundant (all devices use UniFi APs). Its 2.4GHz broadcast on ch 1 at -11 dBm is the strongest interferer on that channel, directly impacting Josh Office and Tracy Office APs. Disabling it removes the interference, then we re-evaluate the 2.4GHz channel plan. The BGW exposes WiFi config via CGI endpoints (`.ha` pages) at `http://192.168.8.254/cgi-bin/`. We'll add a read-only `wifi` subcommand to `bgw.py` to surface that state.

**Tech Stack:** Python, `requests`, `bgw.py` CGI scraping pattern (same as `fiber`/`broadband` commands)

## BGW Access Model (from exploration 2026-03-17)

The BGW exposes two tiers:
- **`home.ha`:** no auth required. Shows WiFi radio status, SSID names, enabled/disabled state, device list. Use this for read-only `bgw.py wifi`.
- **`wconfig_unified.ha`:** requires BGW access code (device label password, cookies needed). Use for any future config changes.

Known CGI endpoints (from `home.ha` nav):
```
apphosting.ha, broadbandstatistics.ha, crestart.ha, devices.ha, diag.ha,
firewall.ha, home.ha, lanstatistics.ha, remoteaccess.ha, restart.ha,
routerpasswd.ha, sitemap.ha, sysinfo.ha, voice.ha, vrestart.ha,
wconfig_unified.ha, wrestart.ha
```

WiFi status fields available in `home.ha` (no auth):
- `2.4 GHz Frequency Status` → `Enabled` / `Disabled`
- `5 GHz Frequency Status` → `Enabled` / `Disabled`
- Per-network: SSID, Type (Home/Guest), Status (Enabled/Disabled), Auth Type
- Device list with connection type and frequency

**Note:** Add dedicated BGW docs to `network/CLAUDE.md` or a new `network/bgw-reference.md` covering these endpoints and the auth model.

---

## Current Channel State (as of 2026-03-17)

### 5GHz
| AP | Channel | Neighbors | Notes |
|---|---|---|---|
| Josh Office | 40 | 13 / -81 dBm | Clean |
| Tracy Office | 44 | 75 / -70 dBm | Noisy, no better non-DFS option |
| Porch | 48 | 36 / **-12 dBm** | Strong new neighbor appeared overnight |
| Living Room | 149 | 24 / -80 dBm | Moved yesterday; neighbors distant |
| Upstairs | 157 | 18 / -73 dBm | Acceptable |

### 2.4GHz
| AP | Channel | Notes |
|---|---|---|
| Josh Office | 1 | ATTt6kgiKH at **-11 dBm** (our own BGW) |
| Tracy Office | 1 | Same interference (moved from ch 11 yesterday) |
| Living Room | 6 | Improved overnight (-9 → -63 dBm strongest) |
| Porch | 11 | 183 neighbors, strongest -35 dBm |

---

## Task 1: Disable BGW WiFi (manual)

**Files:** None: web UI only

**Step 1: Open BGW admin UI**

Navigate to `http://192.168.8.254` in a browser on the LAN.

**Step 2: Disable WiFi radios**

Home Network → Wi-Fi (or similar, BGW UI varies by firmware):
- Turn off **2.4 GHz** radio
- Turn off **5 GHz** radio (if present)
- Save / Apply

**Step 3: Verify it's gone from RF scan**

```bash
uv run --with requests --with python-dotenv network/unifi-wifi.py rfscan
```

Expected: `ATTt6kgiKH` no longer appears in 2.4 GHz neighbors. Ch 1 strongest neighbor should drop from -11 dBm to something much weaker.

---

## Task 2: Re-evaluate 2.4GHz channel plan post-BGW-disable

**Files:** None: observation only

**Step 1: Run AP stats to see current retries/satisfaction**

```bash
uv run --with requests --with python-dotenv network/unifi-wifi.py aps
```

**Step 2: Compare ch 1 strongest neighbor**

With the BGW gone, ch 1 was previously at -66 dBm strongest (before ATT appeared). If ch 1 is now cleaner than ch 6 (currently -63 dBm strongest), no changes needed.

If ch 6 is now clearly the cleanest of the three non-overlapping options, consider:
- Move Tracy Office 2.4GHz back to ch 6... but Living Room is already on ch 6. Avoid co-channel with your own APs.
- The 1/6/11 assignment across 4 APs means one pair always shares. Current pairing (Josh+Tracy on 1, LivingRoom on 6, Porch on 11) is fine if ch 1 clears up.

**Decision point:** Only change channels if the new scan reveals a materially better option.

---

## Task 3: Explore BGW WiFi CGI endpoint ✓ DONE

**Findings:** `home.ha` is the right endpoint: no auth, shows WiFi radio status directly. The HTML structure differs from `fiber`/`broadband` (uses free-form text/table, not strict `<th><td>` pairs). Use Playwright to render and scrape the visible text. See BGW Access Model section above.

---

## Task 4: Add `bgw.py wifi` subcommand (read-only)

**Files:**
- Modify: `network/bgw.py`
- Update: `network/CLAUDE.md` (add wifi command docs)

**Step 1: Add `cmd_wifi()` function**

Follow the same pattern as `cmd_fiber()`: fetch the CGI page, parse fields, print structured output. Fields to surface:
- 2.4 GHz radio: enabled/disabled, SSID, channel, tx power (if available)
- 5 GHz radio: same
- Any guest network state

Example structure (adjust field names from Task 3 findings):

```python
def cmd_wifi():
    r = get("wificonfiguration.ha")  # confirm endpoint in Task 3
    html = r.text
    pairs = parse_table_pairs(html)

    for band in ("2.4 GHz", "5 GHz"):
        print(f"\n{band}")
        print("─" * 40)
        for key in ["Radio", "SSID", "Channel", "Security"]:
            full_key = f"{band} {key}"  # adjust to actual field names
            if full_key in pairs:
                print(f"  {key:<20} {pairs[full_key]}")
```

**Step 2: Wire into argparse**

```python
sub.add_parser("wifi", help="BGW WiFi radio status (read-only)")
```

And in `main()`:
```python
elif args.cmd == "wifi":
    cmd_wifi()
```

**Step 3: Add to Justfile**

Check `Justfile` for existing `bgw-*` tasks and add:
```just
bgw-wifi:
    uv run --with requests network/bgw.py wifi
```

**Step 4: Test**

```bash
just bgw-wifi
# or:
uv run --with requests network/bgw.py wifi
```

Expected: prints BGW WiFi radio state, useful to confirm the radio is actually disabled after Task 1.

**Step 5: Update CLAUDE.md**

Add `wifi` to the `bgw.py` command list in `network/CLAUDE.md`.

---

## Task 5: Post-optimization RF re-scan and channel review

**Files:** None: observation only

After BGW WiFi is disabled and `bgw.py wifi` confirms it, run a full re-scan:

```bash
uv run --with requests --with python-dotenv network/unifi-wifi.py rfscan
uv run --with requests --with python-dotenv network/unifi-wifi.py aps
uv run --with requests --with python-dotenv network/unifi-wifi.py clients
```

Review:
- Has ch 1 2.4GHz interference dropped? Check Josh Office and Tracy Office retries.
- Porch 5GHz ch 48 (-12 dBm neighbor): if still present, consider moving Porch to a DFS channel or accept it (Porch has 0–1 clients typically).
- Living Room 5GHz ch 149: 24 neighbors at -80 dBm is distant, likely fine.
- Check satisfaction scores across all APs vs. pre-optimization baseline.

---

## Open Questions

- **Porch 5GHz ch 48 strong neighbor (-12 dBm):** Appeared overnight. May be a neighbor's newly placed router. Worth monitoring. If it persists, DFS is more justified for Porch (it has few clients and is outdoors, less disruptive if radar kicks it).
- **Tracy Office 5GHz ch 44 (75 neighbors):** No better non-DFS option. Satisfaction 99, so leave it unless it degrades.
- **`connect` device identity:** 4 Google-OUI devices named "connect": 1 confirmed outdoor camera (Living Room AP), other 3 unknown. Low traffic suggests not cameras. Identify by cross-referencing UniFi DHCP history or physically checking IPs.
