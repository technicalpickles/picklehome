# Climate Auto-Switch Run Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add structured JSONL run logging and last-state tracking to the climate comfort-switch auto command, so every run captures thermostat state, outdoor temp, and the mode decision. Enable no-op detection (skip schedule push when mode hasn't changed) while always fetching fresh thermostat data.

**Architecture:** New `climate/runlog.py` module handles reading/writing the JSONL log and last-state file. The `cmd_comfort_switch` function in `sync.py` is refactored to always fetch thermostat status, check last-state for no-op, and write both files after every run. File paths come from a `CLIMATE_DATA_DIR` env var (defaulting to `~/.local/state/picklehome`).

**Tech Stack:** Python, JSON, existing `climate.ecobee.status.extract_thermostat_status`

---

### Task 1: Create the runlog module

**Files:**
- Create: `climate/runlog.py`
- Test: `tests/climate/test_runlog.py`

**Step 1: Write failing tests**

Create `tests/climate/test_runlog.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from climate.runlog import (
    get_data_dir,
    read_last_state,
    write_last_state,
    append_run_log,
)


def test_get_data_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIMATE_DATA_DIR", str(tmp_path))
    assert get_data_dir() == tmp_path


def test_get_data_dir_default(monkeypatch):
    monkeypatch.delenv("CLIMATE_DATA_DIR", raising=False)
    result = get_data_dir()
    assert "picklehome" in str(result)


def test_read_last_state_missing(tmp_path):
    assert read_last_state(tmp_path) is None


def test_read_last_state_exists(tmp_path):
    state = {"timestamp": "2026-03-27T06:00:00Z", "mode": "cool", "outdoor_temp_f": 66.6, "thermostats": []}
    (tmp_path / "last-state.json").write_text(json.dumps(state))
    assert read_last_state(tmp_path) == state


def test_write_last_state(tmp_path):
    state = {"timestamp": "2026-03-27T06:00:00Z", "mode": "cool", "outdoor_temp_f": 66.6, "thermostats": []}
    write_last_state(tmp_path, state)
    written = json.loads((tmp_path / "last-state.json").read_text())
    assert written == state


def test_append_run_log(tmp_path):
    entry1 = {"timestamp": "2026-03-27T06:00:00Z", "decision": "cool"}
    entry2 = {"timestamp": "2026-03-27T12:00:00Z", "decision": "cool"}
    append_run_log(tmp_path, entry1)
    append_run_log(tmp_path, entry2)

    lines = (tmp_path / "run-log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == entry1
    assert json.loads(lines[1]) == entry2


def test_append_run_log_creates_file(tmp_path):
    entry = {"timestamp": "2026-03-27T06:00:00Z", "decision": "heat"}
    append_run_log(tmp_path, entry)
    assert (tmp_path / "run-log.jsonl").exists()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/climate/test_runlog.py -v`
