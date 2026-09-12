"""Build first-pass GeoJSON per docs/floorplan-geojson-schema.md from the MagicPlan
exports (DXF + Report PDF) in ~/Dropbox/2108 Marann Dr Floor Plans/.

Two data sources, combined:

- The DXF's `texts` layer gives each room's label position (x, y in feet), reliable
  and precise. Its `walls` layer, tried first, turned out to be a continuous
  wall-ribbon outline (goes out one face of each wall and back the other), not a
  closed polygon per room -- shoelace area on it comes out as wall footprint, not
  floor area. Getting real room polygons from that needs proper polygon
  reconstruction (e.g. `shapely.ops.polygonize` on the wall centerlines) -- not
  attempted here; ROOM_SCHEDULE's width/length below is the authoritative substitute
  for now.
- The Report PDF's per-room pages give MagicPlan's own measured width/length/area/
  perimeter/ceiling height -- authoritative, hand-transcribed into ROOM_SCHEDULE below
  (MagicPlan doesn't export this as structured data, only as the rendered PDF).

Several room names repeat on the same floor (two "Bathroom"s, several "Other"s, two
"Closet"s). The DXF text position alone can't disambiguate which schedule entry is
which physical room, but the Report PDF's per-room pages each carry a small greyed-out
floor thumbnail with the room highlighted -- cross-referencing those thumbnails
(rendered at 400dpi via `pdftoppm`, cropped to the thumbnail, eyeballed against this
script's own annotated DXF plot) against the DXF label clusters resolved every
duplicate-named room manually. Those manual results are hardcoded in
MANUAL_POSITIONS below rather than re-derived at runtime (there's no automated way to
read the PDF thumbnails), keyed by (level, name, area_sqft) since area is the only
column that's unique per duplicate-named row.

Usage:
    uv run --with ezdxf network/floorplan_dxf_to_geojson.py

Writes network/floorplan/floor-{1,2}.geojson and floor-{1,2}-distances.json.
Gitignored, not committed -- see floorplan-geojson-schema.md's Storage section.
"""

import itertools
import json
import math
import re
from pathlib import Path

import ezdxf

DXF_DIR = Path.home() / "Dropbox" / "2108 Marann Dr Floor Plans"
OUT_DIR = Path(__file__).parent / "floorplan"

FLOORS = [
    (1, DXF_DIR / "Atlanta - 1st Floor.dxf"),
    (2, DXF_DIR / "Atlanta - 2nd Floor.dxf"),
]

FT_IN = re.compile(r"(\d+)'\s*(?:(\d+)(?:\s+(\d+)/(\d+))?)?\"?")


def ft(feet_inches):
    """Parse a MagicPlan dimension like '12\\'4"' or '15\\'2 3/4"' into decimal feet."""
    m = FT_IN.match(feet_inches.strip())
    feet = int(m.group(1))
    inches = int(m.group(2) or 0)
    if m.group(3):
        inches += int(m.group(3)) / int(m.group(4))
    return round(feet + inches / 12, 4)


