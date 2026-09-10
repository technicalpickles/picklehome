# Climate Seasonal Switching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the seasonal comfort-mode switcher idempotent and self-healing by treating the thermostat as the source of truth, and stop it overwriting device settings a human deliberately chose.

**Architecture:** `schedule.yaml` stops encoding the season — occupied slots use a virtual `comfort` ref resolved to `smart1`/`smart2` immediately before a push. Each run decides the mode from a 24-hour mean of logged outdoor temperatures, builds the desired 7×48 schedule array, diffs it against the live program, and pushes only on difference. There is no local record of the mode, so nothing can desync from the device.

**Tech Stack:** Python 3.12, `uv`, `pytest` + `unittest.mock` (no plugins), `python-ecobee-api`, YAML config, Docker Compose + systemd timer on picklelab.

**Spec:** `docs/plans/2026-09-10-climate-seasonal-switching-design.md`

## Global Constraints

- **Spec-first ordering.** `climate/CLAUDE.md`: *"If the desired behavior is changing, update the spec first, then derive YAML changes."* `spec-behavior-update` therefore runs before any task touching `schedule.yaml`.
- **`comfort` must never reach the Ecobee API.** It is resolved to a real climateRef before every push. A `comfort` string arriving in a request body is a bug.
- **The timer never writes `hvacMode`.** Not conditionally, not "only when wrong". Only the explicit `climate-hvac-mode` command writes it.
- **The timer never clears an active hold.** `resume_program` runs only after an actual mode change, and only on thermostats whose `hold` is `None`.
- **A 200 response is not proof a write took.** Ecobee silently rewrites out-of-range values (see `heatCoolMinDelta` in `climate/spec/hvac-spec.md`). Any settings write is verified by reading the live program back and diffing.
- **Tests are offline.** No test hits a real API. Mock at the client boundary (patch the HTTP call or library method, not internal functions). No `conftest.py` — fixtures live in the file that uses them, per `climate/README.md` and the repo's existing tests.
- Run tests with `uv run pytest`.

## File Structure

| File | Responsibility |
|---|---|
| `climate/runlog.py` (modify) | Gains `read_recent_outdoor_temps` — tail-reads the run log and returns temps inside a time window. Stays the only module that knows the log's on-disk shape. |
| `climate/ecobee/comfort_mode.py` (create) | The virtual `comfort` ref, mode↔climateRef mapping, `detect_live_mode`, and `decide_mode`. Pure functions, no I/O, no Ecobee client. |
| `climate/ecobee/schedule.py` (modify) | `validate_climate_refs` accepts the virtual ref. Everything else unchanged. |
| `climate/sync.py` (modify) | Command wiring only: `cmd_sync`, `cmd_validate`, `cmd_comfort_switch` rewritten to resolve-and-diff; `_apply_comfort_mode` deleted; two new commands. |
| `climate/config/schedule.yaml` (modify) | Occupied slots become `comfort`; header comment corrected. |
| `climate/spec/hvac-spec.md` (modify) | Source of truth; corrected first. |
| `climate/README.md` (modify) | Command reference and architecture notes. |
| `tests/climate/test_runlog.py` (modify) | Window-reading cases. |
| `tests/climate/ecobee/test_comfort_mode.py` (create) | Resolution and decision cases. |
| `tests/test_comfort_switch.py` (modify) | Replaces `_apply_comfort_mode` tests with idempotence and settings-untouched tests. |

Decision logic lives in `comfort_mode.py` as pure functions rather than inside `sync.py` because `sync.py` is already 990 lines and command wiring is the one thing that genuinely needs a live client. Everything worth testing is then testable without a mock Ecobee.

---

### spec-behavior-update

Correct the source of truth before any behavior changes. Runs first by constraint, not preference.

**Files:**
- Modify: `climate/spec/hvac-spec.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the documented contract every later task implements.

- [ ] **Step 1: Rewrite the `### HVAC mode` section**

Replace the whole section. The current text says `comfort-switch` sets HVAC mode to auto and calls auto "the safe default" — this design deletes that behavior.

```markdown
### HVAC mode

The thermostat's HVAC mode (`auto`, `heat`, `cool`, `off`) controls which
equipment may run, independent of the schedule's comfort modes.

**The automation never writes it.** A person setting the thermostat to Off, or
to heat-only during a cold snap, is making a deliberate choice that outranks
the schedule. Previously `comfort-switch` forced `auto` on every run, which
meant a household member could not turn the system off — it reverted within 15
minutes with no message and no trace.

The tradeoff is that an HVAC mode can now contradict the active comfort mode:
heat-only left set into June means Comfort Cool cannot cool. This is surfaced,
never corrected. When the current HVAC mode cannot deliver the active comfort
mode, `climate-status` and the run log both say so.

To change it deliberately: `just climate-hvac-mode auto|heat|cool|off`.
```

- [ ] **Step 2: Replace the "Known defect" paragraph in `### Seasonal switching`**

Delete the paragraph beginning `**Known defect as of 2026-09-10:**` and replace with:

