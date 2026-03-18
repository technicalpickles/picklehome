# Outdoor WiFi Coverage Research

Research on deploying a UniFi AP for backyard coverage past cinderblock construction,
with minimal interference to indoor APs. Conducted 2026-03-18.

---

## Context

- **Problem:** Porch AC LR (U7LR) was discovered to be physically co-located with Josh
  Office AC Pro (U7PG2) inside the house — all historical performance data for "Porch"
  is unreliable. The AP was never actually covering the porch or backyard.
- **Goal:** Provide reliable WiFi coverage in the backyard, past a cinderblock wall,
  without interfering with indoor APs or causing sticky-client problems.

---

## Bottom Line

**The wall is the primary problem, not settings.** Cinderblock is highly attenuating,
especially for 5 GHz. No amount of TX power tuning reliably overcomes a geometry problem.
The correct fix is placement + antenna pattern, not configuration.

The U7LR is a capable indoor AP but is not weatherproofed and has an omnidirectional
antenna pattern with modest gain (6 dBi / 5 GHz, 4 dBi / 2.4 GHz). It is suitable for
a controlled test but is not the ideal permanent outdoor solution.

---

## Hardware Comparison

| AP | Weatherproofing | 5 GHz Gain | 2.4 GHz Gain | 5 GHz TX | Notes |
|---|---|---|---|---|---|
| **U7 Outdoor** | IPX6 | 12.5 dBi (directional) | 8 dBi | high | Best fit; directional pattern built for outdoor |
| **U7 Mesh** | IPX6 (w/ outdoor mount) | 10 dBi (directional) or 6 dBi (omni) | varies | high | Good compromise |
| **U6 Mesh** | IPX5 | ~5 dBi omni | ~4 dBi | medium | Weatherproof, older Wi-Fi 6 |
| **U7LR** | None | 6 dBi | 4 dBi | 27 dBm | Indoor only; suitable for testing |
| **UAP-AC-M** | Yes | 3 dBi | 4 dBi | 20 dBm | Weakest radio; not recommended |

**Recommendation:** Use U7LR for initial testing. If it passes the decision gate, keep it
temporarily. Long-term, **U7 Outdoor** is the right hardware — meaningfully better antenna
gain and directional pattern for "cover yard from one side."

---

## Mounting Orientation

For a ceiling-mount disc AP (like U7LR) used on a wall:

- **Correct:** mount flat against the wall with the face pointing outward toward the yard
  (like hanging a picture frame). Antennas stay in correct orientation, main lobe projects
  into the yard.
- **Wrong:** protruding from the wall at 90° (like a shelf bracket). This rotates antenna
  polarization and redirects the main lobe sideways along the wall, not into the yard.

A **high soffit/eave mount** (AP in normal ceiling-mount orientation facing down) can
outperform a wall mount by radiating over the top of the cinderblock rather than into it.
Not wired currently, but worth considering if wall mount results are poor.

---

## Starting Radio Configuration

**Porch AP:**
- 2.4 GHz: ch 11, 20 MHz, Low power
- 5 GHz: ch 149 or 157, 40 MHz, Medium power
- Band steering: enabled

**Josh Office AP (unchanged):**
- 2.4 GHz: ch 1, 20 MHz
- 5 GHz: ch 40, 40 MHz

Rationale:
- Use only 1/6/11 on 2.4 GHz (non-overlapping); avoid ch 40 on 5 GHz (Josh Office)
- Start conservative on power — high TX does not fix cinderblock penetration and increases
  indoor bleed / sticky-client risk
- Band steering nudges capable clients to 5 GHz (shorter range, less indoor bleed)
- Keep 2.4 GHz enabled on outdoor AP — it penetrates block better than 5 GHz

Do NOT use 40 MHz on 2.4 GHz (Cisco: causes co-channel problems in dense environments).

---

## TX Power Trade-offs

| Power | Pros | Cons |
|---|---|---|
| Low | Smaller cell, less indoor bleed, better roaming discipline | May not reach far yard |
| High | Better RSSI reading outside | Sticky indoor clients, more Office overlap, false confidence (uplink still limited by client TX) |

Target outdoor RSSI: **-65 to -70 dBm** minimum for reliable connections.

---

## Roaming / Interference Controls

Apply in order, only as needed:

1. **First:** tune channels, width, TX power only — no roaming kicks
2. **If indoor clients stick to Porch AP:** enable Roaming Assistant on Porch AP (softer than Min RSSI)
3. **If still broken:** add mild Minimum RSSI on Porch 5 GHz only, test carefully

Minimum RSSI can cause instability if mis-tuned — use as last resort.

BSS coloring / RRM are cleanup tools, not primary design tools. They don't solve geometry.

---

## Decision Gate: Keep U7LR vs. Buy U7 Outdoor

Buy the U7 Outdoor if, after correct placement and conservative config:
- Mid-yard RSSI is still below **-70 dBm**
- 5 GHz is unusable outside (clients fall back to 2.4 GHz only)
- Indoor clients keep preferring Porch AP even at reduced TX power
- RSSI looks OK but retries/throughput are poor (uplink geometry problem)

If mid-yard hits **-65 dBm or better on 5 GHz**, the U7LR placement is working and
you can decide whether to leave it or still upgrade for weatherproofing reasons.

---

## Measurement Protocol

Run `wifi-diag.py` from a laptop at each spot; log RSSI, SNR, AP name, band, channel,
retry %, and a quick speed test. Compare before (current indoor placement) and after
(exterior wall, correct orientation).

Fixed test spots:
1. Inside the room adjacent to porch (Josh Office side) — should stay on Office AP
2. Screened porch center
3. Just past the cinderblock wall (near-yard)
4. Mid-yard
5. Far yard / Sonos area

---

## Sources

- Aruba Networks RF Design Guide — cinderblock attenuation
- UniFi Tech Specs: U7LR, U7 Outdoor, U7 Mesh, U6 Mesh, UAP-AC-M
- Ubiquiti Help Center: AP Antenna Radiation Patterns, Optimizing WiFi Connectivity,
  UniFi WiFi SSID and AP Settings Overview, WiFi Troubleshooting Guide