# Transcribed from Atlanta Report.pdf's per-room pages (width x length, area,
# perimeter, ceiling height). MagicPlan doesn't export this as structured data.
_RAW_SCHEDULE = [
    # (level, name, width, length, area_sqft, perimeter, ceiling_height)
    (1, "Bathroom", "6'3 1/2\"", "7'6\"", 47.27, "27'7 1/4\"", "12'1 3/4\""),
    (1, "Bathroom", "4'8 1/4\"", "5'6 1/2\"", 25.99, "20'5 1/2\"", "12'1 3/4\""),
    (1, "Dining Room", "10'6 3/4\"", "11'2\"", 118.13, "43'6\"", "9'4 1/2\""),
    (1, "Entry", "5'1/4\"", "7'8 1/4\"", 38.56, "25'4 3/4\"", "8'3 1/4\""),
    (1, "Gym Bathroom", "12'4\"", "19'10 1/4\"", 214.69, "64'4 1/2\"", "12'1 3/4\""),
    (1, "Josh Office", "12'6\"", "11'", 120.26, "47'1/4\"", "12'1 3/4\""),
    (1, "Kitchen", "11'8 1/2\"", "11'1 1/2\"", 130.36, "45'8 1/4\"", "8'3 1/4\""),
    (1, "Living Room", "35'4 1/2\"", "17'9 3/4\"", 433.40, "108'6 3/4\"", "12'1 3/4\""),
    (1, "Other", "11'2\"", "9'4 1/2\"", 104.81, "41'1 1/4\"", "8'3 1/4\""),
    (1, "Other", "5'4 3/4\"", "1'11 1/2\"", 10.63, "14'8 3/4\"", "8'3 1/4\""),
    (1, "Shower", "8'3 3/4\"", "4'11\"", 40.77, "26'5 1/4\"", "12'1 3/4\""),
    (1, "TV Room", "16'6 1/4\"", "15'1 1/4\"", 249.43, "63'2 3/4\"", "12'1 3/4\""),
    (1, "Tracy Office", "11'2\"", "8'6 1/4\"", 95.27, "39'4 3/4\"", "8'3 1/4\""),
    (2, "Bathroom", "8'6 1/4\"", "16'9 1/2\"", 130.57, "65'3/4\"", "8'1/2\""),
    (2, "Closet", "7'7 1/4\"", "10'4\"", 75.49, "38'3/4\"", "8'1/2\""),
    (2, "Bedroom", "15'2 3/4\"", "15'7 1/2\"", 237.98, "61'8 1/2\"", "8'1/2\""),
    (2, "Laundry", "3'", "7'6 3/4\"", 22.61, "21'1 1/4\"", "8'1/2\""),
    (2, "Storage", "6'6 3/4\"", "11'1 1/2\"", 73.03, "35'4 1/2\"", "8'1/2\""),
    (2, "Hallway", "16'3 1/4\"", "21'1\"", 211.66, "74'8 1/2\"", "8'1/2\""),
    (2, "Playroom", "13'1 1/2\"", "11'7 1/4\"", 152.47, "49'5 3/4\"", "8'1/2\""),
    (2, "Other", "5'7 1/4\"", "3'6\"", 19.58, "18'2 1/2\"", "8'1/2\""),
    (2, "Other", "3'6 3/4\"", "1'4 3/4\"", 5.00, "9'11 1/4\"", "8'1/2\""),
    (2, "Other", "4'1\"", "3'3 1/4\"", 13.28, "14'8\"", "8'1/2\""),
    (2, "Alex Bedroom", "15'6 3/4\"", "12'6\"", 146.87, "56'1 1/4\"", "8'1/2\""),
    (2, "Bathroom", "5'6\"", "11'4 3/4\"", 62.73, "33'9 1/2\"", "8'1/2\""),
    (2, "Closet", "5'8 3/4\"", "8'9 1/2\"", 50.38, "29'1/4\"", "8'1/2\""),
]

# Resolved by cross-referencing each duplicate-named room's Report PDF thumbnail
# against the DXF label cluster positions (see module docstring). Confirms which
# physical room each (level, name, area_sqft) schedule row is, but doesn't confirm
# room *purpose* beyond what MagicPlan's own "Other" classification already tells us --
# that's still an in-person question (docs/floorplan-capture-checklist.md).
MANUAL_POSITIONS = {
    (1, "Bathroom", 47.27): (-3.53, -11.13),  # powder room off the stairwell nook
    (1, "Bathroom", 25.99): (-24.11, -11.36),  # small bathroom by Josh's Office
    (1, "Other", 104.81): (29.66, -10.04),  # furnished room below Tracy's Office
    (1, "Other", 10.63): (12.17, -2.19),  # small nook off the Living Room
    (2, "Bathroom", 130.57): (-27.48, 11.28),  # 2-bathroom -- x lines up with 1-gym-bathroom
    (2, "Bathroom", 62.73): (9.08, 8.48),  # east bathroom near the Playroom
    (2, "Closet", 75.49): (-19.26, 7.22),  # west closet near the Hallway
    (2, "Closet", 50.38): (9.68, 22.85),  # closet directly off Alex's Bedroom
    (2, "Other", 19.58): (10.14, 16.34),
    (2, "Other", 5.00): (0.72, 15.49),
    (2, "Other", 13.28): (4.97, 16.29),
}

