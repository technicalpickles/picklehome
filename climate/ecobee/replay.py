"""Replay the comfort auto-switch rule against Ecobee runtime history.

Answers "what would this band have done" without touching a thermostat. The
decision itself is `comfort_mode.decide_mode`, fed the same 15-minute outdoor
samples the run log records, so a replay can't drift from the real rule.

Each morning's decision is scored against what the equipment actually did that
day (heating vs cooling minutes). That ground truth reflects whatever mode and
holds were active at the time, so it ranks bands, it doesn't prove one right.
"""

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from climate.ecobee.comfort_mode import MIN_SAMPLES, decide_mode

DATA_START = date(2026, 3, 11)
DECISION_TIME = time(7, 0)
SAMPLE_MINUTES = 15
MIN_DEMAND_MINUTES = 60
DEFAULT_MODE = "cool"


@dataclass(frozen=True)
class Band:
    heat_below: float
    cool_above: float

    @classmethod
    def parse(cls, text: str) -> "Band":
        try:
            lo, hi = (float(p) for p in text.split("/"))
        except ValueError:
            raise ValueError(f"Band must look like 60/65, got {text!r}") from None
        if lo > hi:
            raise ValueError(f"Band {text!r}: heat_below can't exceed cool_above")
        return cls(lo, hi)

    def __str__(self) -> str:
        return f"{self.heat_below:g}/{self.cool_above:g}"


@dataclass(frozen=True)
class Flip:
    day: date
    from_mode: str
    to_mode: str


@dataclass(frozen=True)
class Replay:
    band: Band
    window_hours: int
    modes: dict[date, str]
    flips: list[Flip]
    agree: int
    scored: int


def label_days(zones: list[list[dict]], min_minutes: float = MIN_DEMAND_MINUTES) -> dict[date, str]:
    """Label each day "heat" or "cool" by which ran more across all zones.

    Days with less than `min_minutes` of combined runtime are left out: nothing
    was demanded, so any mode is fine.
    """
    heat: dict[date, float] = defaultdict(float)
    cool: dict[date, float] = defaultdict(float)
    for rows in zones:
        for row in rows:
            day = row["ts"].date()
            heat[day] += (row["heat"] + row["aux"]) / 60
            cool[day] += row["cool"] / 60
    return {
        day: "heat" if heat[day] > cool[day] else "cool"
        for day in heat.keys() | cool.keys()
        if heat[day] + cool[day] >= min_minutes
    }


def outdoor_series(rows: list[dict]) -> list[tuple[datetime, float]]:
    """(timestamp, outdoor F) per row, carrying the last reading over gaps."""
    series: list[tuple[datetime, float]] = []
    last = None
    for row in rows:
        if row["outdoor"] is not None:
            last = row["outdoor"]
        if last is not None:
            series.append((row["ts"], last))
    return series


def replay(
    outdoor: list[tuple[datetime, float]],
    labels: dict[date, str],
    band: Band,
    window_hours: int = 24,
) -> Replay:
    """Run the rule once each morning over `outdoor`, scoring against `labels`."""
    times = [t for t, _ in outdoor]
    mode: str | None = None
    modes: dict[date, str] = {}
    flips: list[Flip] = []
    for i, (ts, _) in enumerate(outdoor):
        if ts.time() != DECISION_TIME:
            continue
        start = bisect_right(times, ts - timedelta(hours=window_hours))
        window = [v for t, v in outdoor[start : i + 1] if t.minute % SAMPLE_MINUTES == 0]
        decided, _ = decide_mode(window, band.heat_below, band.cool_above)
        if decided is None and mode is None:
            if len(window) < MIN_SAMPLES:
                continue
            decided = DEFAULT_MODE
        if decided and decided != mode:
            if mode is not None:
                flips.append(Flip(ts.date(), mode, decided))
            mode = decided
        modes[ts.date()] = mode
    scored = [d for d in labels if d in modes]
    agree = sum(1 for d in scored if modes[d] == labels[d])
    return Replay(band, window_hours, modes, flips, agree, len(scored))


def format_replays(replays: list[Replay], labels: dict[date, str]) -> str:
    heat_days = sum(1 for v in labels.values() if v == "heat")
    cool_days = len(labels) - heat_days
    lines = [
        f"Scored against {len(labels)} days with demand ({heat_days} heat, {cool_days} cool). "
        f"Always-cool would score {cool_days}/{len(labels)}.",
        "",
        "  band     window  flips  agree",
    ]
    for r in replays:
        pct = f"{r.agree / r.scored:.0%}" if r.scored else "n/a"
        lines.append(
            f"  {str(r.band):<8} {r.window_hours:>4}h  {len(r.flips):>5}  {r.agree}/{r.scored} = {pct}"
        )
    first = replays[0]
    lines += ["", f"Flips for {first.band} over {first.window_hours}h:"]
    lines += [f"  {f.day}  {f.from_mode} -> {f.to_mode}" for f in first.flips] or ["  none"]
    return "\n".join(lines)
