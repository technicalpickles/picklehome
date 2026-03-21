# iOS + UniFi WiFi Behavior Reference

Research notes on how iPhones behave on a UniFi AC-generation network, with
implications for diagnosing slow/dropped connections and roaming issues.

Sources: Apple deployment docs, Ubiquiti help center, enterprise WiFi community,
ChatGPT research (2026-03-17).

---

## iOS WiFi Power-Save Behavior (Screen Off)

**iOS does NOT disconnect WiFi when the screen locks.** It enters 802.11 PSM
(Power Save Mode): the radio reduces its duty cycle, and the AP is expected to
buffer frames until the client wakes to collect them.

- Association is normally preserved for hours while the screen is off
- Traffic becomes bursty; the AP sees the client as "quiet" but not gone
- Push notifications cause brief wakeups (~15 seconds of radio activity)
- **Plugged in:** WiFi stays fully active regardless of screen state

**Who drops the client during sleep?**
Both sides can, but the AP is the more common initiator in practice:
- AP idle timeout fires on a quiet PSM client → deauth
- AP's PSM buffering is misconfigured or UAPSD is off → client goes unresponsive
- iOS can also initiate disassociation in extreme low-battery conditions, but
  Apple has never documented a proactive "sleep disconnect" policy

**Re-association on wake:** usually sub-second to a few seconds. With 802.11r
enabled, the auth handoff is faster. Without it, PMKID caching still speeds up
reconnects to previously-joined BSSIDs. A congested or distant AP can push this
to 5–10 seconds.

---

## Wi-Fi Assist

Apple feature (iOS 9+, on by default) that silently routes **foreground app
traffic** to cellular when WiFi quality is poor. Key behaviors:

- Does not disconnect the WiFi radio — just routes traffic over LTE/5G
- Only affects foreground apps; background downloads stay on WiFi
- Does not activate during data roaming
- Cellular indicator appears in status bar when active
- Can make WiFi drops invisible to the user — they just experience "slow internet"
  without knowing the phone switched to cellular

Source: https://support.apple.com/en-us/102228

---

## iOS Roaming Behavior

iOS uses **client-driven roaming** based on performance, not just RSSI:

- Holds current BSSID until signal degrades to approximately **-70 dBm**
- Candidate AP must be **~8 dB stronger** while transmitting, **~12 dB stronger**
  while idle (hysteresis prevents unnecessary roams)
- Also factors in **channel utilization** and **client count** when scoring candidates
- Supports 802.11k (neighbor reports), 802.11r (fast BSS transition), 802.11v
  (BSS transition management / AP steering hints)

**Sticky vs aggressive:** iPhones tend toward sticky behavior (hold current AP
until threshold is crossed), but will roam on *performance* degradation even if
RSSI hasn't hit -70 dBm. In a dense AP environment with overlapping cells, this
can look like "bouncing" — especially if band steering or BSS transition hints
are actively nudging the client.

**AP bouncing signature:** short dwell times (seconds to low minutes) across
multiple APs usually indicates:
1. Heavy cell overlap — multiple APs within the hysteresis band simultaneously
2. BSS Transition / band steering actively steering the client
3. RF quality issue at one AP triggering performance-driven roam
4. 802.11r FT failure causing repeated re-association attempts (less common)

Source: https://support.apple.com/guide/deployment/wi-fi-roaming-support-dep98f116c0f/web

---

## UniFi Settings That Affect iOS Behavior

Inspectable via `just unifi wifi config`. Listed in order of likely impact:

### UAPSD (Unscheduled Automatic Power Save Delivery)
- **What it does:** Allows the AP to buffer frames for sleeping clients and deliver
  them in batches when the client wakes. Required for proper 802.11 PSM operation.
- **If off:** PSM clients may not receive buffered frames reliably; AP may time
  them out sooner; re-association after screen-on may be required more often.
- **Ubiquiti default:** Off. Ubiquiti's compatibility troubleshooting guide also
  recommends turning it off for maximum compatibility — so this is genuinely a
  trade-off, not a clear "always on" setting.

### Transmit Power
- **What it does:** Controls AP radio output power. Higher power = larger cell.
- **If too high:** Cells overlap heavily; iPhone sees multiple APs within a few
  dB of each other simultaneously; roaming decisions become noisy; client may
  bounce between APs or oscillate near cell boundaries.
- **Ubiquiti recommendation:** Medium/auto rather than max. Client signal should
  be -65 to -70 dBm at the edge of coverage, not -40 dBm everywhere.
- **Our network:** Several APs running at max (22–25 dBm). Upstairs AC HD is
  notably loud at 25 dBm on both bands.

### Minimum RSSI
- **What it does:** Hard-kicks clients below a signal threshold, forcing them to
  roam to a better AP.
- **Risk:** If too aggressive, or misconfigured (enabled without a sane threshold),
  it can create bouncing loops. Ubiquiti explicitly warns it can cause devices to
  refuse reconnection after repeated kicks.
- **Recommendation:** Leave off in a home network unless you have a specific
  sticky-client problem. If enabled, should have an explicit threshold value.

