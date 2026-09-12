# Network Topology

Last updated: 2026-03-21

## Physical Layout

```
AT&T Fiber
    │
    ▼
AT&T BGW320 (fiber gateway)
    192.168.8.254  (admin UI: http://192.168.8.254)
    WAN: public AT&T IP (AS7018)
    │
    │  (double-NAT: BGW is NOT in IP passthrough mode)
    │
    ▼
UniFi USG 3P (router/firewall)
    WAN: 192.168.8.65  (DHCP from BGW)
    LAN: 192.168.1.1   (gateway for home network)
    │
    ▼
UniFi CloudKey G2 Plus (network controller)
    192.168.1.57
    UI: https://192.168.1.57
    UniFi Network: 10.1.85
```

## Tailscale Overlay Network

Tailscale mesh VPN connects devices across the home LAN and external networks.
All devices are on the same tailnet with MagicDNS enabled, so they can reach each
other by hostname (e.g. `picklelab`) or Tailscale IP (`100.x.y.z`).

| Device | Tailscale IP | OS | Role |
|---|---|---|---|
| joshs-macbook-pro | 100.120.123.117 | macOS | Primary workstation |
| picklelab | 100.123.122.68 | linux | Home server (runs climate-auto-switch) |
| iphone182 | 100.125.174.38 | iOS | Josh's iPhone |

To expose a service on one device to another, bind to `0.0.0.0` (not `127.0.0.1`)
and access via Tailscale hostname or IP. No port forwarding or firewall changes needed.

```bash
just tailscale           # show all tailnet devices + status
tailscale ip             # show this device's Tailscale IP
```

## Hardware Inventory

### Infrastructure

| Device | Model | IP | Firmware | Notes |
|---|---|---|---|---|
| AT&T BGW320 | BGW320-505 | 192.168.8.254 | n/a | Fiber gateway; WiFi disabled; admin UI at `http://192.168.8.254` |
| USG 3P | USG 3P | 192.168.8.65 (WAN) / 192.168.1.1 (LAN) | 4.4.57 | Router/firewall |
| CloudKey G2 Plus | n/a | 192.168.1.57 | Network 10.1.85 | UniFi controller; UI at `https://192.168.1.57` |

### Switches

| Name | Model | IP | Firmware | Notes |
|---|---|---|---|---|
| US 8 PoE 150W | US 8 PoE 150W | 192.168.1.134 | 7.0.50 | Main PoE switch: powers all APs |
| US 24 | US 24 | 192.168.1.99 | 7.0.50 | |
| US 8 | US 8 | 192.168.1.17 | 7.0.50 | |
| US 8 | US 8 | 192.168.1.25 | 5.76.7 | **Offline** |

### Access Points

Five UniFi APs, all wired via ethernet (no wireless uplink/mesh). All PoE from the US 8 PoE 150W.

| Name | Model Code | Model | IP | Firmware | Floor | Mount | Antenna | Notes |
|---|---|---|---|---|---|---|---|---|
| Living Room AC LR | U7LR | AC Long Range | 192.168.1.42 | 6.6.65 | 1st | Wall, facing in | High-gain focused beam | Central AP, most clients; open stairwell nearby. Mount corrected 2026-09-02 (markup pass) from a previously-documented "floor, facing up" |
| Upstairs AC HD | U7HD | AC High Density | 192.168.1.103 | 6.6.65 | 2nd | Ceiling, facing down | Wide uniform | Above/near the stairwell opening |
| Josh Office AC Pro | U7PG2 | AC Pro | 192.168.1.22 | 6.6.65 | 1st | Floor under desk, facing up | Standard omni | Same room as Porch AP (co-located) |
| Tracy Office AC Pro | U7PG2 | AC Pro | 192.168.1.194 | 6.6.65 | 1st | Floor, facing up | Standard omni | Converted carport; brick wall between it and main house |
| Porch AC LR | U7LR | AC Long Range | 192.168.1.16 | 6.6.65 | 1st | Was: exterior wall, horizontal, facing backyard | High-gain focused beam | **Offline**: currently in Josh's office; pending relocation; see `docs/outdoor-wifi-research.md` |

