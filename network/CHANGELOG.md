# Network Changelog

Changes to network configuration, with rationale and follow-up checks.
Most recent first. Use `just unifi-wifi config` and `just bgw wifi` to inspect current state.

---

## 2026-03-20

### Moved Tracy Office 5GHz: ch 40 → ch 48

**What:** `just unifi-wifi set-channel "tracy" 5 48 --yes`

**Why:** Tracy's iPhone was bouncing rapidly between Tracy Office, Josh Office, and
Upstairs APs from the upstairs bathroom (physically above Josh's office). Both offices
were on ch 40, making them hard for the phone to distinguish. Ch 48 is completely clean
(zero neighbors in RF scan) now that the BGW stopped beaconing on it. This gives three
distinct channels from the bathroom: ch 40 (Josh), ch 48 (Tracy), ch 157 (Upstairs).

**Verify:**
- [x] Config and live stats both show ch 48 (confirmed via `/stat/device`)
- [ ] `just unifi-wifi roaming raisynglsiPhone --sessions 3` after a day or two —
  expect fewer segments and less Tracy ↔ Josh ↔ Upstairs cycling

---

## 2026-03-19

### Moved Tracy Office 5GHz: ch 44 → ch 40

**What:** `just unifi-wifi set-channel "tracy" 5 40 --yes`

**Why:** Ch 44 had 54 neighbors (strongest -54 dBm). Ch 40 is the cleanest 5GHz channel
(16 neighbors, all ≤ -88 dBm excluding stale BGW entries). Josh Office is also on ch 40
but they're on opposite sides of the house — co-channel is not a concern.

**Verify:**
- [x] Config and live stats both show ch 40 (confirmed via `/stat/device`)

### BGW WiFi confirmed not beaconing

**What:** `just unifi-wifi rfscan --fresh 30` — no `ATTt6kgiKH` entries in the last 30 min.

**Why:** Follow-up to the 2026-03-18 finding that BGW continued beaconing despite UI showing
Disabled. All BGW entries in the full rfscan are now 13+ hours old (stale cache). The disable
is holding — no factory reset needed.

---

## 2026-03-17

### Disabled BGW WiFi (both bands)

**What:** Turned off 2.4 GHz and 5 GHz radios on AT&T BGW gateway via browser at
`http://192.168.8.254/cgi-bin/wconfig_unified.ha`.

**Why:** BGW was broadcasting `ATTt6kgiKH` and appearing as a strong neighbor on our
APs — -32 dBm on 2.4GHz ch 11 and -13 dBm on 5GHz ch 48. All home devices connect
via UniFi APs; BGW WiFi is redundant.

**Verify:**
- [x] `just bgw wifi` — both bands show Disabled ✓ (confirmed 2026-03-18)
- [x] `just unifi-wifi rfscan` — `ATTt6kgiKH` gone ✓ (confirmed 2026-03-20, no SSID or BSSID in scan)

**2026-03-18 follow-up:** BGW UI shows both bands Disabled, but `ATTt6kgiKH`
(BSSID `bc:9a:8e:ed:fe:ec`, base MAC `bc:9a:8e:ed:fe:e0`) continued beaconing
on 5GHz ch 149 at -50 dBm — confirmed via `just unifi-wifi rfscan --fresh 5`
both before and after a BGW restart. Channel also shifted from ch 48 → ch 149,
suggesting the radio is still active and running auto channel selection despite
the UI reporting Disabled. Likely a firmware bug or AT&T remote management
overriding the setting. Next step: factory reset, re-disable WiFi, re-verify.

**2026-03-20 follow-up:** Resolved without factory reset. RF scan shows no
`ATTt6kgiKH` SSID and no `bc:9a:8e:ed:fe:ec` BSSID on any channel. The disable
eventually took effect (possibly after the BGW restart propagated).

---

### Reduced 5GHz transmit power: max → medium on all APs

**What:** `just unifi-wifi set-power all 5 medium --yes`

**Why:** All 5GHz radios were at or near max power (22–25 dBm), creating heavy cell
overlap. iPhone roaming analysis (Tracy's phone, `raisynglsiPhone`) showed 11 AP-roam
segments across 5 APs in ~1 hour — consistent with a phone constantly re-scoring
overlapping candidates. Research confirmed over-powered APs are a primary cause of
roaming churn.

**Before → After:**

| AP | Before | After | Max |
|---|---|---|---|
| Josh Office AC Pro | 22 dBm | 14 dBm | 22 dBm |
| Living Room AC LR | 22 dBm | 13 dBm | 22 dBm |
| Tracy Office AC Pro | 22 dBm | 14 dBm | 22 dBm |
| Upstairs AC HD | 25 dBm | 16 dBm | 25 dBm |
| Porch AC LR | 19 dBm | 13 dBm | 22 dBm |

2.4GHz left at max — lower frequency penetrates walls better; reducing risks dead spots.

**Verify:**
- [x] `just unifi-wifi config` — all 5GHz radios show mode=medium ✓ (confirmed 2026-03-20)
- [x] `just unifi-wifi roaming raisynglsiPhone --sessions 3` — improved but mixed (2026-03-20):
  session 1 had 5 segments/25 min (Tracy ↔ Upstairs indecision), session 2 was clean
  (2 segments/1.5h). Better than the 11-segment baseline. See Open/Pending for follow-up.

---

## 2026-03-16

### Moved Porch AC LR 5GHz: ch 44 → ch 48

**What:** `just unifi-wifi set-channel "porch" 5 48 --yes`

**Why:** RF scan showed ch 44 had 76 external neighbors (strongest -73 dBm). Ch 48
had 23 neighbors at the time, all weaker. Ch 40 was cleanest overall but conflicts
with Josh Office.

**Note:** BGW was later found to be on ch 48 at -13 dBm. Now that BGW WiFi is
disabled, ch 48 should be cleaner. Verify with rfscan after BGW clears.

**Verify:**
- [ ] `just unifi-wifi rfscan` after BGW clears — confirm ch 48 cleaner than ch 44

---

### Moved Living Room AC LR 5GHz: ch 157 → ch 149

**What:** `just unifi-wifi set-channel "living" 5 149 --yes`

**Why:** Living Room and Upstairs AC HD were both on ch 157, creating co-channel
interference between our own APs. Ch 149 had 40 external neighbors but all distant
(-80 dBm), making it a better choice than competing with Upstairs.

**Verify:**
- [x] Living Room confirmed on ch 149 in live stats

---

### Moved Tracy Office AC Pro 2.4GHz: ch 11 → ch 1

**What:** `just unifi-wifi set-channel "tracy" 2.4 1 --yes`

**Why:** Tracy Office and Porch were both on ch 11. Moving Tracy to ch 1 (shared
with Josh Office, physically separated by house) reduces co-channel between adjacent
APs. Josh Office is on the far side of the house from Tracy Office, so ch 1 sharing
is acceptable.

**Verify:**
- [x] Tracy Office confirmed on ch 1 in live stats

---

## Open / Pending

- **UAPSD off on all SSIDs** — low priority; may help iPhone PSM behavior but
  Ubiquiti's own compatibility guide recommends off; revisit after tx power change settles
- **Relocate Porch AP** — currently offline in Josh's office (co-located with Josh Office AP);
  move to a useful location. See `docs/outdoor-wifi-research.md` for options.
- **Roaming still bouncy for raisynglsiPhone** — 2026-03-20 check: session 1 had
  5 segments/3 APs in 25 min (Tracy Office ↔ Upstairs indecision), but session 2
  was clean (2 segments in 1.5h). Improved from the 11-segment baseline on 2026-03-17
  but not fully settled. Monitor over the next few days.
- **Ch 149 has moderate neighbor density** — 30 neighbors (strongest -79 dBm) vs
  ch 40 (17, -86 dBm) and ch 157 (12, -70 dBm). Not alarming but worth rechecking
  if Living Room clients show persistent high retries.

## Resolved

- ~~**Min RSSI `enabled=True` with no value on main SSID**~~ — 2026-03-20: this was
  a display bug in `unifi-wifi.py config`. The code was reading `minrate_na_enabled`
  (minimum data rate) instead of `minrssi_enabled`. Min RSSI is not configured (keys
  absent from API). Min data rate at 6 Mbps is a harmless default. Bug fixed.