### Fast Roaming (802.11r)
- **What it does:** Fast BSS Transition — streamlines auth handoff during roams.
- **Known issue:** Apple devices + WPA3 + 802.11r FT has a documented iOS bug
  (per Ubiquiti release notes). Not an issue with WPA2-only networks.
- **Our network:** Off. WPA2-only, so no WPA3 FT issue. Enabling it would likely
  reduce roam interruption time, but Ubiquiti's compatibility guide says off for
  maximum compatibility.

### BSS Transition (802.11v)
- **What it does:** Allows the AP to send steering hints suggesting the client
  roam to a different BSSID. Client is not required to comply, but most do.
- **Risk:** Can contribute to bouncing if multiple APs are aggressively steering
  simultaneously. Low risk if transmit power is well-tuned.
- **Our network:** On across all SSIDs.

### DTIM Period
- **What it does:** Controls the interval at which the AP sends buffered
  multicast/broadcast traffic (and wakes PSM clients to receive it).
- **UniFi defaults:** 1 on 2.4 GHz, 3 on 5 GHz — reasonable.
- **If too high:** PSM clients sleep longer, appear more "idle" to the AP.
- **Our network:** At defaults. Low priority for investigation.

### Band Steering
- **What it does:** Encourages dual-band clients onto 5 GHz. Uses BSS transition
  frames in current UniFi versions.
- **Our network:** Off on the main SSID, on for some IoT SSIDs.

---

## Diagnostic Workflow for Client Complaints

1. **Identify the device and physical location** — don't analyze AP choice without
   knowing where the person actually is.
2. **`just unifi client <hostname>`** — current signal, retries, uptime,
   last association time. Short uptime = recently re-associated.
3. **`just unifi wifi roaming <hostname>`** — session history with per-AP segments,
   durations, and satisfaction scores. Use `--sessions N` to look back further.
   Confirms previous AP, roam pattern, and whether bouncing is recurring.
4. **`just network-snapshot`** — rule out WAN/ISP issues before chasing WiFi.
5. **`just unifi wifi config`** — check SSID settings (UAPSD, Fast Roaming, Min
   RSSI) and AP transmit power levels. APs at max power with heavy overlap are
   a roaming risk.
6. **`just unifi wifi rfscan`** — check external channel congestion if retries are
   high and the AP config looks clean.

---

## Network Config Snapshot & Change Log

### SSID Settings (main SSID: `something with pickles in it`)

| Setting | Value | Notes |
|---|---|---|
| Security | WPA2 only | Good — no WPA3 FT issues |
| Fast Roaming (802.11r) | Off | Low risk; could help roam speed |
| BSS Transition (802.11v) | On | OK |
| UAPSD | Off | May contribute to AP dropping sleeping iPhones — see open questions |
| DTIM 2.4GHz / 5GHz | 1 / 3 | At defaults, fine |
| Min RSSI | Enabled, no threshold | Suspicious — see open questions |
| Band Steering | Off | Fine |

### AP Transmit Power

**2026-03-17: reduced all 5GHz radios from max → medium** (`just unifi wifi set-power all 5 medium --yes`)

| AP | 5GHz Before | 5GHz After | Max | 2.4GHz | Notes |
|---|---|---|---|---|---|
| Josh Office AC Pro | 22 dBm | **14 dBm** | 22 dBm | 15 dBm (max) | |
| Living Room AC LR | 22 dBm | **13 dBm** | 22 dBm | 17 dBm (max) | |
| Tracy Office AC Pro | 22 dBm | **14 dBm** | 22 dBm | 15 dBm (max) | |
| Upstairs AC HD | 25 dBm | **16 dBm** | 25 dBm | 25 dBm (max) | Loudest AP; most central |
| Porch AC LR | 19 dBm | **13 dBm** | 22 dBm | 17 dBm (max) | |

2.4GHz left at max — lower frequency penetrates walls better; reducing aggressively
risks dead spots. Revisit if 2.4GHz bouncing becomes an issue.

---

## Open Questions / Follow-up

### 1. Did reducing 5GHz tx power improve roaming? (check in a day or two)
- **How to check:** `just unifi wifi roaming raisynglsiPhone --sessions 3`
- **What to look for:** Fewer short-dwell segments (<60s), longer dwell times per AP,
  fewer distinct APs per session
- **Baseline for comparison:** Session on 2026-03-17 showed 11 segments across 5 APs
  in ~1h with one sat=84 dip on Porch AC LR

### 2. Why is Min RSSI `enabled=True` with no threshold on the main SSID?
- **Risk:** Unknown behavior — could be a no-op, or could be kicking clients at
  some internal default threshold, contributing to bouncing
- **How to investigate:** Check UniFi controller UI for the actual SSID settings;
  the API field `minrate_na_enabled` may be conflated with min RSSI in our current
  `config` display — worth verifying the actual field names
- **Action if confirmed misconfigured:** Disable or set an explicit threshold

### 3. Should UAPSD be enabled?
- **Trade-off:** Enables proper 802.11 frame buffering for sleeping iPhones (reduces
  AP-initiated drops during screen-off), but Ubiquiti's own compatibility guide
  recommends off for maximum compatibility
- **Priority:** Low — address after evaluating tx power change first
- **How to change:** UniFi controller UI → SSID settings → Advanced → UAPSD