# room_id only assigned where the name is unambiguous (occurs once on that floor) or
# resolved via MANUAL_POSITIONS above, AND is already in TOPOLOGY.md's Room Registry.
ROOM_ID_MAP = {
    (1, "Gym Bathroom"): "1-gym-bathroom",
    (1, "TV Room"): "1-tv-room",
    (1, "Entry"): "1-entry",
    (1, "Living Room"): "1-living-room",
    (1, "Tracy Office"): "1-tracy-office",
    (1, "Kitchen"): "1-kitchen",
    (1, "Dining Room"): "1-dining-room",
    (1, "Josh Office"): "1-josh-office",
    (1, "Shower"): "1-shower",
    (1, "Bathroom", 47.27): "1-powder-room",
    (1, "Bathroom", 25.99): "1-office-bathroom",
    (1, "Other", 104.81): "1-tracy-annex",
    (1, "Other", 10.63): "1-living-room-closet",
    (2, "Alex Bedroom"): "2-alex-bedroom",
    (2, "Storage"): "2-storage",
    (2, "Bedroom"): "2-bedroom",
    (2, "Playroom"): "2-playroom",
    (2, "Laundry"): "2-laundry",
    (2, "Hallway"): "2-hallway",
    (2, "Bathroom", 130.57): "2-bathroom",  # already registered; x=-27.48 lines up with 1-gym-bathroom's x=-27.11
    (2, "Bathroom", 62.73): "2-bathroom-east",
    (2, "Closet", 75.49): "2-closet-hallway",
    (2, "Closet", 50.38): "2-closet-alex",
    (2, "Other", 19.58): "2-nook-a",
    (2, "Other", 5.00): "2-nook-b",
    (2, "Other", 13.28): "2-nook-c",
}