> **Live state:** Run `just unifi topology` for the full device tree with uplink ports and radio state.
> Run `just unifi wifi aps` for current channels, utilization, retries, and tx power.
> Run `just unifi wifi config` for SSID settings and per-AP power mode.
> Run `just unifi devices` for all adopted devices with firmware versions.
> Use `just unifi topology --format mermaid` to generate a diagram for docs.

### Room Registry

Stable room IDs, so docs/investigations/floorplan annotations can reference an exact
room instead of an ambiguous name (e.g. "TV room" wasn't documented anywhere before the
2026-08-20 investigation, and turned out to be a distinct room between Living Room and
Josh Office, not a synonym for either). Format: `<floor>-<kebab-case-slug>`. IDs are
assigned once and never renumbered or reused, same rule as taskwarrior UUIDs and plan
step slugs — if a room needs splitting later (e.g. "upstairs" turns out to be three
rooms), give the new rooms new IDs rather than repurposing the old one.

Floors: `1` = ground floor (same level as the garage/entry), `2` = upper floor.

| Room ID | Common name | Floor | Notes | Status |
|---|---|---|---|---|
| `1-living-room` | Living Room | 1 | Has Living Room AC LR; L-shaped, runs from TV Room past the stairwell nook to Kitchen/Dining/Entry | confirmed |
| `1-josh-office` | Josh's Office | 1 | Has Josh Office AC Pro + offline Porch AC LR (co-located) | confirmed |
| `1-tracy-office` | Tracy's Office | 1 | Converted carport; brick wall between it and main house | confirmed |
| `1-tv-room` | TV Room | 1 | Between Living Room and Josh's Office; single doorway to Living Room; site of the 2026-08-20 roaming investigation | confirmed |
| `1-porch` | Porch / backyard | 1 (exterior) | Porch AC LR's original/intended mount location, facing backyard; currently offline, relocation pending | confirmed |
| `1-gym-bathroom` | Gym Bathroom | 1 | Spans the front of the house above/beside Josh's Office; largest 1st-floor room (214.69 sqft) | confirmed |
| `1-kitchen` | Kitchen | 1 | Open to Living Room, no dividing wall | confirmed |
| `1-dining-room` | Dining Room | 1 | Open to Kitchen/Living Room | confirmed |
| `1-entry` | Entry | 1 | Front door, off the angled bay window nook east of Living Room; `2-storage` sits directly above it | confirmed (user-verified cross-floor stacking) |
| `2-hallway` | Upstairs Hallway | 2 | Central 2nd-floor room (211.66 sqft); has Upstairs AC HD, ceiling-mounted. Its NW corner (just below `2-bathroom`) lines up with the upper part of `1-living-room` (open concept), which contains the stairwell landing. Resolves former `2-upstairs-tbd` placeholder | confirmed (user-verified corner alignment) |
| `2-bathroom` | Bathroom above Josh's Office | 2 | Footprint sits above `1-josh-office` (not `1-gym-bathroom` as previously estimated — see Alignment caveat below); tile floor; referenced in `CHANGELOG.md` (2026-03-20 Tracy Office channel note) as a spot with 3 distinct 5GHz APs in range. Resolves former `2-bathroom-above-office` placeholder | confirmed (user-verified in person, 2026-09-02) |
| `2-bedroom` | Primary Bedroom | 2 | Above `1-tv-room`'s footprint; NE corner matches `1-tv-room`'s NE corner (same orientation, user-verified); largest 2nd-floor room (237.98 sqft) | confirmed (user-verified corner alignment) |
| `2-alex-bedroom` | Alex's Bedroom | 2 | Off `2-hallway` | confirmed |
| `2-playroom` | Playroom | 2 | Off `2-hallway` | confirmed |
| `2-laundry` | Laundry | 2 | Off `2-hallway`, near `2-bathroom` | confirmed |
| `2-storage` | Storage | 2 | Off `2-bedroom`; directly above `1-entry` | confirmed (user-verified cross-floor stacking) |
| `1-shower` | Shower (Josh's Office wing) | 1 | 40.77 sqft; sits ~10ft east of `1-gym-bathroom` at similar y, north of `1-josh-office` | confirmed (DXF position) |
| `1-powder-room` | Powder room off the stairwell | 1 | 47.27 sqft; toilet + sink, small closet/stair icon on its MagicPlan floor plan, between `1-living-room`'s stairwell nook and `1-dining-room` | confirmed (DXF position + PDF thumbnail) |
| `1-office-bathroom` | Small bathroom by Josh's Office | 1 | 25.99 sqft; toilet-only per its MagicPlan floor plan; closest of the two ambiguous "Bathroom" rooms to `1-josh-office` | confirmed (DXF position + PDF thumbnail) |
| `1-tracy-annex` | Pantry | 1 | 104.81 sqft; east end of the house, south of `1-tracy-office`. MagicPlan's floor plan shows it furnished (bed/seating-shaped icon), which reads oddly for a pantry, but user confirmed the name in person | confirmed |
| `1-living-room-closet` | Small nook off the Living Room | 1 | 10.63 sqft; between `1-living-room` and `1-kitchen` — user confirmed this isn't an actual room (likely a MagicPlan scan artifact, not a real enclosed space) | confirmed |
| `2-bathroom-east` | Bathroom near the Playroom | 2 | 62.73 sqft; east side of the floor, near `2-playroom`; distinct from `2-bathroom` above | confirmed (DXF position + PDF thumbnail) |
| `2-closet-hallway` | Closet off the Hallway | 2 | 75.49 sqft; west side, near `2-hallway`/`2-bedroom` | confirmed (DXF position + PDF thumbnail) |
| `2-closet-alex` | Closet off Alex's Bedroom | 2 | 50.38 sqft; directly adjacent to `2-alex-bedroom` | confirmed (DXF position + PDF thumbnail) |
| `2-nook-a` | Closet off Alex's Bedroom continued | 2 | 19.58 sqft; east side near `2-closet-alex`/`2-bathroom-east` | confirmed |
| `2-nook-b` | Small unclassified room | 2 | 5.00 sqft; east side, west of `2-nook-a`/`2-nook-c` — user confirmed this isn't an actual room (likely a MagicPlan scan artifact, not a real enclosed space) | confirmed |
| `2-nook-c` | Playroom closet | 2 | 13.28 sqft; east side, between `2-nook-a` and `2-nook-b`; storage off `2-playroom` | confirmed |

**Alignment caveat:** initially resolved from the MagicPlan "Sketch Files" PNG/SVG
exports (2026-08-22, stored in Dropbox — see Room Layout below) by matching room
footprints and printed dimensions between the two independently-scanned floor images —
a visual estimate, not the precision overlay `docs/floorplan-markup-legend.md` calls
for. Three pairs are now user-verified in person against the actual house (not just
the floorplan image): `1-tv-room`'s NE corner = `2-bedroom`'s NE corner (confirms same
orientation), `2-hallway`'s NW corner (just below `2-bathroom`) lines up with the
upper part of open-concept `1-living-room`, and `1-entry` sits directly below
`2-storage`.

That third pair (`1-entry`/`2-storage`) matters beyond confirming those two rooms: it
gives a real registration offset between floor 1's and floor 2's independent DXF
coordinate systems (`network/floorplan/floor-{1,2}.geojson` — each floor keeps its own
origin, see `docs/floorplan-geojson-schema.md`). `2-storage`'s raw coordinates minus
`1-entry`'s raw coordinates work out to roughly (-12, +17); the `1-tv-room`/`2-bedroom`
pair gives a consistent (-13, +18). Applying that offset to `2-bathroom`'s coordinates
lands it on top of `1-josh-office`, not `1-gym-bathroom` as the Room Registry
previously stated — that prior claim (`2-bathroom`'s raw x-coordinate landing within
0.4ft of `1-gym-bathroom`'s) compared un-registered coordinates from two different
origins and the match was coincidental. `2-bathroom` is now recorded as above
`1-josh-office` alone, user-confirmed in person 2026-09-02 (taskwarrior `71701d18`,
closed).

**New rooms below** (`1-shower` through `2-nook-c`) were surfaced by the
`floorplan_dxf_to_geojson.py` pipeline (see `docs/floorplan-geojson-schema.md`):
MagicPlan's own room schedule listed them, but duplicate labels ("Bathroom", "Other",
"Closet" repeated on the same floor) meant they had no room_id until each was
resolved by cross-referencing the Report PDF's per-room thumbnail against the DXF
label position. That resolved *which physical room* is which schedule entry; the
former "Other"/"nook" rooms' *purpose* has since been confirmed in person
(`1-tracy-annex`, `2-nook-a`, `2-nook-c`), including that two of them
(`1-living-room-closet`, `2-nook-b`) aren't actually distinct enclosed rooms —
probably MagicPlan scan artifacts rather than real spaces.

### Room Layout

From the MagicPlan "Sketch Files" export (both floors, dimensioned; captured 2026-08-22,
stored in `~/Dropbox/2108 Marann Dr Floor Plans/` rather than the vault — see Storage
note in `docs/floorplan-markup-legend.md`). This prose section is adjacency + rough
distance, deliberately generic; the precision wall-material/AP/RF-hostile-object
markup pass (per `docs/floorplan-capture-checklist.md`) is done and lives in
`network/floorplan/floor-{1,2}.geojson` — see the Markup pass note below for a
summary of what it found. No floor-penetration (duct chase, non-stairwell opening)
markup has been done yet.

**1st floor:** `1-gym-bathroom` spans the front of the house. Below/beside it,
`1-josh-office` (+ a small bathroom/shower) sits on the west side and `1-tv-room` on
the east side, connected to `1-living-room` by a single doorway (no other wall between
them). `1-living-room` is L-shaped, running from `1-tv-room` past a central stairwell
nook down to `1-kitchen`/`1-dining-room`/`1-entry`. `1-tracy-office` is a separate wing
(converted carport) off the south end, with the already-documented brick dividing wall.

**2nd floor:** footprint sits only over the `1-gym-bathroom` / `1-josh-office` /
`1-tv-room` block, not over the kitchen/dining/entry/Tracy-office wing (those read as
single-story from the floorplan extents). `2-bathroom` (top-left) lines up over
`1-josh-office` alone, user-confirmed in person (corrected 2026-09-02 — see the
Alignment caveat above; previously thought to also span `1-gym-bathroom`). `2-bedroom` (top-right)
lines up over `1-tv-room` — user-verified: their NE corners are the same corner, same
orientation. `2-hallway`'s NW corner (just below `2-bathroom`) lines up with the upper
part of `1-living-room` — also user-verified. `1-living-room` is open concept, so this
is the same stairwell-landing/Upstairs-AC-HD area the AP table's "open stairwell
connects Living Room and Upstairs" note and `docs/24ghz-power-tuning.md` already
describe, now with a confirmed corner instead of a guess.

**Floor construction/materials (user-confirmed 2026-09-02):** the house is largely
hardwood floor over standard wood-joist framing. Exceptions: the upstairs bathrooms
(`2-bathroom`, `2-bathroom-east`) are tile; `1-tracy-office` and `1-tracy-annex`
(Pantry) sit on a concrete slab (that wing was originally a carport); `1-entry` is
also slab. Since `1-living-room`, `1-josh-office`, and the 2nd floor above them are
hardwood (not slab), the floor/ceiling assembly between those two levels is standard
wood-joist construction, not concrete. User also confirmed there's no ductwork or HVAC
returns running through that joist bay — all ductwork lives in the attic above the 2nd
floor or the basement below the 1st floor, not between the levels themselves. Together
this fully resolves the `docs/floorplan-capture-checklist.md` "floor/ceiling
construction between levels" item (taskwarrior `d04eb7cc`, closed): the path between
Upstairs AC HD, Living Room AC LR, and Josh Office AC Pro is plain wood-joist/hardwood,
no metal in the way.

**TV Room finding (reopens the 2026-08-20 open question):** `1-tv-room` is a short
hop from Living Room AC LR, roughly 10-15 ft through a single doorway, both rooms part
of the same open ground-floor pod — not a long-range or heavy-material path. That means
the observed -64 to -75 dBm in `1-tv-room` is **not** well explained by simple
distance/wall-material path loss.

**Mount correction (2026-09-02 markup pass) changes the likely explanation.**
Living Room AC LR was previously documented as floor-mounted facing up (see the AP
table above, prior to this correction); the markup pass placed it at (-1.06, 4.48) —
against the wall a few feet from `1-living-room`'s center — and its mount is actually
**wall, facing in**, not floor/facing-up. That retires the vertical-throw-through-the-
stairwell theory below as stated (a wall-mounted antenna facing into the room isn't
throwing a focused beam straight up through a stairwell); the *high-gain focused beam*
antenna is still real, so a simpler explanation now fits better: if the AP is mounted
facing into `1-living-room` away from the `1-tv-room` doorway, the focused pattern's
edge/back lobe covering that doorway would plausibly be weak regardless of the short
physical distance — an antenna-orientation problem, not a vertical-throw trade-off.
The `2-hallway`/stairwell vertical-coverage explanation this mount correction retires
needs its own re-examination; it was resting on the now-corrected "floor-mounted
facing up" premise.

This reframes the two still-open threads from the 2026-08-20 investigation as separate
problems: leveling Josh Office AC Pro's tx power would address *roaming* onto a weaker
AP, not `1-tv-room`'s baseline weak signal from Living Room AC LR — that's an
antenna-pattern/coverage problem, closer to relocating Porch AC LR to an interior wall
aimed into `1-tv-room`/`1-living-room` instead of outdoors (taskwarrior `0bc49afc`)
than a tx-power tweak.

(This paragraph previously cited "task 385"/"task 386" — taskwarrior's integer IDs get
reused once a task completes, and by 2026-09-02 those numbers pointed at unrelated
chirpfinder tasks. Re-pointed to stable UUIDs per the "cite UUIDs, not integer IDs, in
durable docs" convention.)

**2026-09-02 update — roaming thread closed, not fixed:** before making the Josh
Office tx-power change, a live review (`267b6114`, closed) found no active roaming
problem — recent Josh iPhone roaming history held satisfaction 99-100 through every
segment, with no bad landings like the 2026-08-20 -83dBm Upstairs bounce. The 1dB gap
between Josh Office (14dBm/medium) and Living Room/Upstairs (13dBm/custom) is much
smaller than the 16-vs-13 asymmetry that caused that original bounce, so the tx-power
change was skipped. The live hotspot right now is Living Room AC LR 5GHz itself (88%
utilization, 34.2% retries) — tracked as a capacity/load question, not a roaming one,
in taskwarrior `515`.

**Markup pass (2026-09-02):** wall material, AP positions, and RF-hostile objects were
hand-placed against the DXF floor plan via the floorplan-playground editor and are now
in `network/floorplan/floor-{1,2}.geojson` (`wall`/`ap`/`rf_hostile` features per
`docs/floorplan-geojson-schema.md`); this satisfies the remaining part of task 477.
Click-precision positions, not a surveyed markup pass — good enough for RF reasoning,
not for construction.

- **Walls, the general pattern (user-confirmed):** the house's original core is brick
  on the exterior — the entire upstairs (2nd floor), the first-floor footprint below
  it (`1-gym-bathroom`/`1-josh-office`/`1-shower`/`1-office-bathroom`/`1-tv-room`),
  plus the two separate wings `1-tracy-office` and `1-tracy-annex` (Pantry). This
  matches what the wall markup found: both floors' perimeter walls in that footprint
  came back brick, and the already-documented `1-tracy-office` dividing wall is
  confirmed with exact coordinates (4 segments along its west/south boundary). The
  single-story `1-kitchen`/`1-dining-room`/`1-living-room`/`1-entry` wing was **not**
  tagged brick in this pass — consistent with it being a different, presumably later,
  addition; its actual exterior material is still unconfirmed.
  One interior exception, worth a second look: a **masonry** wall in the kitchen
  wing at (10.65, -1.53)-(16.83, -1.53) (between `1-kitchen` and the small non-room
  nook there) — not part of the brick core, and not brick itself. (The wall near
  `1-office-bathroom`/`1-josh-office` at (-18.74, -14.81)-(-9.73, -14.81) was
  initially misread as block; it's brick, part of the core, and corrected in the
  GeoJSON.) There's also a dense cluster
  of ~20 short brick segments in the `1-living-room`/`1-tv-room`/`1-kitchen` corner
  (roughly x: 3-26, y: 8-17) — plausibly a fireplace/chimney structure (there's an
  `rf_hostile` "fireplace" pin nearby at (14.15, -0.65), though not at quite the same
  spot) rather than dozens of individual walls; worth confirming what's actually there
  next time someone's in that corner.
- **APs:** all 5 are now positioned in the GeoJSON except Porch AC LR (currently
  relocated indoors with Josh Office AC Pro per the AP table — not placed separately
  since its real position is "somewhere in `1-josh-office`", not worth pinning until
  it's back at a fixed mount). Living Room AC LR's mount correction is written up
  above.
- **RF-hostile objects:** floor 1 has a mirror near `1-gym-bathroom`'s west end
  (-31.09, -3.19), a mirror near `1-powder-room` (-3.2, -10.2), an electric panel near
  `1-office-bathroom`/`1-josh-office` (-18.23, -8.62), and the fireplace noted above.
  Floor 2 has two mirrors, one near `2-closet-hallway`/`2-hallway` (-22.48, 15.38) and
  one near `2-closet-alex`/`2-nook-a` (12.88, 11.36). None of these were previously
  documented; worth keeping in mind for any AP repositioning near those spots.

### AP Model Characteristics

| Model | 2.4 GHz Max | 5 GHz Max | Design Intent |
|---|---|---|---|
| U7LR (AC Long Range) | 24 dBm | 22 dBm | Focused high-gain antenna for long range; reaches further than needed in a home |
| U7HD (AC High Density) | 25 dBm | 25 dBm | Wide coverage for many clients in smaller area; highest raw power |
| U7PG2 (AC Pro) | 22 dBm | 22 dBm | Balanced omnidirectional; lowest max power of the three |

---

## Channel & Power Plan

**This section documents _why_ the current configuration exists.** Update entries in-place
when making changes, don't append. For change history, see `CHANGELOG.md`.

### 2.4 GHz Channel Assignments

Only three non-overlapping channels exist: **1, 6, 11**. Dense neighborhood means all three
are congested with 70-110 external neighbors each. Channel selection is about minimizing
*internal* co-channel between our own APs, not avoiding neighbors.

| Channel | APs | Why |
|---|---|---|
| **1** | Josh Office, Tracy Office | Offices are on opposite sides of the house, so co-channel is acceptable at this distance |
| **6** | Living Room | Only AP on ch 6 after Upstairs moved to ch 11 (2026-03-21) |
| **11** | Upstairs | Moved from ch 6 to eliminate co-channel with Living Room through open stairwell. **Porch will conflict when it comes back**: re-plan at that point (only 3 channels for 5 APs) |

### 5 GHz Channel Assignments

5 GHz is much cleaner: shorter range through walls means fewer neighbor conflicts.

| Channel | APs | Why |
|---|---|---|
| **40** | Josh Office | Cleanest 5 GHz channel (fewest neighbors, all weak) |
| **48** | Tracy Office, Porch (offline) | Clean since BGW WiFi was disabled (was interfering at -13 dBm). Tracy moved here from ch 40 (2026-03-20) so phones in the bathroom above Josh's office see three distinct channels and roam cleanly |
| **149** | Living Room | Moved from ch 157 (2026-03-16) to avoid co-channel with Upstairs. Moderate neighbor count but low utilization |
| **157** | Upstairs | Low neighbor count, reasonable interference levels |

### 2.4 GHz Power Plan

| AP | Mode | Actual | Why |
|---|---|---|---|
| Living Room AC LR | medium | ~15 dBm | Reduced from max/17 dBm (2026-03-21): LR's high-gain antenna was pushing signal through open stairwell into Upstairs zone; all 2.4 GHz clients have strong signal. See `docs/24ghz-power-tuning.md` |
| Upstairs AC HD | medium | ~16 dBm | Reduced from max/19 dBm (2026-03-21): was blasting down through stairwell; only 1-2 clients on this radio |
| Josh Office AC Pro | max | 15 dBm | Left at max: AC Pro max (22 dBm) produces only 15 dBm; already moderate |
| Tracy Office AC Pro | max | 15 dBm | Same as Josh Office: AC Pro's max is naturally lower than LR/HD |

### 5 GHz Power Plan

All APs set to **medium** (2026-03-17). Reduced from max to limit cell overlap and
reduce iPhone roaming churn: Tracy's phone was showing 11 roam segments/hour at max power.
See CHANGELOG.md 2026-03-17 entry.

| AP | Actual (medium) | Max |
|---|---|---|
| Josh Office AC Pro | 14 dBm | 22 dBm |
| Living Room AC LR | 13 dBm | 22 dBm |
| Tracy Office AC Pro | 14 dBm | 22 dBm |
| Upstairs AC HD | 16 dBm | 25 dBm |

### Constraints & Trade-offs

- **Only 3 non-overlapping 2.4 GHz channels for 5 APs**: co-channel is unavoidable somewhere.
  Current strategy: pair APs that are physically distant on the same channel.
- **Open stairwell** between Living Room (1st floor) and Upstairs (2nd floor) means RF
  travels freely between floors, so power reduction and channel separation both matter here.
- **AC-LR "Long Range" antenna** on Living Room is a liability: its focused beam amplifies
  vertical leakage through the stairwell. Would benefit from replacement with an AC Pro or
  similar omnidirectional AP if other changes are being made.
- **Porch AP return will force a re-plan**: it was on ch 11 (2.4 GHz) and ch 48 (5 GHz).
  Ch 11 now conflicts with Upstairs; ch 48 shares with Tracy Office.

### Inspecting & Changing Configuration

```bash
# Current state
just unifi wifi aps                              # channels, power, utilization, retries
just unifi wifi config                           # SSID settings + per-AP power mode
just unifi wifi rfscan --summary --fresh 60      # neighbor congestion per channel

# Make changes (prompts for confirmation unless --yes)
just unifi wifi set-channel "tracy" 5 36
just unifi wifi set-power "living" 2.4 medium --yes
```

**After any change:** update this section's rationale, add a CHANGELOG.md entry, and verify
with `just unifi wifi aps`.

## BGW320

Hardware details and CGI endpoint reference: [`docs/bgw-reference.md`](docs/bgw-reference.md).

### Resolved: WiFi "Disabled" but still beaconing (2026-03-18, resolved 2026-03-20)

Both radios set to Disabled via `wconfig_unified.ha`. UI and `just bgw wifi` confirm
Disabled, but `ATTt6kgiKH` (BSSID `bc:9a:8e:ed:fe:ec`) continued beaconing on 5GHz
ch 149 at -50 dBm after a full restart, confirmed via `just unifi wifi rfscan --fresh 5`.
Channel also shifted from ch 48 → ch 149 while "disabled," indicating the radio is still
active. Resolved without factory reset: 2026-03-20 RF scan shows no trace of the SSID
or BSSID. The disable eventually propagated (possibly after the BGW restart settled).

## Key IPs

| Device                  | IP               | Notes                        |
|-------------------------|------------------|------------------------------|
| AT&T BGW320             | 192.168.8.254    | Fiber gateway, admin UI      |
| USG 3P WAN              | 192.168.8.65     | DHCP from BGW                |
| USG 3P LAN              | 192.168.1.1      | Home network gateway         |
| CloudKey G2 Plus        | 192.168.1.57     | UniFi controller             |
| LAN subnet              | 192.168.1.0/24   | DHCP range .6 to .254        |

## DNS Configuration

### USG dnsmasq forwarders (as of 2026-03-16)
- Primary:   `8.8.8.8`  (Google)
- Secondary: `8.8.4.4`  (Google)
- Auto DNS Server: disabled (manually set in UniFi UI)
- No `resolv-file` fallback to BGW

### How to change WAN DNS
UniFi UI → Settings → Internet → Internet 1 → Advanced → Manual
Uncheck "Auto DNS Server" → set Primary/Secondary Server fields.
Takes effect immediately on next USG provisioning (often automatic within minutes).

### UniFi config override (if UI is insufficient)
Place `config.gateway.json` at:
```
/usr/lib/unifi/data/sites/default/config.gateway.json
```
Then force provision: Devices → USG → Settings → Manage → Force Provision.

Example to fully control dnsmasq forwarders:
```json
{
  "service": {
    "dns": {
      "forwarding": {
        "options": [
          "no-resolv",
          "server=8.8.8.8",
          "server=8.8.4.4",
          "cname=unifi.technicalpickles.xyz,unifi",
          "host-record=unifi,192.168.1.57"
        ]
      }
    }
  }
}
```

## ISP

- Provider: AT&T Fiber
- ASN: AS7018
- Region: southeastern US (Atlanta area)
- Known peering: AT&T → Cloudflare (AS13335) at `108.162.235.x` (Atlanta)

## Known Issues / History

### AT&T → Cloudflare peering (2026-03-12 to ~2026-03-16): resolved
See [`investigations/cloudflare-peering-2026-03.md`](investigations/cloudflare-peering-2026-03.md).
Permanent outcome: USG DNS switched from `1.1.1.1` to `8.8.8.8` (also a Cloudflare IP, so switching may have masked the issue rather than AT&T fixing the peering).

## External Status Resources

### ISP / CDN status pages

| Service | URL | What to check |
|---|---|---|
| AT&T | https://www.att.com/outages/ | Broadband outages by address |
| Cloudflare | https://www.cloudflarestatus.com/ | Global / regional incidents |
| Cloudflare Radar | https://radar.cloudflare.com/ | Traffic anomalies, AS-level trends |
| DownDetector (AT&T) | https://downdetector.com/status/att/ | Crowdsourced outage reports |

### BGP / routing tools

| Tool | URL | What to check |
|---|---|---|
| RIPE Stat | https://stat.ripe.net/ | BGP state, prefix visibility, origin ASN (**automated via `just network-status`**) |
| BGPview | https://bgpview.io/ | Peering relationships, prefix announcements (manual deep-dive only) |

### Looking glass / traceroute

| Tool | URL | What to check |
|---|---|---|
| AT&T Looking Glass | https://www.att.com/ipservices/lookingglass/ | Route from AT&T's perspective |
| Cloudflare Trace | https://one.one.one.one/cdn-cgi/trace | Your IP, colo, Cloudflare routing |

## Diagnostic Tools

> **Note:** The authoritative CLI reference is in `network/CLAUDE.md`. This section is a
> quick-reference subset. When in doubt, check `just --list` or `just unifi --help`.

```bash
# Live topology: device tree with uplink ports and radio state
just unifi topology                              # text tree (default)
just unifi topology --format mermaid             # mermaid diagram for docs
just unifi topology --format dot                 # graphviz DOT

# Quick network health check (AP retries + RF neighbors + watched device roaming)
just unifi checkup
just unifi checkup --sessions 3

# WiFi diagnostics: AP perspective
just unifi wifi aps                              # channels, utilization, retries, power
just unifi wifi aps --sort retries               # worst retries first
just unifi clients                               # all connected WiFi clients
just unifi client <hostname|ip>                  # detail for one client
just unifi wifi roaming                          # roaming for all watched devices
just unifi wifi roaming <hostname> --sessions 5  # roaming for one device
just unifi wifi rfscan --summary --fresh 60      # neighbor congestion summary
just unifi wifi config                           # SSID settings + per-AP power mode

# WiFi diagnostics: client perspective (run on any Mac)
just wifi-diag
just wifi-diag --no-trace --no-speed

# Infrastructure
just unifi devices                               # all adopted devices + firmware
just unifi usg wan-detail                        # WAN IP, gateway, DNS, counters
just bgw fiber                                   # BGW fiber signal / optical metrics
just bgw broadband                               # WAN connection status

# ISP and CDN status
just network-status                              # Cloudflare + Radar BGP + RIPE BGP state
just network-status 30318                        # + AT&T outage check by ZIP

# Raw API: last resort for debugging
just unifi api get /stat/device
just unifi api get /stat/sta
```
