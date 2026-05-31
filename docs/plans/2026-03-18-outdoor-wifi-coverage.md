# Outdoor WiFi Coverage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish reliable WiFi coverage in the backyard past the cinderblock wall, without
interfering with indoor APs or causing sticky-client problems indoors.

**Architecture:** Two-phase approach. Phase 1 tests the existing U7LR (Porch AC LR) with correct
physical placement and conservative radio config. A decision gate determines whether U7LR is
sufficient or the U7 Outdoor hardware is needed. Phase 2 finalizes config and documents the
settled state. No new code required for Phase 1; Phase 2 may add a CHANGELOG entry and
update network/CLAUDE.md.

**Reference:** `network/docs/outdoor-wifi-research.md`: full hardware comparison, antenna
orientation guidance, TX power trade-offs, and measurement protocol.

**Tech Stack:** UniFi CloudKey legacy API, `just unifi-wifi` CLI, `just wifi-diag`

---

## Phase 1: Test with U7LR

### Task 1: Capture baseline config and client associations

Before touching anything, record current state so you have a clean before/after.

**Step 1: Record current AP radio config**

```bash
just unifi-wifi aps
```

Copy output to a scratch file or note. Key fields: channel, TX power, client counts for
Porch AC LR and Josh Office AC Pro.

**Step 2: Record which clients are currently on Porch AP**

```bash
just unifi-wifi clients
```

Note any clients associated to "Porch AC LR". These are currently on an indoor AP and
may roam once it moves.

**Step 3: Commit nothing yet.** This is just a snapshot.

---

### Task 2: Physically remount U7LR correctly

**Current state:** U7LR is mounted vertically on exterior wall (protruding 90°, wrong orientation).

**Correct orientation for wall mount:**
- Mount flat against the exterior wall like a picture frame, face pointing outward toward the backyard
- Antennas stay in their designed vertical orientation
- Main signal lobe projects into the yard, not sideways along the wall

**If testing the high soffit point instead:**
- Mount in normal ceiling-mount orientation (face down), elevated as high as possible under the eave
- This radiates over the cinderblock rather than into it
- Requires a temporary patch cable / PoE injector since it's not wired. Do this only if wall-mount results are poor

No config changes yet. Just get the physical placement right first.

---

### Task 3: Apply starting radio configuration

See `network/docs/outdoor-wifi-research.md` → "Starting Radio Configuration" for rationale.

**Step 1: Set Porch AP 2.4 GHz channel and power**

```bash
just unifi-wifi set-channel porch 2.4 11
just unifi-wifi set-power porch 2.4 low
```

**Step 2: Set Porch AP 5 GHz channel and power**

```bash
just unifi-wifi set-channel porch 5 149
just unifi-wifi set-power porch 5 medium
```

**Step 3: Verify**

```bash
just unifi-wifi aps
```

Confirm Porch shows: 2.4 ch 11 / Low, 5 GHz ch 149 / Medium.
Josh Office should remain: 2.4 ch 1, 5 GHz ch 40 (unchanged).

**Step 4: Enable band steering**

In UniFi Network UI: Devices → Porch AC LR → Config → Radios → enable Band Steering.
(Not yet exposed in the CLI tools.)

Do NOT enable Minimum RSSI or Roaming Assistant yet.

---

### Task 4: Run measurement sweep

Run `wifi-diag.py` from a laptop at each of the following fixed spots. Log the output
for each location. Do not average or summarize in your head, keep the raw output.

**Test spots (in order):**
1. Inside the room adjacent to the porch (Josh Office side)
2. Screened porch center
3. Just past the cinderblock wall (near-yard)
4. Mid-yard
5. Far yard / Sonos area

**At each spot:**

```bash
just wifi-diag --no-trace --no-speed
```

For spots 4 and 5, also run with speed test to get real throughput:

```bash
just wifi-diag
```

**Key metrics to record per spot:**
- Which AP and band the client chose (BSSID → AP name)
- RSSI (dBm)
- SNR
- Channel
- Download speed (spots 4–5)

---

