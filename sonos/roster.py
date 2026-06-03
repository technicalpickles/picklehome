"""Load the expected-speakers roster from YAML.

The roster is what lets us flag a speaker as offline: discovery alone can only
report what answered, never what is missing. An entry's `uid` is filled in once
the speaker has been seen; a brand-new or currently-offline speaker can be
listed by name only and matched on name until its uid is known.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sonos.model import ExpectedSpeaker


def load_expected(path: str | Path) -> list[ExpectedSpeaker]:
    """Parse the roster YAML into a list of ExpectedSpeaker."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Roster not found: {path}")

    data = yaml.safe_load(path.read_text()) or {}
    entries = data.get("speakers") or []

    roster: list[ExpectedSpeaker] = []
    for entry in entries:
        name = entry.get("name")
        if not name:
            raise ValueError(f"Roster entry missing 'name': {entry!r}")
        roster.append(ExpectedSpeaker(name=name, uid=entry.get("uid")))
    return roster
