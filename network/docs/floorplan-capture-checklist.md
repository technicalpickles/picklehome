# Floorplan Capture Checklist

What to annotate on the MagicPlan floorplan so future WiFi/RF reasoning is grounded in
measured facts instead of assumptions about range, adjacency, or materials. Fulfills
Phase 1 ("Spatial Foundation") of `docs/plans/2026-03-17-wifi-survey-agent-experiment.md`.

## Why this exists

Diagnosing the TV room WiFi issue (2026-08-20) repeatedly ran into the same wall: every
claim about "this AP should be closer/stronger than that one" was a guess based on room
names, not measured distance or known construction. `TOPOLOGY.md`'s AP table has
Floor/Mount/Antenna columns but no room-level layout, and the TV room isn't mentioned
anywhere in the docs. This checklist is the minimum annotation set to close that gap.

## On the floorplan itself

- **Every AP's exact position**, not just "which room" — mark the physical spot (e.g.
  "floor, southeast corner" or "ceiling, center"), matching what's already recorded in
  `TOPOLOGY.md`'s Mount column so the two stay consistent.
- **Room-to-room adjacency**, both floors — which walls are shared, where doorways/open
  passages are (an open doorway is a very different RF path than a load-bearing wall).
- **The open stairwell** connecting 1st and 2nd floor — already flagged in `TOPOLOGY.md`
  as a known RF path between Living Room and Upstairs; mark its footprint and which
  rooms on each floor open onto it.
- **Wall material, per wall segment that matters** — at minimum, flag any non-drywall
  wall: brick (Tracy Office's carport wall is already documented), concrete, block,
  masonry fireplace/chimney chases. Drywall/stud walls can be left unmarked (assume
  standard unless noted) — the goal is flagging the *exceptions* that cause unexpected
  RF loss, not exhaustively labeling every wall.
- **Floor/ceiling construction between levels** — especially under/around Upstairs AC HD
  and above Living Room AC LR and Josh Office AC Pro. Standard wood joist floor vs.
  concrete slab vs. anything with metal ductwork or HVAC returns running through it.
- **Large metal or RF-hostile objects** near any AP or in a room with known WiFi
  complaints: mirrors, metal furniture/appliances, ductwork, electrical panels,
  aquariums. These cause localized dead spots that distance/wall-material alone won't
  predict.
- **Measured distances** from each room with a known complaint (TV room, first) to each
  AP that's a realistic candidate for it — actual feet from the floorplan's scale, not
  paced-off estimates.

## Per-AP fields to confirm or correct (cross-check against `TOPOLOGY.md`)

For each of the 5 APs, note on/alongside the floorplan:

- Mount height and orientation (floor-facing-up vs. ceiling vs. under-desk) — confirm
  the existing table entries still match reality; APs get bumped, adjusted, obstructed
  by placed furniture over time.
- Antenna pattern (Living Room's high-gain focused beam vs. the standard omnis) —
  already documented, but worth marking directionality on the floorplan itself since a
  focused beam's coverage shape isn't intuitive from a room name.
- Anything placed directly in front of the AP since it was mounted (a moved couch,
  a new shelf, etc.)

## What NOT to spend time on yet

- Don't do a full NetSpot/WiFiMan signal-strength walk survey as part of this pass —
  that's gated in `docs/plans/2026-03-17-wifi-survey-agent-experiment.md` behind "if
  point measurements don't clearly explain the issue." This checklist is the free,
  no-tools-required layer; a walk survey is the next escalation if this doesn't resolve
  things.
- Don't try to label every stud wall's material — only the exceptions (see above).

## After capturing

See `docs/floorplan-markup-legend.md` for the actual symbols/colors to use when
annotating the export, the room-ID scheme (canonical registry in `TOPOLOGY.md`), and
the floor-alignment method. In short:

1. Export the annotated floorplan from MagicPlan (Sketch Files, not PDF/3D/Report).
2. Mark it up per the legend; store alongside the raw exports (see Storage note in
   `docs/floorplan-markup-legend.md` for current location — not committed, the image
   itself reveals physical layout).
3. Add a "Room Layout" section to `TOPOLOGY.md` summarizing the adjacency, distances,
   and material exceptions in text form (so it's greppable/readable without opening the
   floorplan file), and fill in/confirm the Room Registry table.
4. Update the AP table in `TOPOLOGY.md` if this pass surfaces any corrections (moved
   AP, changed obstruction, wrong mount description).
