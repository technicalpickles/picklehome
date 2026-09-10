"""Seasonal comfort mode: the virtual `comfort` ref and how a mode is decided.

`schedule.yaml` never names a season. Occupied slots use COMFORT_REF, which is
resolved to a real Ecobee climateRef immediately before a push and is never sent
to the API.

Nothing here stores "what mode are we in". That question is answered by reading
the thermostat's live program (detect_live_mode), because a local record of the
mode desyncs silently and then never self-corrects.
"""

COMFORT_REF = "comfort"

MODE_TO_REF = {"cool": "smart1", "heat": "smart2"}
REF_TO_MODE = {ref: mode for mode, ref in MODE_TO_REF.items()}

# A full 24h window at 15-minute sampling is 96 entries. Below half that, the
# window is too gappy to average meaningfully (timer outage, cold start,
# restored volume), so the run declines to decide rather than guessing.
MIN_SAMPLES = 48


def resolve_ref(mode: str) -> str:
    """Map a mode name to the Ecobee climateRef that implements it."""
    try:
        return MODE_TO_REF[mode]
    except KeyError:
        raise ValueError(
            f"Unknown mode {mode!r}. Expected one of {sorted(MODE_TO_REF)}."
        ) from None


def resolve_schedule_array(schedule_array: list[list[str]], mode: str) -> list[list[str]]:
    """Replace every COMFORT_REF slot with the climateRef for `mode`."""
    ref = resolve_ref(mode)
    return [[ref if slot == COMFORT_REF else slot for slot in day] for day in schedule_array]


def detect_live_mode(program: dict) -> str | None:
    """Which season the live program is running, or None if not determinable.

    None means either ref is absent (a reset thermostat, or a schedule
    hand-edited to use only home/away/sleep) or both are present (hand-edited
    into a mixed state). Callers must not default: silently picking a season is
    how the original bug stayed invisible for months.
    """
    refs = {slot for day in program.get("schedule", []) for slot in day}
    found = {REF_TO_MODE[ref] for ref in refs if ref in REF_TO_MODE}
    return found.pop() if len(found) == 1 else None


def decide_mode(
    temps: list[float], heat_below: float, cool_above: float
) -> tuple[str | None, dict]:
    """Decide a mode from a rolling window. Returns (mode-or-None, reasoning).

    A None mode always means "make no change"; the reasoning dict says why, and
    is written to the run log so the decision is inspectable after the fact
    rather than reconstructed.
    """
    samples = len(temps)
    if samples < MIN_SAMPLES:
        return None, {
            "reason": "insufficient_samples",
            "samples": samples,
            "min_samples": MIN_SAMPLES,
        }

    mean = sum(temps) / samples
    info = {"samples": samples, "mean": round(mean, 1)}

    if mean < heat_below:
        return "heat", {**info, "reason": "below_heat_threshold"}
    if mean > cool_above:
        return "cool", {**info, "reason": "above_cool_threshold"}
    return None, {**info, "reason": "hysteresis_band"}