# Markup pass (2026-09-01, via the floorplan-playground room/markup editor): wall
# material exceptions, AP positions, and RF-hostile objects, hand-placed by clicking
# the DXF-derived floor plan. Positions are click-precision (~feet), not surveyed.
# Wall segments are keyed by their DXF wall-polyline endpoints, matching the walls
# layer's own geometry (see label_positions()/build_floor() below) rather than a
# separate coordinate system.
MARKUP_WALLS = {
    1: [
        {"material": "brick", "rooms": [], "coords": [[-12.83, 17.8], [-8.48, 17.8]]},
        {"material": "brick", "rooms": [], "coords": [[-4.84, 17.8], [-1.64, 17.8]]},
        {"material": "brick", "rooms": [], "coords": [[-19.56, 17.8], [-16.44, 17.8]]},
        {"material": "masonry", "rooms": [], "coords": [[10.65, -1.53], [16.83, -1.53]]},
        {"material": "brick", "rooms": [], "coords": [[16.6, -16.27], [10.45, -16.27]]},
        {"material": "brick", "rooms": [], "coords": [[22.17, -15.41], [25.32, -15.41]]},
        {"material": "brick", "rooms": ["1-tracy-office"], "coords": [[25.32, -15.41], [25.32, -9.28]]},
        {"material": "brick", "rooms": ["1-tracy-office"], "coords": [[25.73, 2.92], [25.73, -5.61]]},
        {"material": "brick", "rooms": ["1-tracy-office"], "coords": [[25.33, -3.89], [25.33, 8.5]]},
        {"material": "brick", "rooms": [], "coords": [[4.94, -16.27], [-0.5, -16.27]]},
        {"material": "brick", "rooms": [], "coords": [[-19.56, 5.93], [-19.56, 17.8]]},
        {"material": "brick", "rooms": [], "coords": [[-18.74, -14.81], [-9.73, -14.81]]},
        {"material": "brick", "rooms": [], "coords": [[0.92, 17.77], [4.02, 17.77]]},
        {"material": "brick", "rooms": [], "coords": [[3.2, 14.91], [3.2, 16.95]]},
        {"material": "brick", "rooms": [], "coords": [[3.2, 8.87], [3.2, 11.95]]},
        {"material": "brick", "rooms": [], "coords": [[6.6, 8.87], [3.2, 8.87]]},
        {"material": "brick", "rooms": [], "coords": [[7.08, 9.89], [7.34, 9.11]]},
        {"material": "brick", "rooms": [], "coords": [[10.79, 10.26], [10.53, 11.04]]},
        {"material": "brick", "rooms": [], "coords": [[17.03, 10.26], [17.03, 11.08]]},
        {"material": "brick", "rooms": [], "coords": [[18.13, 10.79], [17.79, 10.04]]},
        {"material": "brick", "rooms": [], "coords": [[7.34, 9.11], [6.6, 8.87]]},
        {"material": "brick", "rooms": [], "coords": [[10.97, 10.26], [10.79, 10.26]]},
        {"material": "brick", "rooms": [], "coords": [[10.53, 11.04], [10.66, 11.08]]},
        {"material": "brick", "rooms": [], "coords": [[10.66, 11.08], [10.97, 11.08]]},
        {"material": "brick", "rooms": [], "coords": [[4.02, 9.69], [6.47, 9.69]]},
        {"material": "brick", "rooms": [], "coords": [[3.2, 16.95], [0.92, 16.95]]},
        {"material": "brick", "rooms": [], "coords": [[0.92, 16.95], [0.92, 17.77]]},
        {"material": "brick", "rooms": [], "coords": [[17.03, 11.08], [17.5, 11.08]]},
        {"material": "brick", "rooms": [], "coords": [[17.79, 10.04], [17.32, 10.26]]},
        {"material": "brick", "rooms": [], "coords": [[20.44, 8.82], [20.78, 9.57]]},
        {"material": "brick", "rooms": [], "coords": [[21.31, 9.32], [26.15, 9.32]]},
        {"material": "brick", "rooms": [], "coords": [[25.33, 8.5], [21.13, 8.5]]},
        {"material": "brick", "rooms": ["1-tracy-office"], "coords": [[28.71, -16.23], [22.17, -16.23]]},
        {"material": "brick", "rooms": [], "coords": [[-9.73, -15.63], [-20.75, -15.63]]},
        {"material": "brick", "rooms": [], "coords": [[-19.14, -14.78], [-19.14, -9.24]]},
        {"material": "brick", "rooms": [], "coords": [[-5.42, -15.63], [-6.93, -15.63]]},
        {"material": "brick", "rooms": [], "coords": [[-1.82, 16.95], [-1.82, 9.27]]},
    ],
    2: [
        {"material": "brick", "rooms": [], "coords": [[-30.96, 18.68], [-30.96, 35.55]]},
        {"material": "brick", "rooms": [], "coords": [[-30.96, 1.49], [-30.96, 18.68]]},
        {"material": "brick", "rooms": [], "coords": [[-29.63, 1.49], [-30.96, 1.49]]},
        {"material": "brick", "rooms": [], "coords": [[-16.31, 1.49], [-24.81, 1.49]]},
        {"material": "brick", "rooms": [], "coords": [[-11.32, 1.31], [-16.31, 1.31]]},
        {"material": "brick", "rooms": [], "coords": [[-8.04, 1.3], [-11.32, 1.31]]},
        {"material": "brick", "rooms": [], "coords": [[5.56, 1.3], [-5.32, 1.31]]},
        {"material": "brick", "rooms": [], "coords": [[15.28, 1.3], [8.0, 1.3]]},
        {"material": "brick", "rooms": [], "coords": [[15.28, 5.94], [15.28, 1.3]]},
        {"material": "brick", "rooms": [], "coords": [[14.46, 8.62], [14.46, 13.52]]},
        {"material": "brick", "rooms": [], "coords": [[14.48, 13.91], [14.48, 17.4]]},
        {"material": "brick", "rooms": [], "coords": [[14.51, 17.8], [14.51, 26.59]]},
        {"material": "brick", "rooms": [], "coords": [[11.77, 27.41], [15.33, 27.41]]},
        {"material": "brick", "rooms": [], "coords": [[5.07, 27.45], [9.26, 27.45]]},
        {"material": "brick", "rooms": [], "coords": [[-1.34, 27.45], [2.41, 27.45]]},
        {"material": "brick", "rooms": [], "coords": [[-6.74, 27.45], [-4.0, 27.45]]},
        {"material": "brick", "rooms": [], "coords": [[-7.56, 23.62], [-7.55, 34.74]]},
        {"material": "brick", "rooms": [], "coords": [[-10.28, 35.56], [-6.73, 35.56]]},
        {"material": "brick", "rooms": [], "coords": [[-17.29, 35.56], [-12.87, 35.56]]},
        {"material": "brick", "rooms": [], "coords": [[-24.28, 35.55], [-19.87, 35.55]]},
        {"material": "brick", "rooms": [], "coords": [[-30.96, 35.55], [-26.86, 35.55]]},
    ],
}

