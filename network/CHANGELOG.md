# Network Changelog

Changes to network configuration, with rationale and follow-up checks.
Most recent first. Use `just unifi-wifi config` and `just bgw wifi` to inspect current state.

## Follow-up

- [ ] **2.4 GHz power reduction verification**: `just unifi-wifi checkup` after 24h. Compare
  retry rates to pre-change baseline (Living Room was 25-33%, Upstairs was 33%). Also verify
  no IoT devices dropped off (check 2.4 GHz client counts on both APs).
- [ ] **Roaming recheck after ch 48 move**: `just unifi-wifi roaming raisynglsiPhone --sessions 3`
  after a day or two. Expect fewer segments and less Tracy ↔ Josh ↔ Upstairs cycling.
  Prior check (2026-03-20, before ch 48 move): improved from 11-segment baseline but
  still bouncy (5 segments/25 min in worst session). Ch 48 move should help further.
- [ ] **Relocate Porch AP**: currently offline in Josh's office (co-located with Josh Office AP);
  move to a useful location. See `docs/outdoor-wifi-research.md` for options.
  **Note:** When Porch comes back on ch 11, will conflict with Upstairs (now ch 11).
  Re-plan 2.4 GHz channel assignments at that point.
- [ ] **Ch 149 neighbor density**: 30 neighbors (strongest -79 dBm) vs ch 40 (17) and
  ch 157 (12). Currently 2% utilization so not a problem. Recheck if Living Room clients
  show persistent high retries.
- [ ] **UAPSD off on all SSIDs**: low priority; may help iPhone PSM behavior but
  Ubiquiti's own compatibility guide recommends off. Revisit only if iPhone PSM issues resurface.

### Resolved

- [x] ~~**Min RSSI `enabled=True` with no value on main SSID**~~: 2026-03-20: display bug
  in `unifi-wifi.py config` (was reading `minrate_na_enabled`). Min RSSI not configured. Fixed.
- [x] ~~**BGW WiFi beaconing despite Disabled**~~: 2026-03-20: resolved without factory reset.
  No trace of SSID or BSSID in RF scan.
- [x] ~~**5GHz TX power reduction verification**~~: 2026-03-20: all radios confirmed mode=medium.
- [x] ~~**Ch 48 clean after BGW disable**~~: 2026-03-20: zero neighbors on ch 48 in RF scan.

---

## 2026-03-21

### Moved Upstairs AC HD 2.4GHz: ch 6 → ch 11

**What:** `just unifi-wifi set-channel "upstairs" 2.4 11 --yes`

**Why:** Living Room AC LR and Upstairs AC HD were both on 2.4 GHz ch 6, one floor apart
with an open stairwell between them: co-channel interference. Each AP's transmissions
consumed the other's airtime (30% RX utilization on Living Room). Ch 11 was available
since Porch AP is offline.

**Immediate result:** Upstairs retries dropped from 33% to 0%, RX utilization from ~20% to 0%.

**Verify:**
- [x] Config confirms ch 11 (verified via `just unifi-wifi aps`)

### Reduced 2.4GHz transmit power: max → medium on Living Room + Upstairs

**What:**
```
just unifi-wifi set-power "living" 2.4 medium --yes
just unifi-wifi set-power "upstairs" 2.4 medium --yes
```

**Why:** Research confirmed the original "leave 2.4 GHz at max" decision (2026-03-17) was
overcautious for these two APs. The AC-LR's high-gain antenna at 17 dBm was pushing signal
through the open stairwell into the Upstairs AP's zone, and the AC-HD at 19 dBm was blasting
back down. All 2.4 GHz clients had strong signal (well above -70 dBm), so medium provides
adequate coverage. Reducing power also addresses the near-far problem with low-power IoT
devices (ESP8266, smart plugs transmit at ~10-12 dBm).

See `docs/24ghz-power-tuning.md` for full research findings.

**Before → After:**

| AP | Before | After (est.) | Max |
|---|---|---|---|
| Living Room AC LR | 17 dBm | ~13 dBm | 24 dBm |
| Upstairs AC HD | 19 dBm | ~16 dBm | 25 dBm |

Office APs (AC Pro, 15 dBm max=22) left unchanged: already lower power, serve distinct zones.

**Verify:**
- [ ] `just unifi-wifi checkup` after 24h: retry rates should be lower, no IoT dropouts

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
- [ ] `just unifi-wifi roaming raisynglsiPhone --sessions 3` after a day or two:
  expect fewer segments and less Tracy ↔ Josh ↔ Upstairs cycling

---

## 2026-03-19

### Moved Tracy Office 5GHz: ch 44 → ch 40

**What:** `just unifi-wifi set-channel "tracy" 5 40 --yes`

**Why:** Ch 44 had 54 neighbors (strongest -54 dBm). Ch 40 is the cleanest 5GHz channel
(16 neighbors, all ≤ -88 dBm excluding stale BGW entries). Josh Office is also on ch 40
but they're on opposite sides of the house, so co-channel is not a concern.

**Verify:**
- [x] Config and live stats both show ch 40 (confirmed via `/stat/device`)

### BGW WiFi confirmed not beaconing

**What:** `just unifi-wifi rfscan --fresh 30`: no `ATTt6kgiKH` entries in the last 30 min.

**Why:** Follow-up to the 2026-03-18 finding that BGW continued beaconing despite UI showing
Disabled. All BGW entries in the full rfscan are now 13+ hours old (stale cache). The disable
is holding: no factory reset needed.

---

## 2026-03-17

### Disabled BGW WiFi (both bands)

**What:** Turned off 2.4 GHz and 5 GHz radios on AT&T BGW gateway via browser at
`http://192.168.8.254/cgi-bin/wconfig_unified.ha`.

**Why:** BGW was broadcasting `ATTt6kgiKH` and appearing as a strong neighbor on our
APs: -32 dBm on 2.4GHz ch 11 and -13 dBm on 5GHz ch 48. All home devices connect
via UniFi APs; BGW WiFi is redundant.

**Verify:**
- [x] `just bgw wifi`: both bands show Disabled ✓ (confirmed 2026-03-18)
- [x] `just unifi-wifi rfscan`: `ATTt6kgiKH` gone ✓ (confirmed 2026-03-20, no SSID or BSSID in scan)

**2026-03-18 follow-up:** BGW UI shows both bands Disabled, but `ATTt6kgiKH`
(BSSID `bc:9a:8e:ed:fe:ec`, base MAC `bc:9a:8e:ed:fe:e0`) continued beaconing
on 5GHz ch 149 at -50 dBm, confirmed via `just unifi-wifi rfscan --fresh 5`
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
segments across 5 APs in ~1 hour, consistent with a phone constantly re-scoring
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

2.4GHz left at max: lower frequency penetrates walls better; reducing risks dead spots.

**Verify:**
- [x] `just unifi-wifi config`: all 5GHz radios show mode=medium ✓ (confirmed 2026-03-20)
- [x] `just unifi-wifi roaming raisynglsiPhone --sessions 3`: improved but mixed (2026-03-20):
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
- [x] `just unifi-wifi rfscan`: ch 48 confirmed clean (zero neighbors, 2026-03-20)

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