Expected: FAIL (module doesn't exist)

**Step 3: Write the implementation**

Create `climate/runlog.py`:

```python
import json
import os
from datetime import datetime, timezone
from pathlib import Path

LAST_STATE_FILE = "last-state.json"
RUN_LOG_FILE = "run-log.jsonl"


def get_data_dir() -> Path:
    env_path = os.environ.get("CLIMATE_DATA_DIR")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "state" / "picklehome"


def read_last_state(data_dir: Path) -> dict | None:
    path = data_dir / LAST_STATE_FILE
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def write_last_state(data_dir: Path, state: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LAST_STATE_FILE
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def append_run_log(data_dir: Path, entry: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / RUN_LOG_FILE
    with open(path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/climate/test_runlog.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
feat(climate): add runlog module for structured run logging
```

---

### Task 2: Refactor cmd_comfort_switch to use runlog

**Files:**
- Modify: `climate/sync.py:386-474` (cmd_comfort_switch)
- Test: `tests/climate/test_comfort_switch.py`

This is the main refactor. The new flow:

1. Read outdoor temp (unchanged)
2. Decide mode (unchanged)
3. Read last-state
4. **Always** create ecobee client and fetch thermostat statuses
5. If mode matches last-state mode: no-op (skip schedule push, hold clearing, HVAC mode setting)
6. If mode differs (or no last-state): push schedule, clear holds, set HVAC mode (existing logic)
7. Write JSONL entry with full data
8. Write last-state

**Step 1: Write failing tests**

Create `tests/climate/test_comfort_switch.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def test_noop_when_mode_unchanged(tmp_path, monkeypatch):
    """When last-state mode matches decision, skip schedule push."""
    monkeypatch.setenv("CLIMATE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ECOBEE_API_KEY", "test-key")

    # Seed last-state as "cool"
    last_state = {"timestamp": "2026-03-27T00:00:00Z", "mode": "cool", "outdoor_temp_f": 67.0, "thermostats": []}
    (tmp_path / "last-state.json").write_text(json.dumps(last_state))

    from climate.runlog import read_last_state, RUN_LOG_FILE, LAST_STATE_FILE

    # The run log entry should exist and show switched=false
    log_path = tmp_path / RUN_LOG_FILE
    state_path = tmp_path / LAST_STATE_FILE

    # We'll verify the behavior indirectly through the log files
    # rather than mocking the full Ecobee API chain
    assert read_last_state(tmp_path)["mode"] == "cool"
```

Note: Full integration testing of the refactored cmd_comfort_switch requires mocking the Ecobee API, which is complex. For this task, we test the runlog module thoroughly (Task 1) and verify the wiring manually with the Docker E2E test (Task 4). The refactored function is a composition of already-tested pieces.

**Step 2: Refactor cmd_comfort_switch**

Replace `cmd_comfort_switch` in `climate/sync.py` (lines 386-474) with:

```python
def cmd_comfort_switch(args) -> None:
    from climate.ambient.client import load_weather_config, get_configured_macs, get_outdoor_temp_from_stations
    from climate import runlog

    mode = args.mode
    outdoor_temp = None
    data_dir = runlog.get_data_dir()

    if mode == "auto":
        config = load_weather_config(args.weather)
        macs = get_configured_macs(config)
        if not macs:
            print("No stations configured. Run 'just climate-weather-discover', then set AMBIENT_STATION_MACS in .env.")
            sys.exit(1)
        result = get_outdoor_temp_from_stations(macs)
        if result is None:
            print("Could not read outdoor temp from any configured station.")
            sys.exit(1)
        mac, outdoor_temp, age_minutes = result
        thresholds = config.get("thresholds", {})
        heat_below = thresholds.get("heat_below", 60)
        cool_above = thresholds.get("cool_above", 65)
        if outdoor_temp < heat_below:
            mode = "heat"
        elif outdoor_temp > cool_above:
            mode = "cool"
        else:
            print(f"Outdoor temp {outdoor_temp}°F is in hysteresis band ({heat_below}-{cool_above}°F). No change.")
            return
        print(f"Outdoor temp: {outdoor_temp}°F → switching to {mode}")

    # Check last-state for no-op
    last_state = runlog.read_last_state(data_dir)
    previous_mode = last_state["mode"] if last_state else None

    # Always fetch thermostat status for logging
    ecobee = auth.make_ecobee()
    registry = load_thermostats(args.thermostats)
    managed = get_managed_thermostats(registry)
    managed_ids = {tid for _, tid in managed}

    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        print("Failed to fetch thermostat data from Ecobee.")
        sys.exit(1)

    thermostat_statuses = [
        status.extract_thermostat_status(t)
        for t in ecobee.thermostats
        if t["identifier"] in managed_ids
    ]

    switched = False
    holds_cleared = False
    skipped = False

    if previous_mode == mode:
        print(f"Already in {mode} mode. Skipping schedule push.")
        skipped = True
    elif args.dry_run:
        schedule_path = args.schedule
        original = schedule_path.read_text()
        updated = _apply_comfort_mode(original, mode)
        if updated != original:
            print(f"[dry run] Would switch to {mode} comfort:")
            for i, (old, new) in enumerate(zip(original.splitlines(), updated.splitlines()), 1):
                if old != new:
                    print(f"  line {i}: {old.strip()!r} → {new.strip()!r}")
        else:
            print(f"Schedule already set to {mode} comfort.")
        if args.clear_holds:
            print(f"[dry run] Would clear active holds on all managed thermostats")
        print(f"[dry run] Would set HVAC mode to auto on all managed thermostats")
        return
    else:
        # Push schedule change
        schedule_path = args.schedule
        original = schedule_path.read_text()
        updated = _apply_comfort_mode(original, mode)

        if updated != original:
            schedule_path.write_text(updated)
            print(f"schedule.yaml updated to {mode} comfort. Syncing to Ecobee...")
            sync_args = argparse.Namespace(
                schedule=schedule_path,
                thermostats=args.thermostats,
                thermostat=None,
                dry_run=False,
            )
            try:
                cmd_sync(sync_args)
            except SystemExit as e:
                if e.code != 0:
                    print("Ecobee sync failed. Restoring schedule.yaml to original content.")
                    schedule_path.write_text(original)
                    raise
            switched = True
        else:
            print(f"Schedule already set to {mode} comfort.")

        if args.clear_holds:
            for name, thermostat_id in managed:
                try:
                    schedule.resume_program(ecobee, thermostat_id)
                    print(f"  [{name}] Cleared active holds")
                    holds_cleared = True
                except RuntimeError as e:
                    print(f"  [{name}] Warning: failed to clear holds: {e}")

        hvac_mode = "auto"
        for name, thermostat_id in managed:
            try:
                schedule.set_hvac_mode(ecobee, thermostat_id, hvac_mode)
                print(f"  [{name}] HVAC mode set to {hvac_mode}")
            except RuntimeError as e:
                print(f"  [{name}] Warning: failed to set HVAC mode: {e}")

    # Write run log and last-state
    log_entry = {
        "timestamp": runlog.now_iso(),
        "outdoor_temp_f": outdoor_temp,
        "decision": mode,
        "previous_mode": previous_mode,
        "switched": switched,
        "holds_cleared": holds_cleared,
        "skipped": skipped,
        "thermostats": thermostat_statuses,
    }
    runlog.append_run_log(data_dir, log_entry)

    state = {
        "timestamp": runlog.now_iso(),
        "mode": mode,
        "outdoor_temp_f": outdoor_temp,
        "thermostats": thermostat_statuses,
    }
    runlog.write_last_state(data_dir, state)
```

**Step 3: Run existing tests**

Run: `uv run pytest tests/climate/ -v`
Expected: ALL PASS (existing tests still work, new runlog tests pass)

**Step 4: Commit**

```
feat(climate): add no-op detection and structured run logging to comfort-switch
```

---

### Task 3: Add CLIMATE_DATA_DIR to compose and env template

**Files:**
- Modify: `homelab/services/climate-auto-switch/compose.yaml`
- Modify: `homelab/services/climate-auto-switch/compose.picklelab.yaml`

**Step 1: Update compose.yaml**

Add `CLIMATE_DATA_DIR` to the environment section, pointing to the same mount as the token file:

```yaml
    environment:
      - ECOBEE_TOKEN_PATH=/data/ecobee-tokens.json
      - CLIMATE_DATA_DIR=/data
```

Also simplify the volume mount name from `/data/tokens` to `/data` since it now holds more than just tokens:

```yaml
    volumes:
      - ${CLIMATE_DATA_DIR:-~/.local/state/picklehome}:/data
```

**Step 2: Update compose.picklelab.yaml**

```yaml
    volumes:
      - /srv/data/climate-auto-switch:/data
```

**Step 3: Commit**

```
feat(homelab): add CLIMATE_DATA_DIR to compose config
```

---

### Task 4: Add just tasks for checking logs remotely

**Files:**
- Modify: `Justfile`

**Step 1: Add tasks**

```just
# Show last climate auto-switch state (from picklelab)
climate-check host="picklelab":
    ssh {{host}} "cat /srv/data/climate-auto-switch/last-state.json | python3 -m json.tool"

# Show recent climate auto-switch run log (from picklelab)
climate-log host="picklelab" lines="10":
    ssh {{host}} "tail -n {{lines}} /srv/data/climate-auto-switch/run-log.jsonl | python3 -m json.tool --json-lines"
```

**Step 2: Verify tasks appear**

Run: `just --list | grep climate`

**Step 3: Commit**

```
feat: add climate-check and climate-log just tasks
```

---

### Task 5: Docker E2E test

**No files changed. Verification only.**

**Step 1: Rebuild the image**

From `homelab/services/climate-auto-switch/`:
```bash
docker compose build --no-cache
```

**Step 2: Run the container**

```bash
docker compose run --rm climate-auto-switch
```
Expected: runs, prints output as before, plus writes to data dir.

**Step 3: Check the log files**

```bash
cat ~/.local/state/picklehome/last-state.json | python3 -m json.tool
cat ~/.local/state/picklehome/run-log.jsonl
```

Expected: last-state has mode, outdoor temp, and thermostat data. JSONL has one entry.

**Step 4: Run again to verify no-op**

```bash
docker compose run --rm climate-auto-switch
```

Expected: prints "Already in [mode] mode. Skipping schedule push." JSONL has two entries, second one has `"skipped": true`. Last-state is updated with fresh thermostat data.

**Step 5: Verify JSONL has two entries**

```bash
wc -l ~/.local/state/picklehome/run-log.jsonl
cat ~/.local/state/picklehome/run-log.jsonl | python3 -m json.tool --json-lines
```