# name/model_code/mount/antenna_pattern must match TOPOLOGY.md's AP table. Two of
# these came out of the markup UI with stale model_code/mount/antenna_pattern (a bug
# in the editor's AP-name dropdown: picking a different AP from the list didn't
# refresh the model/mount/antenna text fields before they were read back); the values
# below are corrected to match TOPOLOGY.md, not the raw tool output.
MARKUP_APS = {
    1: [
        {"name": "Josh Office AC Pro", "model_code": "U7PG2", "mount": "Floor under desk, facing up", "antenna_pattern": "Standard omni", "antenna_azimuth_deg": None, "coords": [-6.73, -12.45]},
        {"name": "Tracy Office AC Pro", "model_code": "U7PG2", "mount": "Floor, facing up", "antenna_pattern": "Standard omni", "antenna_azimuth_deg": None, "coords": [27.6, -3.91]},
        {"name": "Living Room AC LR", "model_code": "U7LR", "mount": "Wall, facing in", "antenna_pattern": "High-gain focused beam", "antenna_azimuth_deg": None, "coords": [-1.06, 4.48]},
    ],
    2: [
        {"name": "Upstairs AC HD", "model_code": "U7HD", "mount": "Ceiling, facing down", "antenna_pattern": "Wide uniform", "antenna_azimuth_deg": None, "coords": [-7.05, 17.93]},
    ],
}

MARKUP_RF_HOSTILE = {
    1: [
        {"object": "electric panel", "coords": [-18.23, -8.62]},
        {"object": "mirror", "coords": [-31.09, -3.19]},
        {"object": "mirror", "coords": [-3.2, -10.2]},
        {"object": "fireplace", "coords": [14.15, -0.65]},
    ],
    2: [
        {"object": "mirror", "coords": [-22.48, 15.38]},
        {"object": "mirror", "coords": [12.88, 11.36]},
    ],
}


def decode_dxf_unicode(text):
    """MagicPlan DXF TEXT entities encode every char as a literal \\U+XXXX escape
    rather than real unicode -- decode them back."""
    return re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), text)


def cluster_texts(texts, threshold=3.0):
    """Group nearby TEXT entities (MagicPlan renders each line of a room label as a
    separate TEXT entity) via single-linkage clustering on insertion point distance."""
    remaining = list(texts)
    clusters = []
    while remaining:
        cluster = [remaining.pop()]
        changed = True
        while changed:
            changed = False
            for t in remaining[:]:
                if any(
                    math.dist((t.dxf.insert.x, t.dxf.insert.y), (c.dxf.insert.x, c.dxf.insert.y))
                    < threshold
                    for c in cluster
                ):
                    cluster.append(t)
                    remaining.remove(t)
                    changed = True
        clusters.append(cluster)
    return clusters


def cluster_label(cluster):
    ordered = sorted(cluster, key=lambda t: (-t.dxf.insert.y, t.dxf.insert.x))
    return " ".join(decode_dxf_unicode(t.dxf.text) for t in ordered)


def cluster_centroid(cluster):
    xs = [t.dxf.insert.x for t in cluster]
    ys = [t.dxf.insert.y for t in cluster]
    return (round(sum(xs) / len(xs), 2), round(sum(ys) / len(ys), 2))


def label_positions(dxf_path):
    """name -> list of (x, y) positions of every label with that name on this floor."""
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    texts = [t for t in msp.query("TEXT") if t.dxf.layer == "texts"]
    positions = {}
    for cluster in cluster_texts(texts):
        name = cluster_label(cluster)
        positions.setdefault(name, []).append(cluster_centroid(cluster))
    return positions


def door_features(level, dxf_path):
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    features = []
    for e in msp.query("INSERT"):
        if e.dxf.layer != "doors":
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "feature_type": "opening",
                    "opening_type": "doorway",
                    "block_name": e.dxf.name,
                    "rotation_deg": round(e.dxf.rotation, 1),
                    "level": level,
                    "connects": None,  # not derivable from CAD alone; fill in by hand
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(e.dxf.insert.x, 2), round(e.dxf.insert.y, 2)],
                },
            }
        )
    return features


def markup_features(level):
    """wall/ap/rf_hostile features from the MARKUP_* hand-placed markup pass."""
    features = []
    for w in MARKUP_WALLS.get(level, []):
        features.append(
            {
                "type": "Feature",
                "properties": {"feature_type": "wall", "material": w["material"], "rooms": w["rooms"]},
                "geometry": {"type": "LineString", "coordinates": w["coords"]},
            }
        )
    for a in MARKUP_APS.get(level, []):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "feature_type": "ap",
                    "name": a["name"],
                    "model_code": a["model_code"],
                    "mount": a["mount"],
                    "antenna_pattern": a["antenna_pattern"],
                    "antenna_azimuth_deg": a["antenna_azimuth_deg"],
                    "level": level,
                },
                "geometry": {"type": "Point", "coordinates": a["coords"]},
            }
        )
    for r in MARKUP_RF_HOSTILE.get(level, []):
        features.append(
            {
                "type": "Feature",
                "properties": {"feature_type": "rf_hostile", "object": r["object"]},
                "geometry": {"type": "Point", "coordinates": r["coords"]},
            }
        )
    return features


