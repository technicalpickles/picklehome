# Floorplan GeoJSON Schema

Machine-readable companion to the visual markup in `floorplan-markup-legend.md`. Where
that doc produces an annotated image for a human to read, this schema produces
plain-text GeoJSON that code can parse: room polygons, wall materials, AP positions,
and adjacency.

Modeled on [IMDF](https://register.opengis.org/tenders/id/241cca7c-27a1-499e-b3aa-cd1a5c9d8bfa/)
(Apple's Indoor Mapping Data Format, an OGC Community Standard) rather than invented
from scratch — IMDF's `level`/`unit`/`opening` vocabulary maps directly onto our floors
and Room Registry, so we reuse its shape and extend it with two things IMDF doesn't
have: wall material and AP/antenna properties.

## Why GeoJSON over IndoorGML/gbXML/IFC

Those are real standards but built for institutional-scale problems (airport
navigation graphs, energy simulation, full BIM) with XML/EXPRESS tooling disproportionate
to documenting one house's ~15 rooms and 5 APs. See the research behind this doc for
the fuller comparison. GeoJSON is plain-text, diffable, and readable by `jq`, any map
library, or a five-line Python script — no BIM tooling required.

## Files and coordinate system

One `FeatureCollection` per floor, stored in `network/floorplan/`:

- `network/floorplan/floor-1.geojson`
- `network/floorplan/floor-2.geojson`

**Not GPS coordinates.** Each floor uses the same local (x, y) system, in **feet**,
sharing one origin and axis orientation across floors so a point on floor 1 and the
point directly above it on floor 2 have the same (x, y) — that's what makes multi-floor
alignment checkable instead of eyeballed. MagicPlan's own DXF export already gives each
floor a consistent per-floor origin; the Floor Alignment section of
`floorplan-markup-legend.md` covers tying the two floors' origins together (they're
independent between floors, per that section).

**Not committed to the repo.** Unlike the room-adjacency/material *prose* in
`TOPOLOGY.md` (deliberately kept generic — "roughly 10-15 ft through a single
doorway"), this GeoJSON's precision (exact room dimensions, label coordinates, door
positions) reveals the physical layout in the same way the raw floorplan image does —
same sensitivity class as the image, not as the prose. `network/floorplan/` is
gitignored for exactly that reason (see its entry in `.gitignore`); these files live
there, regenerable from the source exports, not committed.

## Feature types

### `room` (Polygon, or Point as an interim)

`Polygon` is the target once a room's true footprint is captured. Until then, a
`Point` at the room's label/center position (e.g. from the CAD export, or paced off
during the markup pass) is an acceptable interim geometry — better to record a
verified center point than a guessed polygon. `network/floorplan_dxf_to_geojson.py`'s
first pass does this: MagicPlan's DXF `walls` layer traces a continuous wall-ribbon
outline rather than one polygon per room, so real per-room polygons aren't
mechanically extractable from it without proper polygon reconstruction (e.g.
`shapely.ops.polygonize` on wall centerlines) — not attempted yet.

```json
{
  "type": "Feature",
  "properties": {
    "feature_type": "room",
    "room_id": "1-tv-room",
    "level": 1
  },
  "geometry": { "type": "Polygon", "coordinates": [[[x, y], ...]] }
}
```

`room_id` must match a row in `TOPOLOGY.md`'s Room Registry — don't invent IDs here
that don't exist there. A rough rectangular bounding box is fine to start; refine to
the true polygon later if it matters.

### `wall` (LineString)

```json
{
  "type": "Feature",
  "properties": {
    "feature_type": "wall",
    "material": "brick",
    "rooms": ["1-tracy-office"]
  },
  "geometry": { "type": "LineString", "coordinates": [[x1, y1], [x2, y2]] }
}
```

Only mark exceptions, same rule as the visual legend's Wall Material Colors table —
omit standard drywall/stud walls entirely rather than adding a `"drywall"` feature for
every segment. `material` is one of: `brick`, `block`, `concrete`, `masonry`, `metal`.

### `opening` (Point or LineString)

```json
{
  "type": "Feature",
  "properties": {
    "feature_type": "opening",
    "opening_type": "doorway",
    "connects": ["1-tv-room", "1-living-room"]
  },
  "geometry": { "type": "Point", "coordinates": [x, y] }
}
```

Captures room-to-room adjacency explicitly (doorway, open passage, stairwell opening)
rather than leaving it implicit in polygon boundaries. `opening_type`: `doorway`,
`open-passage`, or `floor-penetration` (stairwell, duct chase — the dashed-line symbol
in the visual legend).

### `ap` (Point)

```json
{
  "type": "Feature",
  "properties": {
    "feature_type": "ap",
    "name": "Living Room AC LR",
    "model_code": "U7LR",
    "mount": "floor, facing up",
    "antenna_pattern": "high-gain focused beam",
    "antenna_azimuth_deg": null,
    "level": 1
  },
  "geometry": { "type": "Point", "coordinates": [x, y] }
}
```

`name` and `model_code` should match the AP table in `TOPOLOGY.md` exactly, so the two
stay consistent. `antenna_azimuth_deg` is the compass-style direction the beam points
(0 = the floor's +y axis), only meaningful for directional/focused antennas — leave
`null` for standard omnis.

### `rf_hostile` (Point)

```json
{
  "type": "Feature",
  "properties": {
    "feature_type": "rf_hostile",
    "object": "mirror"
  },
  "geometry": { "type": "Point", "coordinates": [x, y] }
}
```

The orange-star symbol from the visual legend: large metal furniture/appliances,
mirrors, electrical panels, aquariums.

## Workflow

This is additive to `floorplan-markup-legend.md`'s workflow, not a replacement — the
visual markup pass is still how you *find* wall materials and RF-hostile objects by
looking at the real floorplan; this schema is how you *record* what that pass found in
a form code can read.

1. Do the visual markup pass as described in `floorplan-markup-legend.md`.
2. Transcribe the markup into `network/floorplan/floor-1.geojson` and
   `floor-2.geojson` using the feature types above.
3. Update `TOPOLOGY.md`'s Room Registry and Room Layout section as before — the prose
   summary and the GeoJSON should agree; the GeoJSON doesn't replace the human-readable
   text, it supplements it for anything that wants to compute with the data (e.g.
   distance from a complaint room to each candidate AP).