```markdown
The mode is decided from a **24-hour mean** of outdoor temperature, not a single
reading. Samples come from the run log, which records outdoor temperature every
15 minutes. A full window is 96 samples; below 48 the run makes no change and
logs why.

A mean is used because a shoulder-season day genuinely spans the band — an April
day running 45–80°F would otherwise flip the mode twice daily. Its mean lands
near 62°F, inside the band, which correctly means "leave it alone". The
tradeoff is stickiness: through a long mild spring the mean can sit in the band
for weeks and the house holds whichever mode it was in. That is deliberate and
comfortable, but the seasonal flip happens later than intuition suggests.

**The thermostat is the source of truth for the current mode.** `schedule.yaml`
does not encode a season: occupied slots use the virtual ref `comfort`, resolved
to `smart1` or `smart2` immediately before a push. Each run builds the desired
schedule, compares it to the live program, and pushes **only if they differ**.
No local file records the mode, so there is nothing to desync.
```

- [ ] **Step 3: Amend the hold paragraph**

Replace the paragraph starting `If someone has manually adjusted a thermostat`:

```markdown
A manual adjustment creates an Ecobee **hold**, which overrides the schedule.
Holds last **4 hours** (`holdAction: useEndTime4hour`) and are never cleared by
the automation. Pass `--clear-holds` to clear them explicitly.

The fixed duration is deliberate. `holdAction: nextPeriod` made a hold last
until the next schedule transition, so the same gesture behaved wildly
differently by zone and time of day: downstairs has transitions at 00:00 and
07:30, so a bump at 8am held for sixteen hours, while upstairs on a weekday has
one at 10:00, so a bump at 9:50am expired in ten minutes. Four hours is
predictable, covers a work block or an evening, and self-clears if forgotten.

After an actual mode change, thermostats with **no** active hold are resumed so
the new schedule applies immediately rather than waiting up to 16 hours for the
next downstairs transition. Thermostats with an active hold are left alone.
```

- [ ] **Step 4: Update the schedule tables to name the virtual ref**

In both the Downstairs and Upstairs schedule tables, change the mode column from
`Comfort Heat / Comfort Cool` to ``Comfort (`comfort`)`` and set the reason
column to mention that the seasonal decision resolves it. Add below both tables:

```markdown
Occupied slots are written as `comfort` in `schedule.yaml`. It is a virtual ref
resolved to Comfort Cool (`smart1`) or Comfort Heat (`smart2`) at push time; it
is never sent to Ecobee.
```

- [ ] **Step 5: Verify no stale claims remain**

Run: `grep -n "sets the HVAC mode\|nextPeriod\|Known defect\|Comfort Heat / Comfort Cool" climate/spec/hvac-spec.md`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add climate/spec/hvac-spec.md
git commit -m "docs(climate): update hvac spec for the seasonal switching redesign

Spec-first per climate/CLAUDE.md: the behavior contract changes before any
config or code does. The HVAC mode section described behavior this redesign
deletes (forcing auto every run, which is why nobody could turn the system
off), so it was actively wrong rather than merely incomplete."
```

---

### outdoor-window

Read a time-bounded set of outdoor temperatures from the run log.

**Files:**
- Modify: `climate/runlog.py`
- Test: `tests/climate/test_runlog.py`

**Interfaces:**
- Consumes: `get_data_dir()`, `RUN_LOG_FILE`, `LOCAL_TZ` (existing in `climate/runlog.py`).
- Produces: `read_recent_outdoor_temps(data_dir: Path, hours: int = 24, now: datetime | None = None, tail_bytes: int = 262144) -> list[float]` — temps inside the window, oldest first.

- [ ] **Step 1: Write the failing tests**

Append to `tests/climate/test_runlog.py`:

```python
import json
from datetime import datetime, timedelta

from climate.runlog import LOCAL_TZ, read_recent_outdoor_temps


def _write_log(data_dir, entries):
    path = data_dir / "run-log.jsonl"
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _entry(ts, temp):
    return {"timestamp": ts.isoformat(), "outdoor_temp_f": temp, "decision": "cool"}


