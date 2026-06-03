"""soco I/O: discover Sonos speakers and read their state.

This is the one module that talks to the network. It converts soco zone objects
into the pure `Speaker` dataclasses that the rest of the package reasons about.

Two soco details worth knowing (confirmed against the Home Assistant Sonos
integration, which uses soco too):

- We read `visible_zones`, not `all_zones`. A bonded set (a 5.1 home theater, a
  stereo pair) exposes several soco devices that share one zone name; only the
  visible coordinator should show up as a logical speaker.
- Volume and mute are per-speaker, but transport state ("what's playing") lives
  on the group coordinator. A grouped speaker reports its coordinator's track.
"""

from __future__ import annotations

import soco
from soco.exceptions import SoCoException

# soco rides on requests for its HTTP calls; a slow/declining speaker surfaces
# as a requests Timeout or a plain OSError at the socket layer.
try:
    from requests.exceptions import RequestException
except ImportError:  # pragma: no cover - requests is always present via soco
    RequestException = ()  # type: ignore[assignment]

from sonos.model import Speaker

_READ_ERRORS = (OSError, SoCoException, RequestException)


class SonosError(Exception):
    """A speaker could not be reached or read."""


def discover_zones(timeout: float = 10.0) -> list:
    """Return the visible soco zones on the LAN (may be empty if none answer)."""
    try:
        zones = soco.discover(timeout=timeout)
    except _READ_ERRORS as err:
        raise SonosError(f"Sonos discovery failed: {err}") from err

    if not zones:
        return []

    # Any one zone can enumerate the household's visible zones.
    anchor = next(iter(zones))
    try:
        return sorted(anchor.visible_zones, key=lambda z: z.player_name)
    except _READ_ERRORS as err:
        raise SonosError(f"Could not enumerate visible zones: {err}") from err


def read_speaker(zone) -> Speaker:
    """Read one zone into a Speaker, raising SonosError with context on failure."""
    name = getattr(zone, "player_name", None) or zone.ip_address
    try:
        coordinator = zone.group.coordinator if zone.group else zone
        transport = coordinator.get_current_transport_info()
        track = coordinator.get_current_track_info()
        return Speaker(
            uid=zone.uid,
            name=zone.player_name,
            ip=zone.ip_address,
            volume=zone.volume,
            muted=zone.mute,
            state=transport.get("current_transport_state", "UNKNOWN"),
            now_playing=_format_track(track),
        )
    except _READ_ERRORS as err:
        raise SonosError(f"Error reading speaker {name}: {err}") from err


def _format_track(track: dict) -> str:
    """Render now-playing as 'Title - Artist', omitting empty parts."""
    title = (track.get("title") or "").strip()
    artist = (track.get("artist") or "").strip()
    if title and artist:
        return f"{title} - {artist}"
    return title or artist
