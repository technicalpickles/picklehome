#!/usr/bin/env python3
"""
sonos_cli.py -- Sonos status checks

Usage:
    uv run python sonos/sonos_cli.py status     # health check against the roster
    uv run python sonos/sonos_cli.py roster     # print online speakers as roster YAML
    uv run python sonos/sonos_cli.py list       # raw list of discovered speakers

`status` exits non-zero when any expected speaker is offline or flagged, so it
works as a cron/CI health gate.
"""

import argparse
import sys
from pathlib import Path

from sonos.client import SonosError, discover_zones, read_speaker
from sonos.model import Speaker, reconcile
from sonos.roster import load_expected

DEFAULT_ROSTER = Path(__file__).parent / "config" / "speakers.yaml"


def _gather() -> tuple[list[Speaker], list[SonosError]]:
    """Discover and read every visible speaker.

    Reads each speaker independently so one unreachable unit doesn't sink the
    whole check; collected errors are returned for the caller to present.
    """
    speakers: list[Speaker] = []
    errors: list[SonosError] = []
    for zone in discover_zones():
        try:
            speakers.append(read_speaker(zone))
        except SonosError as err:
            errors.append(err)
    return speakers, errors


def _format_speaker(s: Speaker) -> str:
    parts = [f"vol {s.volume}"]
    if s.state and s.state != "UNKNOWN":
        parts.append(s.state.replace("_PLAYBACK", "").lower())
    if s.now_playing:
        parts.append(f"♪ {s.now_playing}")
    return "  ".join(parts)


def cmd_status(args: argparse.Namespace) -> int:
    expected = load_expected(args.roster)
    speakers, errors = _gather()
    report = reconcile(speakers, expected)

    for status in report.online:
        flag = "!" if status.issues else " "
        suffix = f"  [{', '.join(status.issues)}]" if status.issues else ""
        print(f"{flag} {status.name:18} {_format_speaker(status.speaker)}{suffix}")

    for status in report.offline:
        print(f"x {status.name:18} OFFLINE")

    for status in report.unexpected:
        print(f"? {status.name:18} not in roster (uid {status.speaker.uid})")

    for err in errors:
        print(f"! {err}", file=sys.stderr)

    print()
    if report.healthy and not errors:
        print(f"All {len(report.online)} speakers online and unmuted.")
        return 0

    problems = len(report.offline) + len(errors)
    muted = sum(1 for s in report.online if s.issues)
    summary = []
    if problems:
        summary.append(f"{problems} unreachable")
    if muted:
        summary.append(f"{muted} flagged")
    if report.unexpected:
        summary.append(f"{len(report.unexpected)} unexpected")
    print("Problems: " + ", ".join(summary) if summary else "Problems found.")
    return 1


def cmd_roster(args: argparse.Namespace) -> int:
    """Print discovered speakers as roster YAML (for seeding speakers.yaml)."""
    speakers, errors = _gather()
    for err in errors:
        print(f"# warning: {err}", file=sys.stderr)
    print("speakers:")
    for s in sorted(speakers, key=lambda s: s.name):
        print(f"  - name: {s.name}")
        print(f"    uid: {s.uid}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    speakers, errors = _gather()
    for s in sorted(speakers, key=lambda s: s.name):
        print(f"{s.name:18} {s.ip:15} {_format_speaker(s)}")
    for err in errors:
        print(f"! {err}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sonos status checks")
    parser.add_argument(
        "--roster",
        type=Path,
        default=DEFAULT_ROSTER,
        help=f"path to roster YAML (default: {DEFAULT_ROSTER})",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="health check against the roster")
    sub.add_parser("roster", help="print online speakers as roster YAML")
    sub.add_parser("list", help="raw list of discovered speakers")

    args = parser.parse_args(argv)
    dispatch = {
        "status": cmd_status,
        "roster": cmd_roster,
        "list": cmd_list,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