def build_floor(level, dxf_path):
    positions = label_positions(dxf_path)
    schedule = [r for r in _RAW_SCHEDULE if r[0] == level]

    room_features = []
    ambiguous = []
    for lvl, name, w, l, area, perim, ceil in schedule:
        candidates = positions.get(name, [])
        if len(candidates) == 1:
            position = candidates[0]
            room_id = ROOM_ID_MAP.get((level, name))
        elif (level, name, area) in MANUAL_POSITIONS:
            position = MANUAL_POSITIONS[(level, name, area)]
            room_id = ROOM_ID_MAP.get((level, name, area))
        else:
            position = None
            room_id = None
            ambiguous.append(name)

        room_features.append(
            {
                "type": "Feature",
                "properties": {
                    "feature_type": "room",
                    "room_id": room_id,
                    "label_raw": name,
                    "level": level,
                    "width_ft": ft(w),
                    "length_ft": ft(l),
                    "area_sqft": area,
                    "perimeter_ft": ft(perim),
                    "ceiling_height_ft": ft(ceil),
                },
                "geometry": {"type": "Point", "coordinates": list(position)} if position else None,
            }
        )

    fc = {
        "type": "FeatureCollection",
        "properties": {
            "level": level,
            "source": [
                str(dxf_path.relative_to(Path.home())),
                str((dxf_path.parent / "Atlanta Report.pdf").relative_to(Path.home())),
            ],
            "units": "feet",
            "note": (
                "Room geometry is a Point at the label position (from DXF), not a "
                "polygon -- true room footprints need the markup pass "
                "(floorplan-capture-checklist.md) or polygon reconstruction from wall "
                "centerlines. width_ft/length_ft/area_sqft/perimeter_ft/"
                "ceiling_height_ft are from MagicPlan's own measurements (Report PDF). "
                "Repeated room names on this floor were disambiguated by cross-"
                "referencing the Report PDF's per-room thumbnails against the DXF "
                "label positions (see MANUAL_POSITIONS in this script) -- a desk "
                "exercise, not in-person verification. Any name still listed in "
                "ambiguous_labels had no PDF thumbnail to resolve it against and is "
                "left with position/room_id null."
            ),
            "ambiguous_labels": sorted(set(ambiguous)),
        },
        "features": room_features + door_features(level, dxf_path) + markup_features(level),
    }

    located = [f for f in room_features if f["geometry"]]
    distances = {}
    for a, b in itertools.combinations(located, 2):
        key = f"{a['properties']['label_raw']} <-> {b['properties']['label_raw']}"
        distances[key] = round(
            math.dist(a["geometry"]["coordinates"], b["geometry"]["coordinates"]), 1
        )

    return fc, distances


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for level, dxf_path in FLOORS:
        fc, distances = build_floor(level, dxf_path)

        geojson_path = OUT_DIR / f"floor-{level}.geojson"
        geojson_path.write_text(json.dumps(fc, indent=2) + "\n")

        distances_path = OUT_DIR / f"floor-{level}-distances.json"
        distances_path.write_text(
            json.dumps(
                {
                    "level": level,
                    "units": "feet (label position to label position, unambiguous rooms only)",
                    "distances": distances,
                },
                indent=2,
            )
            + "\n"
        )

        n_rooms = sum(1 for f in fc["features"] if f["properties"]["feature_type"] == "room")
        n_located = sum(1 for f in fc["features"] if f["properties"]["feature_type"] == "room" and f["geometry"])
        n_markup = len(markup_features(level))
        print(f"Floor {level}: {n_rooms} rooms ({n_located} positioned), {n_markup} markup features -> {geojson_path}")
        if fc["properties"]["ambiguous_labels"]:
            print(f"  Ambiguous (position/room_id left null): {fc['properties']['ambiguous_labels']}")
        print(f"  Distance matrix ({len(distances)} pairs) -> {distances_path}")


if __name__ == "__main__":
    main()
