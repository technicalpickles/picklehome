# Floorplan Markup Legend

How to mark up the MagicPlan export so it's consistent and machine/human-readable
later. Companion to `floorplan-capture-checklist.md` (what to capture) — this is *how*
to annotate it once you have the exported image.

Room IDs referenced here are the canonical ones in `TOPOLOGY.md`'s Room Registry —
don't invent room names/IDs on the floorplan that don't exist there; add new rooms to
the registry first, then mark them up.

## Symbols

| Symbol | Meaning |
|---|---|
| Blue filled dot | AP position (exact spot, not room-center) |
| Arrow from AP dot | Antenna direction, for directional/focused antennas (Living Room AC LR's high-gain beam). Omit for standard omnis. |
| Red outline on a wall segment | Non-drywall material — see Wall Material Colors below for which color/label to use |
| Dashed line (any color) | Floor/ceiling penetration between levels — stairwell opening, duct chase, open floor plan gap |
| Black text label, room center | Room ID (e.g. `1-tv-room`), not the common name — keeps it grep-able and unambiguous |
| Orange star | Known RF-hostile object (large metal furniture/appliance, mirror, electrical panel, aquarium) |

## Wall Material Colors

Only mark exceptions. Unmarked walls are assumed standard drywall/stud construction.

| Color | Material |
|---|---|
| Red | Brick |
| Gray | Block / concrete |
| Brown | Masonry (fireplace, chimney chase) |
| Orange | Metal (ductwork run, appliance-backed wall) |

## Floor Alignment

MagicPlan scans each floor independently — nothing ties a point on floor 1 to the point
directly above it on floor 2. Before annotating:

1. Pick 1-2 fixed reference points visible on both floor exports (stairwell edges, a
   chimney/duct chase, a distinctive exterior wall corner).
2. Note their approximate (x, y) position or overlay the two floor images in an editor
   to visually confirm vertical alignment (e.g. is `2-upstairs-tbd` actually directly
   above `1-tv-room`, or offset?).
3. Record the alignment method used (which reference points) alongside the exported
   files, so it can be redone/verified later without re-guessing.

## Workflow

1. Export "Sketch Files" from MagicPlan (per the conversation that led to this doc —
   Report PDF/3D Model/Statistics aren't the right format for markup or tool import).
2. Drop the raw export into `network/floorplan/` (symlinked to the vault; see below).
3. Duplicate it before marking up — keep the raw export untouched, annotate a copy.
4. Mark up using the symbols/colors above.
5. Update `TOPOLOGY.md`'s Room Registry: replace `tentative` rows with confirmed room
   IDs, add any missing rooms.
6. Add a short "Room Layout" text summary to `TOPOLOGY.md` (adjacency, materials,
   distances) referencing the room IDs, so the facts are readable without opening the
   image.

## Storage

Raw exports (PNG/JPG/SVG/DXF/PDF) live in `~/Dropbox/2108 Marann Dr Floor Plans/` —
moved here 2026-08-22 instead of the vault-symlinked `network/floorplan/`, since the
DXF exports are multi-MB and Dropbox handles that better than the vault sync. The
`network/floorplan/` symlink still exists (see `.claude/second-brain.local.md`) but is
currently unused; repurpose it for annotated/marked-up copies if that workflow gets
picked up. Either way, the floorplan image itself is not committed to this repo: it
reveals the home's physical layout, which is a different sensitivity class than the
network facts derived from it (room IDs, materials, adjacency — those *are* fine to
commit and live in `TOPOLOGY.md`).