def test_returns_temps_within_window(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    _write_log(tmp_path, [
        _entry(now - timedelta(hours=1), 70.0),
        _entry(now - timedelta(hours=2), 72.0),
    ])
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [70.0, 72.0]


def test_excludes_entries_outside_window(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    _write_log(tmp_path, [
        _entry(now - timedelta(hours=25), 40.0),
        _entry(now - timedelta(hours=1), 70.0),
    ])
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [70.0]


def test_entry_exactly_at_boundary_is_included(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    _write_log(tmp_path, [_entry(now - timedelta(hours=24), 55.0)])
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [55.0]


def test_malformed_lines_are_skipped(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    path = tmp_path / "run-log.jsonl"
    with open(path, "w") as f:
        f.write("not json at all\n")
        f.write(json.dumps({"timestamp": "garbage", "outdoor_temp_f": 1.0}) + "\n")
        f.write(json.dumps({"timestamp": now.isoformat()}) + "\n")  # no temp key
        f.write(json.dumps(_entry(now, None)) + "\n")               # null temp
        f.write(json.dumps(_entry(now, 68.0)) + "\n")
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [68.0]


def test_missing_log_returns_empty(tmp_path):
    assert read_recent_outdoor_temps(tmp_path, hours=24) == []


def test_partial_first_line_from_tail_read_is_dropped(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    entries = [_entry(now - timedelta(minutes=i), 70.0) for i in range(200)]
    _write_log(tmp_path, entries)
    # tail_bytes small enough to slice mid-line; the partial line must not crash
    # or contribute, and everything fully inside the tail must still be read.
    temps = read_recent_outdoor_temps(tmp_path, hours=24, now=now, tail_bytes=2000)
    assert len(temps) > 0
    assert all(t == 70.0 for t in temps)
    assert len(temps) < 200
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/climate/test_runlog.py -v`
Expected: FAIL with `ImportError: cannot import name 'read_recent_outdoor_temps'`

- [ ] **Step 3: Implement**

In `climate/runlog.py`, change the datetime import to
`from datetime import datetime, timedelta` and append:

```python
def read_recent_outdoor_temps(
    data_dir: Path,
    hours: int = 24,
    now: datetime | None = None,
    tail_bytes: int = 262144,
) -> list[float]:
    """Outdoor temps logged within the last `hours`, oldest first.

    Only the tail of the log is read. At roughly 870 bytes/entry, 256KB covers
    well over a day of 15-minute samples, and the log grows ~30MB/year.

    Malformed lines are skipped rather than raising: one bad append should
    degrade the sample count (which the caller already guards on) instead of
    blinding the decision entirely.
    """
    path = data_dir / RUN_LOG_FILE
    if not path.exists():
        return []
    if now is None:
        now = datetime.now(LOCAL_TZ)
    cutoff = now - timedelta(hours=hours)

    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - tail_bytes))
        chunk = f.read()

    lines = chunk.decode("utf-8", errors="replace").splitlines()
    # A tail read almost certainly starts mid-line; that fragment is not valid
    # JSON and would be skipped anyway, but drop it explicitly for clarity.
    if size > tail_bytes and lines:
        lines = lines[1:]

    temps: list[float] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry["timestamp"])
            temp = entry["outdoor_temp_f"]
        except (ValueError, KeyError, TypeError):
            continue
        if temp is None:
            continue
        if ts >= cutoff:
            temps.append(float(temp))
    return temps
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/climate/test_runlog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add climate/runlog.py tests/climate/test_runlog.py
git commit -m "feat(climate): read a time-bounded outdoor temp window from the run log

Tail-reads rather than parsing the whole file; the log is already 13.9MB and
this runs every 15 minutes. Malformed lines are skipped so one bad append
degrades the sample count instead of blinding the decision."
```

---

### mode-resolution

Pure functions for the virtual ref and the decision. No I/O.

**Files:**
- Create: `climate/ecobee/comfort_mode.py`
- Test: `tests/climate/ecobee/test_comfort_mode.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `COMFORT_REF: str` = `"comfort"`
  - `MIN_SAMPLES: int` = `48`
  - `resolve_ref(mode: str) -> str`
  - `resolve_schedule_array(schedule_array: list[list[str]], mode: str) -> list[list[str]]`
  - `detect_live_mode(program: dict) -> str | None`
  - `decide_mode(temps: list[float], heat_below: float, cool_above: float) -> tuple[str | None, dict]`

- [ ] **Step 1: Write the failing tests**

Create `tests/climate/ecobee/test_comfort_mode.py`:

```python
import pytest

from climate.ecobee.comfort_mode import (
    COMFORT_REF,
    MIN_SAMPLES,
    decide_mode,
    detect_live_mode,
    resolve_ref,
    resolve_schedule_array,
)


def test_resolve_ref_maps_modes():
    assert resolve_ref("cool") == "smart1"
    assert resolve_ref("heat") == "smart2"


def test_resolve_ref_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unknown mode"):
        resolve_ref("warm")


def test_resolve_schedule_array_replaces_only_the_virtual_ref():
    array = [[COMFORT_REF, "sleep", "away", "home"]]
    assert resolve_schedule_array(array, "heat") == [["smart2", "sleep", "away", "home"]]


def test_resolve_schedule_array_leaves_no_virtual_ref_behind():
    array = [[COMFORT_REF] * 48 for _ in range(7)]
    resolved = resolve_schedule_array(array, "cool")
    assert not any(COMFORT_REF in day for day in resolved)


def test_detect_live_mode_reads_cool():
    program = {"schedule": [["sleep", "smart1"]]}
    assert detect_live_mode(program) == "cool"


def test_detect_live_mode_reads_heat():
    program = {"schedule": [["sleep", "smart2"]]}
    assert detect_live_mode(program) == "heat"


def test_detect_live_mode_none_when_neither_present():
    program = {"schedule": [["sleep", "away", "home"]]}
    assert detect_live_mode(program) is None


def test_detect_live_mode_none_when_both_present():
    # Hand-edited in the Ecobee app; ambiguous, so refuse to guess.
    program = {"schedule": [["smart1", "smart2"]]}
    assert detect_live_mode(program) is None


def test_decide_mode_below_threshold_is_heat():
    mode, info = decide_mode([50.0] * MIN_SAMPLES, heat_below=60, cool_above=65)
    assert mode == "heat"
    assert info["mean"] == 50.0


def test_decide_mode_above_threshold_is_cool():
    mode, info = decide_mode([80.0] * MIN_SAMPLES, heat_below=60, cool_above=65)
    assert mode == "cool"


def test_decide_mode_inside_band_makes_no_change():
    mode, info = decide_mode([62.0] * MIN_SAMPLES, heat_below=60, cool_above=65)
    assert mode is None
    assert info["reason"] == "hysteresis_band"


def test_decide_mode_exactly_on_threshold_makes_no_change():
    # Thresholds are exclusive on both sides, matching the documented band.
    assert decide_mode([60.0] * MIN_SAMPLES, 60, 65)[0] is None
    assert decide_mode([65.0] * MIN_SAMPLES, 60, 65)[0] is None


def test_decide_mode_refuses_on_too_few_samples():
    mode, info = decide_mode([20.0] * (MIN_SAMPLES - 1), heat_below=60, cool_above=65)
    assert mode is None
    assert info["reason"] == "insufficient_samples"
    assert info["samples"] == MIN_SAMPLES - 1


def test_decide_mode_refuses_on_empty_window():
    mode, info = decide_mode([], heat_below=60, cool_above=65)
    assert mode is None
    assert info["reason"] == "insufficient_samples"


def test_decide_mode_averages_a_swinging_day():
    # The shoulder-season case this design exists for: a day spanning the band
    # in both directions must not flip the mode.
    temps = [45.0] * 48 + [80.0] * 48
    mode, info = decide_mode(temps, heat_below=60, cool_above=65)
    assert mode is None
    assert info["mean"] == 62.5
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/climate/ecobee/test_comfort_mode.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'climate.ecobee.comfort_mode'`

- [ ] **Step 3: Implement**

Create `climate/ecobee/comfort_mode.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/climate/ecobee/test_comfort_mode.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add climate/ecobee/comfort_mode.py tests/climate/ecobee/test_comfort_mode.py
git commit -m "feat(climate): add comfort mode resolution and rolling-window decision

Pure functions, no I/O, so the logic worth testing is testable without a mock
Ecobee client. detect_live_mode returns None rather than defaulting when the
live program is ambiguous -- silently picking a season is how the original bug
hid for months."
```

---

### schedule-virtual-ref

Migrate the config to the virtual ref and teach validation about it.

**Files:**
- Modify: `climate/ecobee/schedule.py:185-199` (`validate_climate_refs`)
- Modify: `climate/config/schedule.yaml`
- Test: `tests/climate/ecobee/test_schedule_refs.py` (create)

**Interfaces:**
- Consumes: `COMFORT_REF` from `climate.ecobee.comfort_mode`.
- Produces: `schedule.yaml` whose occupied slots are `comfort`; `validate_climate_refs` accepting it.

- [ ] **Step 1: Write the failing tests**

Create `tests/climate/ecobee/test_schedule_refs.py`:

```python
import pytest

from climate.ecobee.schedule import validate_climate_refs

PROGRAM = {"climates": [
    {"climateRef": "smart1"}, {"climateRef": "smart2"},
    {"climateRef": "sleep"}, {"climateRef": "away"}, {"climateRef": "home"},
]}


def test_virtual_comfort_ref_is_accepted():
    schedule = {"monday": [{"time": "00:00", "climate": "comfort"}]}
    validate_climate_refs(schedule, PROGRAM)  # must not raise


def test_real_refs_still_accepted():
    schedule = {"monday": [{"time": "00:00", "climate": "sleep"}]}
    validate_climate_refs(schedule, PROGRAM)


def test_unknown_ref_still_raises():
    schedule = {"monday": [{"time": "00:00", "climate": "nonsense"}]}
    with pytest.raises(ValueError, match="Unknown climate"):
        validate_climate_refs(schedule, PROGRAM)


def test_error_message_does_not_suggest_comfort_is_a_real_ref():
    schedule = {"monday": [{"time": "00:00", "climate": "nonsense"}]}
    with pytest.raises(ValueError) as exc:
        validate_climate_refs(schedule, PROGRAM)
    assert "comfort" not in str(exc.value).split("Valid climateRefs")[-1]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/climate/ecobee/test_schedule_refs.py -v`
Expected: FAIL on `test_virtual_comfort_ref_is_accepted` with `ValueError: Unknown climate(s): ['comfort']`

- [ ] **Step 3: Implement**

In `climate/ecobee/schedule.py`, add the import at the top:

```python
from climate.ecobee.comfort_mode import COMFORT_REF
```

Replace the body of `validate_climate_refs`:

```python
def validate_climate_refs(schedule_dict: dict, program: dict) -> None:
    # COMFORT_REF is virtual: it is resolved to a real climateRef immediately
    # before a push and never sent to Ecobee, so it is valid in the file but
    # deliberately absent from the "valid climateRefs" list in the error below.
    real = {c["climateRef"] for c in program["climates"]}
    valid = real | {COMFORT_REF}
    used = set()
    for transitions in schedule_dict.values():
        if not isinstance(transitions, list):
            continue  # skip anchor-definition keys and other non-list values
        for entry in transitions:
            if isinstance(entry, dict) and "climate" in entry:
                used.add(entry["climate"])
    unknowns = used - valid
    if unknowns:
        raise ValueError(
            f"Unknown climate(s): {sorted(unknowns)}. "
            f"Valid climateRefs for this thermostat: {sorted(real)}"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/climate/ecobee/test_schedule_refs.py -v`
Expected: PASS

- [ ] **Step 5: Migrate `schedule.yaml`**

Replace every `climate: smart1` and `climate: smart2` (with their trailing
comments) with `climate: comfort`, and replace the header comment line
`# Climate values must be climateRef strings from your Ecobee thermostat.`:

```yaml
# climate/config/schedule.yaml
# Climate values are either a climateRef from your Ecobee thermostat
# (sleep, away, home) or the virtual ref `comfort`.
#
# `comfort` is resolved at push time to Comfort Cool (smart1) or Comfort Heat
# (smart2) based on the seasonal decision, and is never sent to Ecobee. Do not
# write smart1/smart2 here directly -- the season is not stored in this file.
# See climate/spec/hvac-spec.md, "Seasonal switching".
#
# Thermostat IDs are in climate/config/thermostats.yaml.
# All times must be on 30-minute boundaries (:00 or :30).
# Every day must start with time: "00:00". All 7 days are required.
```

- [ ] **Step 6: Verify no season is left in the file**

Run: `grep -n "smart1\|smart2" climate/config/schedule.yaml`
Expected: no output.

- [ ] **Step 7: Commit**

```bash
git add climate/ecobee/schedule.py climate/config/schedule.yaml tests/climate/ecobee/test_schedule_refs.py
git commit -m "feat(climate): move schedule.yaml to the virtual comfort ref

The file no longer encodes a season, which is what dissolves the stale
smart1/smart2 trailing comments (they drifted because the mode was stored as a
text mutation and the swap regex deliberately skipped comments).

The error message still lists only real climateRefs, so a typo does not get
told that 'comfort' is a thermostat climate."
```

---

### conditional-push

The core change: resolve, diff, push only on difference. Stop writing settings.

**Files:**
- Modify: `climate/sync.py` — `cmd_sync`, `cmd_validate`, `cmd_comfort_switch`; delete `_apply_comfort_mode` (line ~473)
- Test: `tests/test_comfort_switch.py` (rewrite)

**Interfaces:**
- Consumes: `read_recent_outdoor_temps`, `decide_mode`, `detect_live_mode`, `resolve_schedule_array`, `COMFORT_REF`, and existing `diff_schedules` / `push_schedule` / `build_schedule_array`.
- Produces: `_resolve_mode_for_push(program, args, weather_config, data_dir) -> tuple[str, dict]` — the shared resolution used by both sync and comfort-switch.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_comfort_switch.py`. The
`_apply_comfort_mode` tests go away with the function.

```python
from unittest.mock import MagicMock, patch

import pytest

from climate.ecobee.comfort_mode import COMFORT_REF, resolve_schedule_array


def _program(ref):
    """A live program whose occupied slots all use `ref`."""
    return {
        "schedule": [["sleep"] * 15 + [ref] * 33 for _ in range(7)],
        "climates": [{"climateRef": r, "name": r} for r in
                     ("smart1", "smart2", "sleep", "away", "home")],
    }


def _local_array():
    return [["sleep"] * 15 + [COMFORT_REF] * 33 for _ in range(7)]


def test_resolved_array_matches_live_when_mode_unchanged():
    # The idempotence property: same decision, same live state -> nothing to push.
    from climate.ecobee.schedule import diff_schedules
    live = _program("smart1")
    desired = resolve_schedule_array(_local_array(), "cool")
    assert diff_schedules(desired, live["schedule"], live) == []


def test_resolved_array_differs_when_mode_changes():
    from climate.ecobee.schedule import diff_schedules
    live = _program("smart1")
    desired = resolve_schedule_array(_local_array(), "heat")
    assert diff_schedules(desired, live["schedule"], live) != []


def test_resolved_array_never_contains_the_virtual_ref():
    # Guard the global constraint: `comfort` must never reach the Ecobee API.
    for mode in ("cool", "heat"):
        desired = resolve_schedule_array(_local_array(), mode)
        assert not any(COMFORT_REF in day for day in desired)


def test_push_not_called_when_schedule_matches(monkeypatch):
    from climate.ecobee import schedule as schedule_mod
    push = MagicMock()
    monkeypatch.setattr(schedule_mod, "push_schedule", push)

    live = _program("smart1")
    desired = resolve_schedule_array(_local_array(), "cool")
    if schedule_mod.diff_schedules(desired, live["schedule"], live):
        schedule_mod.push_schedule(MagicMock(), "tid", desired, live["climates"])
    push.assert_not_called()


def test_push_called_once_when_schedule_differs(monkeypatch):
    from climate.ecobee import schedule as schedule_mod
    push = MagicMock()
    monkeypatch.setattr(schedule_mod, "push_schedule", push)

    live = _program("smart1")
    desired = resolve_schedule_array(_local_array(), "heat")
    if schedule_mod.diff_schedules(desired, live["schedule"], live):
        schedule_mod.push_schedule(MagicMock(), "tid", desired, live["climates"])
    assert push.call_count == 1


def test_comfort_switch_never_sets_hvac_mode():
    """The timer must not write hvacMode. Regression guard for 'cannot turn it off'."""
    import climate.sync as sync_mod
    src = __import__("inspect").getsource(sync_mod.cmd_comfort_switch)
    assert "set_hvac_mode" not in src


def test_apply_comfort_mode_is_gone():
    """The text-mutation approach is deleted, not merely unused."""
    import climate.sync as sync_mod
    assert not hasattr(sync_mod, "_apply_comfort_mode")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_comfort_switch.py -v`
Expected: FAIL — `test_apply_comfort_mode_is_gone` and `test_comfort_switch_never_sets_hvac_mode` fail because both still exist.

- [ ] **Step 3: Delete `_apply_comfort_mode`**

Remove the whole function from `climate/sync.py` (starts at line ~473,
`def _apply_comfort_mode(schedule_text: str, mode: str) -> str:`) and its `re`
import if nothing else uses it. Verify: `grep -n "^import re\|re\." climate/sync.py`

- [ ] **Step 4: Add the shared mode resolver**

Add to `climate/sync.py` above `cmd_comfort_switch`:

```python
def _resolve_mode_for_push(program, explicit_mode, weather_config, data_dir):
    """Pick the mode to resolve `comfort` against. Returns (mode, reasoning).

    Order: an explicit --mode wins; otherwise preserve whatever the thermostat
    is already running, so a structural sync (moving a transition time) does not
    accidentally flip the season; otherwise fall back to the rolling window.
    Never defaults -- an undeterminable mode raises.
    """
    from climate.ecobee.comfort_mode import decide_mode, detect_live_mode
    from climate import runlog

    if explicit_mode:
        return explicit_mode, {"reason": "explicit_mode"}

    live = detect_live_mode(program)
    if live:
        return live, {"reason": "preserved_live_mode"}

    thresholds = weather_config.get("thresholds", {})
    temps = runlog.read_recent_outdoor_temps(data_dir)
    decided, info = decide_mode(
        temps,
        thresholds.get("heat_below", 60),
        thresholds.get("cool_above", 65),
    )
    if decided:
        return decided, info
    raise RuntimeError(
        "Cannot determine the comfort mode: the live program uses neither "
        "smart1 nor smart2 (or uses both), and the outdoor window was "
        f"inconclusive ({info}). Re-run with --mode heat|cool."
    )
```

- [ ] **Step 5: Rewrite the push path in `cmd_comfort_switch`**

Replace everything from `schedule_path = args.schedule` through the
`set_hvac_mode` loop with:

```python
    from climate.ecobee.comfort_mode import resolve_schedule_array

    pushed = []
    for name, thermostat_id, schedule_dict in entries:
        program = schedule.get_current_program(ecobee, thermostat_id)
        schedule.validate_climate_refs(schedule_dict, program)
        desired = resolve_schedule_array(
            schedule.build_schedule_array(schedule_dict), mode
        )
        diffs = schedule.diff_schedules(desired, program["schedule"], program)
        if not diffs:
            print(f"  [{name}] Already correct, nothing to push.")
            continue
        if args.dry_run:
            print(f"  [{name}] Would push {len(diffs)} slot change(s).")
            continue
        schedule.push_schedule(ecobee, thermostat_id, desired, program["climates"])
        print(f"  [{name}] Pushed {len(diffs)} slot change(s).")
        pushed.append((name, thermostat_id))

    # Resume only where we actually changed something and no one is holding.
    # An active hold is a deliberate human override and is never cleared here.
    hold_by_name = {s["name"].lower(): s.get("hold") for s in thermostat_statuses}
    if args.clear_holds:
        for name, thermostat_id in managed:
            schedule.resume_program(ecobee, thermostat_id)
            print(f"  [{name}] Cleared active holds")
            holds_cleared = True
    else:
        for name, thermostat_id in pushed:
            if hold_by_name.get(name.lower()) is None:
                schedule.resume_program(ecobee, thermostat_id)
                print(f"  [{name}] Resumed program so the change applies now")

    # hvacMode is deliberately NOT written here. A person setting Off or
    # heat-only outranks the automation; see climate/spec/hvac-spec.md.
    switched = bool(pushed)
```

- [ ] **Step 6: Use the rolling window for the auto decision**

In `cmd_comfort_switch`, replace the `if mode == "auto":` block's threshold
comparison. Keep the existing Ambient fetch (it still feeds the log), but decide
from the window:

```python
    if mode == "auto":
        config = load_weather_config(args.weather)
        macs = get_configured_macs(config)
        if not macs:
            print("No stations configured. Run 'just climate-weather-discover'.")
            sys.exit(1)
        result = get_outdoor_temp_from_stations(macs)
        if result is None:
            print("Could not read outdoor temp from any configured station.")
            sys.exit(1)
        mac, outdoor_temp, age_minutes = result
        # The instantaneous reading is still fetched and logged: it is no longer
        # what we decide from, but it is what future 24h windows are built out
        # of. Do not remove this alongside the unconditional push.
        thresholds = config.get("thresholds", {})
        temps = runlog.read_recent_outdoor_temps(data_dir)
        decided, decision_info = decide_mode(
            temps, thresholds.get("heat_below", 60), thresholds.get("cool_above", 65)
        )
        if decided is None:
            print(f"No change: {decision_info}")
            hysteresis = True
        else:
            mode = decided
            print(f"24h mean {decision_info['mean']}°F "
                  f"({decision_info['samples']} samples) → {mode}")
```

Add `decision_info` to both run-log entries so the reasoning is recorded.

- [ ] **Step 7: Apply the same resolve-and-diff to `cmd_sync` and `cmd_validate`**

In `cmd_sync`, after `validate_climate_refs`, resolve before building the push;
in `cmd_validate`, resolve before diffing so a season change is not reported as
a false diff:

```python
    mode, _ = _resolve_mode_for_push(
        program, getattr(args, "mode", None), load_weather_config(args.weather),
        runlog.get_data_dir(),
    )
    schedule_array = resolve_schedule_array(schedule_array, mode)
```

Add `--mode` to both parsers: `choices=["heat", "cool"], default=None`.

- [ ] **Step 8: Run the full climate test suite**

Run: `uv run pytest tests/climate/ tests/test_comfort_switch.py -v`
Expected: PASS

- [ ] **Step 9: Dry-run against the live thermostats**

Run: `just climate-comfort-switch-dry cool`
Expected: reports "Already correct, nothing to push" for both thermostats,
because `spec-behavior-update` and `schedule-virtual-ref` did not change any
resolved slot. Anything else means the migration changed the schedule and needs
explaining before proceeding.

- [ ] **Step 10: Commit**

```bash
git add climate/sync.py tests/test_comfort_switch.py
git commit -m "feat(climate): push the schedule only when it actually differs

Replaces the text-mutation approach. Each run resolves the virtual comfort ref,
diffs the desired 7x48 array against the live program, and pushes only on
difference -- so the operation is idempotent and the ephemeral container stops
mattering by construction.

Also stops writing hvacMode entirely (this is why nobody could turn the system
off) and gates resume_program on an actual mode change, dropping it from ~96
calls/day to ~2/year. An active hold is never cleared."
```

---

### hvac-mode-command

Give back the lever the timer just stopped taking, and warn on mismatch.

**Files:**
- Modify: `climate/sync.py` (new `cmd_hvac_mode`, subparser), `climate/ecobee/status.py` (mismatch warning)
- Modify: `Justfile`
- Test: `tests/climate/ecobee/test_status.py`

**Interfaces:**
- Consumes: `set_hvac_mode` from `climate.ecobee.schedule`.
- Produces: `hvac_mode_warning(status: dict) -> str | None` in `climate/ecobee/status.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/climate/ecobee/test_status.py`:

```python
from climate.ecobee.status import hvac_mode_warning


def test_warns_when_heat_only_during_comfort_cool():
    w = hvac_mode_warning({"hvac_mode": "heat", "climate_ref": "smart1"})
    assert w is not None and "cannot cool" in w


def test_warns_when_cool_only_during_comfort_heat():
    w = hvac_mode_warning({"hvac_mode": "cool", "climate_ref": "smart2"})
    assert w is not None and "cannot heat" in w


def test_warns_when_off():
    assert hvac_mode_warning({"hvac_mode": "off", "climate_ref": "smart1"}) is not None


def test_no_warning_on_auto():
    assert hvac_mode_warning({"hvac_mode": "auto", "climate_ref": "smart1"}) is None


def test_no_warning_when_mode_matches_season():
    assert hvac_mode_warning({"hvac_mode": "cool", "climate_ref": "smart1"}) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/climate/ecobee/test_status.py -v`
Expected: FAIL with `ImportError: cannot import name 'hvac_mode_warning'`

- [ ] **Step 3: Implement the warning**

Add to `climate/ecobee/status.py`:

```python
def hvac_mode_warning(status: dict) -> str | None:
    """Warn when the HVAC mode cannot deliver the active comfort mode.

    Surfaced, never corrected: a person choosing Off or heat-only outranks the
    automation (see climate/spec/hvac-spec.md, "HVAC mode"). The cost of that
    choice is that this mismatch is possible, so it is said out loud.
    """
    mode = status.get("hvac_mode")
    ref = status.get("climate_ref")
    if mode == "off":
        return "HVAC mode is off; neither heating nor cooling will run."
    if mode == "heat" and ref == "smart1":
        return "HVAC mode is heat-only but Comfort Cool is scheduled; it cannot cool."
    if mode == "cool" and ref == "smart2":
        return "HVAC mode is cool-only but Comfort Heat is scheduled; it cannot heat."
    return None
```

Call it in the status printer and append the warning line when non-None.

- [ ] **Step 4: Add the command**

In `climate/sync.py`:

```python
def cmd_hvac_mode(args) -> None:
    ecobee = auth.make_ecobee()
    registry = load_thermostats(args.thermostats)
    for name, thermostat_id in get_managed_thermostats(registry):
        schedule.set_hvac_mode(ecobee, thermostat_id, args.mode)
        print(f"  [{name}] HVAC mode set to {args.mode}")
```

Register the subparser with
`choices=["auto", "heat", "cool", "off", "auxHeatOnly"]`, and add to `Justfile`:

```make
# Set HVAC mode on managed thermostats (auto | heat | cool | off)
climate-hvac-mode MODE:
    uv run python -m climate.sync hvac-mode {{MODE}}
```

- [ ] **Step 5: Run tests and confirm the recipe registered**

Run: `uv run pytest tests/climate/ecobee/test_status.py -v && just --list | grep hvac`
Expected: PASS, and `climate-hvac-mode` appears.

- [ ] **Step 6: Commit**

```bash
git add climate/sync.py climate/ecobee/status.py Justfile tests/climate/ecobee/test_status.py
git commit -m "feat(climate): add explicit hvac-mode command and mismatch warning

The timer no longer writes hvacMode, so this is the deliberate lever. The
accepted risk is heat-only left set into June, so a mode that cannot deliver
the active comfort mode is surfaced in status and the run log -- loudly, but
never corrected."
```

---

### hold-action-setting

Make a walk-up bump behave the same everywhere. Verify empirically.

**Files:**
- Modify: `climate/config/thermostats.yaml`, `climate/sync.py`, `Justfile`

**Interfaces:**
- Consumes: `get_managed_thermostats`.
- Produces: `just climate-settings-sync`.

- [ ] **Step 1: Add the setting to the registry**

In `climate/config/thermostats.yaml`, add under each managed thermostat:

```yaml
    settings:
      hold_action: useEndTime4hour
```

- [ ] **Step 2: Add the command**

In `climate/sync.py`:

```python
def cmd_settings_sync(args) -> None:
    """Push device settings from thermostats.yaml. Manual only, never the timer."""
    ecobee = auth.make_ecobee()
    registry = load_thermostats(args.thermostats)
    for name, thermostat_id in get_managed_thermostats(registry):
        desired = (registry[name].get("settings") or {}).get("hold_action")
        if not desired:
            continue
        body = {
            "selection": {"selectionType": "thermostats", "selectionMatch": thermostat_id},
            "thermostat": {"settings": {"holdAction": desired}},
        }
        if args.dry_run:
            print(f"  [{name}] Would set holdAction={desired}")
            continue
        ecobee._request_with_refresh(
            "POST", ECOBEE_ENDPOINT_THERMOSTAT, f"set holdAction {desired}", body=body
        )
        print(f"  [{name}] Pushed holdAction={desired}")
```

- [ ] **Step 3: Verify the enum empirically, do not trust the spelling**

Ecobee silently rewrites values it does not accept, so a 200 proves nothing.

Run: `just climate-settings-sync` then:

```bash
uv run python -c "
from climate.ecobee import auth
e = auth.make_ecobee(); e.get_thermostats()
for t in e.thermostats:
    print(t['name'], '->', t['settings'].get('holdAction'))
"
```

Expected: both managed thermostats report `useEndTime4hour`.

If they instead report `nextPeriod` (silently rejected), try `useEndTime2hour`
to confirm the `useEndTime*` family is valid at all, then consult the Ecobee
API docs for the settings enum. **Do not proceed on an unverified value** — an
unverified write here is the exact failure this whole redesign exists to stop.

- [ ] **Step 4: Commit**

```bash
git add climate/config/thermostats.yaml climate/sync.py Justfile
git commit -m "feat(climate): push holdAction via an explicit settings command

holdAction was nextPeriod, so a hold lasted until the next schedule transition
-- sixteen hours downstairs at 8am, ten minutes upstairs at 9:50am. Same
gesture, wildly different result. Fixed 4h is predictable on both.

Manual command, never the timer: this is a device setting affecting everyone's
muscle memory. Value verified by reading the live program back, because Ecobee
silently rewrites values it rejects."
```

---

### docs-and-deploy

Finish the living docs and ship it.

**Files:**
- Modify: `climate/README.md`

- [ ] **Step 1: Update `climate/README.md`**

- Reword the Comfort modes architecture note (line ~124): smart1/smart2 are no
  longer "swappable" by text mutation; describe resolve-and-diff.
- Add `climate-hvac-mode` and `climate-settings-sync` to the command reference.
- In the config-file table, note that `schedule.yaml` uses the virtual `comfort`
  ref.

- [ ] **Step 2: Run the whole suite**

Run: `uv run pytest`
Expected: PASS, no failures.

- [ ] **Step 3: Commit and merge to main**

```bash
git add climate/README.md
git commit -m "docs(climate): update README for the seasonal switching redesign"
```

- [ ] **Step 4: Deploy**

`schedule.yaml` is baked into the image, so the config and code deploy together.

Run: `just deploy-climate`

- [ ] **Step 5: Verify the first post-deploy run is a no-op**

Wait for the next 15-minute tick, then:

Run: `just climate-log picklelab 1`

Expected: an entry with the 24h mean, its sample count, `decision: cool`, and
**no push** — the device already matches. A boring no-op is the correct
outcome. A push on the first run means the migration changed a resolved slot
and must be explained before leaving it running.

- [ ] **Step 6: Confirm settings survived**

Run: `just climate-status`

Expected: both thermostats still on their pre-deploy `hvacMode`, holds intact,
and no warning unless an HVAC mode genuinely mismatches.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Mode representation / virtual ref | `mode-resolution`, `schedule-virtual-ref` |
| Push only on difference | `conditional-push` |
| 24-hour mean decision | `outdoor-window`, `conditional-push` step 6 |
| Insufficient-samples guard | `mode-resolution` (`MIN_SAMPLES`) |
| Window fed by the command itself | `conditional-push` step 6 (comment + retained fetch) |
| `hvacMode` never written / warned | `conditional-push` step 5, `hvac-mode-command` |
| `resume_program` gating | `conditional-push` step 5 |
| `holdAction` → 4h, verified empirically | `hold-action-setting` |
| Live-mode-undeterminable fallback | `conditional-push` step 4 (`_resolve_mode_for_push`) |
| Command surface table | `conditional-push` step 7, `hvac-mode-command`, `hold-action-setting` |
| Documentation changes (spec, yaml header, README) | `spec-behavior-update`, `schedule-virtual-ref` step 5, `docs-and-deploy` |
| Rollout | `docs-and-deploy` |

No gaps.

**Type consistency:** `decide_mode` returns `tuple[str | None, dict]` everywhere
it is called (`_resolve_mode_for_push`, `cmd_comfort_switch`).
`resolve_schedule_array` takes and returns `list[list[str]]`, matching
`build_schedule_array`'s return and `diff_schedules`'s parameters.
`detect_live_mode` returns `str | None` and every caller handles `None`
explicitly rather than defaulting.

**Ordering:** `spec-behavior-update` precedes `schedule-virtual-ref` as
`climate/CLAUDE.md` requires. `mode-resolution` precedes `schedule-virtual-ref`
because `validate_climate_refs` imports `COMFORT_REF`.
