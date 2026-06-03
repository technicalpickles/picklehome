"""Pure data model and reconciliation logic for Sonos status checks.

This module holds no I/O. `client.py` discovers speakers via soco and converts
them into `Speaker` instances; here we compare what was discovered against the
expected roster and classify each one. Keeping it pure makes the interesting
logic (offline detection, mute flagging) testable without mocking soco.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Speaker:
    """A discovered Sonos speaker (one visible zone)."""

    uid: str
    name: str
    ip: str
    volume: int
    muted: bool
    state: str = "UNKNOWN"  # transport state: PLAYING / PAUSED_PLAYBACK / STOPPED
    now_playing: str = ""


@dataclass(frozen=True)
class ExpectedSpeaker:
    """A speaker we expect to find on the network.

    `uid` is the stable identity (`RINCON_...`) and is preferred for matching.
    It may be None for a speaker that was offline when the roster was written,
    in which case matching falls back to the name.
    """

    name: str
    uid: str | None = None


class Health(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class SpeakerStatus:
    name: str
    health: Health
    speaker: Speaker | None = None
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class StatusReport:
    statuses: list[SpeakerStatus] = field(default_factory=list)

    @property
    def online(self) -> list[SpeakerStatus]:
        return [s for s in self.statuses if s.health is Health.ONLINE]

    @property
    def offline(self) -> list[SpeakerStatus]:
        return [s for s in self.statuses if s.health is Health.OFFLINE]

    @property
    def unexpected(self) -> list[SpeakerStatus]:
        return [s for s in self.statuses if s.health is Health.UNEXPECTED]

    @property
    def healthy(self) -> bool:
        """True when every expected speaker is online with no issues."""
        return all(
            s.health is Health.ONLINE and not s.issues for s in self.statuses
        )


def _issues(speaker: Speaker) -> tuple[str, ...]:
    """Flag anything notable about an online speaker."""
    issues: list[str] = []
    if speaker.muted:
        issues.append("muted")
    return tuple(issues)


def _match(exp: ExpectedSpeaker, discovered: list[Speaker]) -> Speaker | None:
    """Find the discovered speaker for an expected one, by uid then name."""
    if exp.uid is not None:
        for speaker in discovered:
            if speaker.uid == exp.uid:
                return speaker
    for speaker in discovered:
        if speaker.name.casefold() == exp.name.casefold():
            return speaker
    return None


def reconcile(
    discovered: list[Speaker], expected: list[ExpectedSpeaker]
) -> StatusReport:
    """Compare discovered speakers against the expected roster."""
    statuses: list[SpeakerStatus] = []
    matched: set[str] = set()
    for exp in expected:
        match = _match(exp, discovered)
        if match is None:
            statuses.append(SpeakerStatus(name=exp.name, health=Health.OFFLINE))
        else:
            matched.add(match.uid)
            statuses.append(
                SpeakerStatus(
                    name=exp.name,
                    health=Health.ONLINE,
                    speaker=match,
                    issues=_issues(match),
                )
            )
    for speaker in discovered:
        if speaker.uid not in matched:
            statuses.append(
                SpeakerStatus(
                    name=speaker.name,
                    health=Health.UNEXPECTED,
                    speaker=speaker,
                )
            )
    return StatusReport(statuses=statuses)
