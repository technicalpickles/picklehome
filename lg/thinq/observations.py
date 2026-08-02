"""Append-only observation log + transition queries over a JSONL file.

This module knows nothing about LG, washers, or dryers. It appends one JSON
record per (device_id, timestamp, fields) and can answer "did a given numeric
field increase, and how confidently can we say when". client.py and lg_cli.py
decide what goes in `fields` (state, cycle_count, etc.) and what the resulting
increase means; this module just does the bookkeeping.

Why this exists at all: the API reports current state, not when it changed.
A CLI process that lives under a second can't know a cycle ended two hours
ago on its own -- it has to compare today's reading against what a previous
invocation observed. See docs/plans/2026-08-02-lg-thinq-design.md,
"The observation log".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Below this gap between the last-seen-lower-value record and the
# first-seen-at-or-above-current-value record, we trust the detection time
# enough to report a precise "finished N ago". Above it, we can only bound
# the window ("sometime in the last N"). This is deliberately generous for a
# CLI that runs on demand rather than a continuously-sampling watcher.
DEFAULT_PRECISE_THRESHOLD = timedelta(minutes=10)


def append_observation(log_path: Path, device_id: str, timestamp: datetime, fields: dict[str, Any]) -> None:
    """Append one record to the JSONL log. Creates parent directories as needed.

    Raises OSError on write failure (disk full, bad permissions) -- callers
    per repo convention should catch this at the CLI boundary and warn rather
    than fail the command, since the status read is the point and the log is
    a side effect.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": timestamp.isoformat(), "device_id": device_id, "fields": fields}
    with log_path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def read_observations(log_path: Path) -> list[dict[str, Any]]:
    """Read all records, parsing `timestamp` back to a datetime.

    Missing file reads as empty (nothing has been observed yet). Individual
    unparseable lines are skipped rather than failing the whole read -- a
    single corrupt line (e.g. a truncated write from a crash) shouldn't take
    down every future read of the log.
    """
    if not log_path.exists():
        return []

    records: list[dict[str, Any]] = []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                timestamp = datetime.fromisoformat(raw["timestamp"])
                if timestamp.tzinfo is None:
                    # A naive timestamp sorts and compares incompatibly with
                    # the aware ones this module always writes (see
                    # append_observation/_log_result, both `.astimezone()`),
                    # and would raise TypeError the moment
                    # find_counter_increment tries to sort past it -- taking
                    # down every future read of the log with it, not just
                    # this record. A future watcher process is exactly the
                    # kind of author likely to write `datetime.now().isoformat()`
                    # without a zone, so treat this the same as a corrupt
                    # line: skip it, don't propagate.
                    raise ValueError("naive timestamp (missing UTC offset)")
                raw["timestamp"] = timestamp
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                continue
            records.append(raw)
    return records


@dataclass
class CompletionEstimate:
    """The result of finding a counter increment in the log, as two explicit bounds.

    This replaces an earlier single `span` field whose meaning silently
    flipped depending on a `precise` flag -- that overloading is exactly what
    let a wrong-direction bug ship: the imprecise branch rendered the width
    of the detection *window* as if it were the time elapsed since
    completion, understating "finished 7 days ago" as "in the last 24h".
    Two named bounds make that particular wrong output unrepresentable.

    earliest_ago: the MINIMUM time elapsed since completion -- how long ago
        `current_value` was first observed (`first_high`). Zero when this
        call is the first time we're seeing it (no `first_high` in the log
        yet, so "first observed" is `now`).
    latest_ago: the MAXIMUM time that could have elapsed -- how long ago the
        field was last seen below `current_value` (`last_low`). Always
        >= earliest_ago.
    threshold: how tight `latest_ago - earliest_ago` must be to render a
        single point-in-time claim ("about X ago") instead of a range.
    """

    earliest_ago: timedelta
    latest_ago: timedelta
    threshold: timedelta = DEFAULT_PRECISE_THRESHOLD

    def describe(self) -> str:
        # The increment was first observed on this very invocation: we only
        # know it happened somewhere in [now - latest_ago, now]. Never claim
        # a point estimate here -- that's how a 9-minute-old completion
        # rendered as "finished less than a minute ago" (finding #4).
        if self.earliest_ago <= timedelta(0):
            return f"finished within the last {_format_duration(self.latest_ago)}"

        window = self.latest_ago - self.earliest_ago
        if window <= self.threshold:
            return f"finished about {_format_duration(self.earliest_ago)} ago"

        return (
            f"finished between {_format_duration(self.earliest_ago)} "
            f"and {_format_duration(self.latest_ago)} ago"
        )


def find_counter_increment(
    records: list[dict[str, Any]],
    device_id: str,
    field: str,
    current_value: Any,
    now: datetime,
    precise_threshold: timedelta = DEFAULT_PRECISE_THRESHOLD,
) -> CompletionEstimate | None:
    """Find whether `field` increased to `current_value` for `device_id`, bounded by two timestamps.

    Scans the device's own records in time order and tracks:
    - `last_low`: the most recent record where `field < current_value`
    - `first_high`: the earliest record at-or-after `last_low` where
      `field >= current_value`

    If `field` never dips below `current_value` anywhere in the log, there's
    no provable transition (either nothing has run yet, or the counter simply
    hasn't changed since the last observation) -- returns None. Because we
    keep overwriting `last_low` as we scan forward, back-to-back cycles
    (48 -> 49 -> 49 -> 50) correctly key off only the most recent transition.

    `first_high` may not exist yet in the log at all (this call is the first
    time we're seeing `current_value`) -- in that case the increment's
    earliest possible moment is `now` itself, so `earliest_ago` is zero and
    only `latest_ago` (bounded by `last_low`) carries information.
    """
    device_records = sorted(
        (r for r in records if r.get("device_id") == device_id and field in (r.get("fields") or {})),
        key=lambda r: r["timestamp"],
    )
    if not device_records:
        return None

    last_low: dict[str, Any] | None = None
    first_high: dict[str, Any] | None = None
    for record in device_records:
        value = record["fields"][field]
        if value < current_value:
            last_low = record
        elif first_high is None:
            first_high = record
            break

    if last_low is None:
        return None

    earliest_ago = (now - first_high["timestamp"]) if first_high is not None else timedelta(0)
    latest_ago = now - last_low["timestamp"]
    return CompletionEstimate(earliest_ago=earliest_ago, latest_ago=latest_ago, threshold=precise_threshold)


def _format_duration(delta: timedelta) -> str:
    total_seconds = max(int(delta.total_seconds()), 0)
    if total_seconds < 60:
        return "less than a minute"
    total_minutes = total_seconds // 60
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    if days and hours:
        return f"{days}d {hours}h"
    if days:
        return f"{days}d"
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"