### Task 5: Evaluate against decision gate

Compare results to thresholds from `network/docs/outdoor-wifi-research.md`.

**U7LR is working if:**
- Spots 1–2 (indoor/porch): client is on Josh Office or Porch, RSSI ≥ -65 dBm
- Spot 3 (near-yard): RSSI ≥ -65 dBm on 5 GHz
- Spots 4–5 (mid/far yard): RSSI ≥ -70 dBm; 5 GHz usable (not just 2.4 fallback)
- Indoor clients in Josh Office room are NOT preferring Porch AP

**Buy U7 Outdoor if ANY of these are true:**
- Mid-yard RSSI < -70 dBm
- 5 GHz unusable in yard (clients fall back to 2.4 GHz only at spots 3–5)
- Indoor clients near Josh Office keep associating to Porch AP at full TX
- RSSI looks OK but throughput is poor / retries are high (uplink geometry problem)

---

## Phase 2A: U7LR passes, finalize and document

### Task 6: Final config cleanup

If U7LR results are acceptable:

**Step 1: Verify Sonos**

Check whether Sonos is hardwired or WiFi:

```bash
just unifi-wifi clients
```

If it appears in WiFi clients list, note which AP and signal quality. If hardwired, ignore.

**Step 2: Evaluate whether to add roaming controls**

Only if indoor clients are occasionally sticking to Porch AP:

```bash
# Enable Roaming Assistant in UniFi UI:
# Devices → Porch AC LR → Config → Radios → Roaming Assistant → enable, threshold -70 dBm
```

Do not add Minimum RSSI unless Roaming Assistant is insufficient.

**Step 3: Document final config in CHANGELOG**

Add an entry to `network/CHANGELOG.md` (create if it doesn't exist):

```markdown
## 2026-03-18: Outdoor WiFi: Porch AC LR remounted and reconfigured

- Discovered Porch AC LR was physically inside Josh Office the entire time
- Remounted on exterior wall in correct flat orientation (face toward backyard)
- Channel: 2.4 GHz ch 11 / 5 GHz ch 149
- TX power: 2.4 Low / 5 Medium
- Band steering enabled
- Result: [paste key RSSI numbers from measurement sweep]
- Decision: U7LR sufficient / upgrading to U7 Outdoor [delete as appropriate]
```

**Step 4: Update network/CLAUDE.md**

Add a note under the `unifi-wifi.py` section that Porch AC LR covers the backyard
and link to the research doc.

**Step 5: Commit**

```bash
git add network/CHANGELOG.md network/CLAUDE.md
git commit -m "docs: document outdoor wifi config, Porch AC LR remounted + reconfigured"
```

---

## Phase 2B: U7LR fails decision gate, upgrade to U7 Outdoor

### Task 7: Hardware upgrade path

**Step 1: Order U7 Outdoor**

UniFi U7 Outdoor (model UWO). IPX6, directional antennas (12.5 dBi / 5 GHz).

**Step 2: Choose mount location**

Options in order of preference:
1. Same wired exterior wall location, flat-mounted (same cable run, no new wiring)
2. High soffit/eave point: requires running ethernet (better geometry for over-wall coverage)

**Step 3: Configure same starting radio settings**

Same as Task 3 above (ch 11 / ch 149, Low/Medium power, band steering).

**Step 4: Re-run measurement sweep**

Repeat Task 4 with the U7 Outdoor in place. Compare against U7LR baseline.

**Step 5: Document in CHANGELOG and commit**

Same as Task 6 Steps 3–5, noting the hardware change.

---

## Notes

- Historical Porch AP data (roaming history, client associations, signal logs) is unreliable.
  The AP was inside the office, not covering the porch. Disregard it.
- The screened porch high-mount point is not wired. If testing it requires a long patch cable
  run, do that only as a last step before deciding on hardware upgrade.
- 40 MHz on 2.4 GHz is explicitly not recommended (Cisco/Ubiquiti guidance). Stay at 20 MHz.
- Do not enable Minimum RSSI until Roaming Assistant has been tried first.
