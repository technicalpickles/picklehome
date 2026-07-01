"""Named locations (Atlanta main house, MA beachhouse, ...).

Locations are discovered from 1Password at `just dotenv` time: every item tagged
`picklehome-location` is read and its fields snapshotted into the
PICKLEHOME_LOCATIONS env var as a JSON array (see scripts/dotenv). This module
parses that var at runtime; it never calls `op` itself.

Coords and station MACs are geolocatable, so they live only in .env (gitignored),
never a checked-in config file.

Falls back to the legacy single-home HOME_LAT/HOME_LON/AMBIENT_STATION_MACS vars
so weather and air-quality commands work before any tagged items exist.
"""

import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Location:
    slug: str
    label: str
    lat: float
    lon: float
    station_macs: list[str] = field(default_factory=list)
    # Whether this location has a thermostat this tooling manages (Atlanta does,
    # the beachhouse doesn't). Gates the comfort-mode recommendation in
    # `just climate-weather`, which is Ecobee-specific (smart1/smart2).
    comfort_mode: bool = False


def load_locations() -> list[Location]:
    """Parse PICKLEHOME_LOCATIONS, or synthesize one home from legacy env vars.

    Returns an empty list only when nothing at all is configured; callers that
    need at least one location should use resolve_locations() instead.
    """
    raw = os.environ.get("PICKLEHOME_LOCATIONS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"PICKLEHOME_LOCATIONS is not valid JSON: {e}. Re-run 'just dotenv'."
            ) from e
        locations = [_from_dict(d) for d in data]
        if locations:
            return locations

    # Legacy fallback: synthesize a single "home" from the original env vars.
    lat_str = os.environ.get("HOME_LAT", "")
    lon_str = os.environ.get("HOME_LON", "")
    if lat_str and lon_str:
        try:
            lat, lon = float(lat_str), float(lon_str)
        except ValueError as e:
            raise RuntimeError(
                f"HOME_LAT/HOME_LON are not valid floats: {lat_str!r}, {lon_str!r}"
            ) from e
        macs = _split_macs(os.environ.get("AMBIENT_STATION_MACS", ""))
        # Legacy single-home == the Atlanta thermostat setup, so it manages comfort.
        return [Location(slug="home", label="Home", lat=lat, lon=lon,
                         station_macs=macs, comfort_mode=True)]

    return []


def resolve_locations(slug: str | None = None) -> list[Location]:
    """All configured locations, or just the one matching `slug`.

    Raises RuntimeError (caught at the command boundary) when nothing is
    configured or the requested slug is unknown, rather than returning an empty
    list the caller has to second-guess.
    """
    locations = load_locations()
    if not locations:
        raise RuntimeError(
            "No locations configured. Set HOME_LAT/HOME_LON, or tag 1Password "
            "items with 'picklehome-location', then run 'just dotenv'."
        )
    if slug is None:
        return locations
    matches = [loc for loc in locations if loc.slug.lower() == slug.lower()]
    if not matches:
        available = ", ".join(loc.slug for loc in locations)
        raise RuntimeError(f"Unknown location {slug!r}. Available: {available}")
    return matches


def _from_dict(d: dict) -> Location:
    return Location(
        slug=d["slug"],
        label=d.get("label") or d["slug"],
        lat=float(d["lat"]),
        lon=float(d["lon"]),
        station_macs=list(d.get("station_macs", [])),
        comfort_mode=bool(d.get("comfort_mode", False)),
    )


def _split_macs(raw: str) -> list[str]:
    return [m.strip() for m in raw.split(",") if m.strip()]
