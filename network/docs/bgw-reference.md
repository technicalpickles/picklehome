# AT&T BGW320 Reference

AT&T fiber gateway at `http://192.168.8.254`. Double-NAT, not in IP passthrough mode. USG gets `192.168.8.65` via DHCP.

## Hardware

Captured 2026-03-18 via `http://192.168.8.254/cgi-bin/sysinfo.ha`.

| Field | Value |
|---|---|
| Manufacturer | HUMAX |
| Model | BGW320-500 |
| Hardware Version | 02001F00460050 |
| Software Version | 6.34.7 |
| Serial Number | D93LD4GJ303300 |
| WAN MAC | `bc:9a:8e:ed:fe:e0` |
| First Use Date | 2024-11-19 |

WiFi BSSIDs follow base MAC pattern: `e0` → `e4` (2.4GHz home), `e8`/`ec` (5GHz home/guest).

**SFP / Fiber module** (from `just bgw fiber`):

| Field | Value |
|---|---|
| Vendor | NOKIA |
| Part Number | 3FE46899AB |
| Serial Number | ALCLEC158B58 |
| Date Code | 240530 (May 2024) |

## Access Model

Two tiers of access:

| Tier | Auth required | Use for |
|---|---|---|
| Status pages | None | Read-only diagnostics: fiber, broadband, WiFi state, device list |
| Config pages | BGW access code (device label) + cookies | Changing WiFi, firewall, etc. |

Config pages redirect to a login page if no valid session cookie is present. `requests` alone won't work for these; use Playwright to handle the login flow.

Status pages are freely accessible with a plain GET.

## CGI Endpoints

All pages are at `http://192.168.8.254/cgi-bin/<page>.ha`.

### Status (no auth)

| Page | Description |
|---|---|
| `home.ha` | Overview: broadband status, WiFi radio state, connected devices |
| `broadbandstatistics.ha` | WAN connection details (used by `bgw.py broadband`) |
| `fiberstat.ha` | Optical fiber signal / SFP metrics (used by `bgw.py fiber`) |
| `lanstatistics.ha` | LAN port statistics |
| `sysinfo.ha` | Device info, firmware version, uptime |
| `devices.ha` | Known device list |
| `diag.ha` | Diagnostics UI: ping, traceroute, nslookup from BGW WAN |

### Config (requires auth)

| Page | Description |
|---|---|
| `wconfig_unified.ha` | WiFi configuration: SSID, password, band enable/disable |
| `firewall.ha` | Firewall rules |
| `remoteaccess.ha` | Remote access settings |
| `routerpasswd.ha` | Change BGW access code |
| `apphosting.ha` | Application hosting / port forwarding |

### Restart actions (require auth)

`wrestart.ha`, `vrestart.ha`, `crestart.ha`, `restart.ha`

## home.ha: WiFi Status Fields

`home.ha` renders WiFi state without auth. Scrape with Playwright (the page uses JavaScript to render some sections). Key fields visible in page text:

```
2.4 GHz Frequency Status    Enabled / Disabled
  Network Name (SSID)       <ssid>
  Type                      Home / Guest
  Status                    Enabled / Disabled
  Authentication Type       WPA-2 / Disabled

5 GHz Frequency Status      Enabled / Disabled
  (same sub-fields)
```

Also shows a device list of previously-connected WiFi clients (status on/off, connection type, frequency band). Useful for confirming the BGW WiFi is actually off after disabling it.

### Example scrape (Playwright)

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("http://192.168.8.254/cgi-bin/home.ha")
    page.wait_for_load_state("networkidle")
    text = page.inner_text("body")
    browser.close()
# Parse "2.4 GHz Frequency Status" and "5 GHz Frequency Status" from text
```

## bgw.py Integration

`bgw.py` uses plain `requests` for status pages (fast, no browser). Playwright is only used for `diag.ha` commands (trace, ping, nslookup) which stream output progressively into a textarea.

For `home.ha` WiFi status, Playwright is needed even for read-only access because the page uses JavaScript rendering.

The `session()` pattern in `bgw.py`:
```python
BGW = "http://192.168.8.254"
SESSION = requests.Session()

def get(path, **kwargs):
    return SESSION.get(f"{BGW}/cgi-bin/{path}", timeout=10, **kwargs)
```

## WiFi State

**2026-03-17: Both bands disabled** via `wconfig_unified.ha` in browser. Confirmed off with `just bgw wifi`.

Was broadcasting `ATTt6kgiKH` on 2.4GHz ch 11 (-32 dBm at nearest AP) and 5GHz ch 48 (-13 dBm), directly interfering with our APs. All home devices connect via UniFi APs; BGW WiFi was redundant.

Check `just bgw wifi` to confirm still disabled. Check `just unifi wifi rfscan` to confirm gone from neighbor scan (rfscan data is passive/cached; allow ~15 min after change for APs to rescan).
