# Climate Directory Restructure + Status Command: Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename `ecobee/` to `climate/` with proper code/config/spec separation, consolidate thermostat IDs into a registry, and add a `status` command showing current thermostat state.

**Architecture:** Move the Python package to `climate/ecobee/`, config YAMLs to `climate/config/`, spec docs to `climate/spec/`. A new `thermostats.yaml` registry holds all thermostat IDs and a `managed` flag (Cottage is `managed: false`). The `status` command reads from this registry and the live API; all other commands are updated to resolve IDs through it too.

**Tech Stack:** Python 3.12, `pyecobee` (python-ecobee-api 0.3.2), `pyyaml`, `keyring`, `uv`, `just`

---

### Task 1: Create directory structure

**Files:**
- Create: `climate/ecobee/` (directory)
- Create: `climate/config/` (directory)
- Create: `climate/spec/` (directory)

**Step 1: Create directories**

```bash
mkdir -p climate/ecobee climate/config climate/spec
```

**Step 2: Verify**

```bash
ls climate/
```
Expected: `config/  ecobee/  spec/`

**Step 3: Commit**

```bash
git add climate/
git commit -m "chore: scaffold climate/ directory structure"
```

---

### Task 2: Move Python package files

**Files:**
- Copy: `ecobee/__init__.py` → `climate/ecobee/__init__.py`
- Copy: `ecobee/auth.py` → `climate/ecobee/auth.py`
- Copy: `ecobee/schedule.py` → `climate/ecobee/schedule.py`
- Copy: `ecobee/comforts.py` → `climate/ecobee/comforts.py`
- Copy: `ecobee/sync.py` → `climate/sync.py`

**Step 1: Copy files**

```bash
cp ecobee/__init__.py climate/ecobee/__init__.py
cp ecobee/auth.py climate/ecobee/auth.py
cp ecobee/schedule.py climate/ecobee/schedule.py
cp ecobee/comforts.py climate/ecobee/comforts.py
cp ecobee/sync.py climate/sync.py
```

**Step 2: Update imports in `climate/sync.py`**

Find all `from ecobee import` and change to `from climate.ecobee import`:

```python
# climate/sync.py line ~8, change:
from ecobee import auth, comforts, schedule
# to:
from climate.ecobee import auth, comforts, schedule
```

**Step 3: Update default config paths in `climate/sync.py`**

The current defaults point at `Path(__file__).parent / "schedule.yaml"` etc. Update to point at `climate/config/`:

```python
# climate/sync.py
DEFAULT_SCHEDULE_PATH = Path(__file__).parent / "config" / "schedule.yaml"
DEFAULT_COMFORTS_PATH = Path(__file__).parent / "config" / "comforts.yaml"
```

**Step 4: Update `pyproject.toml`**

```toml
# Change:
packages = ["ecobee"]
# To:
packages = ["climate"]

# Also update project name:
name = "picklehome-climate"
```

**Step 5: Verify import works**

```bash
uv run python -c "from climate.ecobee import auth; print('ok')"
```
Expected: `ok`

**Step 6: Commit**

```bash
git add climate/ pyproject.toml
git commit -m "chore: copy ecobee package into climate/ecobee, update imports"
```

---

### Task 3: Move config and spec files

**Files:**
- Copy: `ecobee/schedule.yaml` → `climate/config/schedule.yaml`
- Copy: `ecobee/comforts.yaml` → `climate/config/comforts.yaml`
- Copy: `ecobee/hvac-spec.md` → `climate/spec/hvac-spec.md`

**Step 1: Copy files**

```bash
cp ecobee/schedule.yaml climate/config/schedule.yaml
cp ecobee/comforts.yaml climate/config/comforts.yaml
cp ecobee/hvac-spec.md climate/spec/hvac-spec.md
```

**Step 2: Smoke test, list command still works**

```bash
uv run python -m climate.sync list
```
Expected: lists thermostats without errors (same output as before).

**Step 3: Commit**

```bash
git add climate/config/ climate/spec/
git commit -m "chore: move config and spec files into climate/"
```

---

### Task 4: Create `thermostats.yaml` registry

**Files:**
- Create: `climate/config/thermostats.yaml`

**Step 1: Create the registry**

```yaml
# climate/config/thermostats.yaml
# Canonical thermostat registry for this home.
# managed: true  : included in all home automation (status, sync, etc.)
# managed: false : registered but excluded (e.g. separate property)

thermostats:
  downstairs:
    thermostat_id: "532572869586"
    managed: true
  upstairs:
    thermostat_id: "532537308613"
    managed: true
  cottage:
    thermostat_id: "272457106318"
    managed: false  # separate property, excluded from home automation
```

**Step 2: Commit**

```bash
git add climate/config/thermostats.yaml
git commit -m "feat: add thermostats.yaml canonical registry"
```

---

### Task 5: Write `thermostats.py`, the registry loader (TDD)

**Files:**
- Create: `tests/climate/ecobee/test_thermostats.py`
- Create: `climate/ecobee/thermostats.py`

**Step 1: Create test directory**

```bash
mkdir -p tests/climate/ecobee
touch tests/__init__.py tests/climate/__init__.py tests/climate/ecobee/__init__.py
```

**Step 2: Write failing tests**

```python
# tests/climate/ecobee/test_thermostats.py
import pytest
from climate.ecobee.thermostats import (
    get_managed_thermostats,
    get_thermostat_id,
)

REGISTRY = {
    "thermostats": {
        "downstairs": {"thermostat_id": "111", "managed": True},
        "upstairs": {"thermostat_id": "222", "managed": True},
        "cottage": {"thermostat_id": "333", "managed": False},
    }
}


def test_get_managed_thermostats_returns_only_managed():
    result = get_managed_thermostats(REGISTRY)
    names = [name for name, _ in result]
    assert "downstairs" in names
    assert "upstairs" in names
    assert "cottage" not in names


def test_get_managed_thermostats_returns_ids():
    result = get_managed_thermostats(REGISTRY)
    by_name = dict(result)
    assert by_name["downstairs"] == "111"
    assert by_name["upstairs"] == "222"


def test_get_thermostat_id_returns_id():
    assert get_thermostat_id(REGISTRY, "downstairs") == "111"


def test_get_thermostat_id_raises_for_unknown():
    with pytest.raises(KeyError):
        get_thermostat_id(REGISTRY, "nonexistent")
```

**Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/climate/ecobee/test_thermostats.py -v
```
Expected: `ImportError` or `ModuleNotFoundError`

**Step 4: Write minimal implementation**

```python
# climate/ecobee/thermostats.py
import sys
from pathlib import Path

import yaml


def load_thermostats(path: str | Path) -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except OSError as e:
        print(f"Cannot read thermostats file: {path}: {e}")
        sys.exit(1)
    if data is None or "thermostats" not in data:
        print("thermostats.yaml is empty or missing 'thermostats' key")
        sys.exit(1)
    return data


def get_managed_thermostats(data: dict) -> list[tuple[str, str]]:
    """Return (name, thermostat_id) for all managed thermostats."""
    return [
        (name, entry["thermostat_id"])
        for name, entry in data["thermostats"].items()
        if entry.get("managed", False)
    ]


def get_thermostat_id(data: dict, name: str) -> str:
    """Return thermostat_id for the named thermostat. Raises KeyError if not found."""
    thermostats = data["thermostats"]
    if name not in thermostats:
        raise KeyError(f"Thermostat '{name}' not in thermostats.yaml")
    return thermostats[name]["thermostat_id"]
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/climate/ecobee/test_thermostats.py -v
```
Expected: all 4 tests PASS

**Step 6: Commit**

```bash
git add climate/ecobee/thermostats.py tests/
git commit -m "feat: add thermostats.py registry loader with tests"
```

---

### Task 6: Refactor `schedule.yaml`: remove `thermostat_id`

**Files:**
- Modify: `climate/config/schedule.yaml`
- Modify: `climate/ecobee/schedule.py`
- Modify: `climate/sync.py`

**Step 1: Update `climate/config/schedule.yaml`**, remove `thermostat_id` lines

```yaml
# climate/config/schedule.yaml
# Climate values must be climateRef strings from your Ecobee thermostat.
# Thermostat IDs are in climate/config/thermostats.yaml.
# All times must be on 30-minute boundaries (:00 or :30).
# Every day must start with time: "00:00". All 7 days are required.

thermostats:
  downstairs:
    schedule:
      _everyday: &downstairs_everyday
        - time: "00:00"
          climate: sleep
        - time: "06:00"
          climate: smart1  # Comfort Cool

      sunday: *downstairs_everyday
      monday: *downstairs_everyday
      tuesday: *downstairs_everyday
      wednesday: *downstairs_everyday
      thursday: *downstairs_everyday
      friday: *downstairs_everyday
      saturday: *downstairs_everyday

  upstairs:
    schedule:
      _weekday: &upstairs_weekday
        - time: "00:00"
          climate: smart1  # Comfort Cool
        - time: "10:00"
          climate: away    # Eco
        - time: "14:30"
          climate: smart1  # Comfort Cool

      _weekend: &upstairs_weekend
        - time: "00:00"
          climate: smart1  # Comfort Cool

      sunday: *upstairs_weekend
      monday: *upstairs_weekday
      tuesday: *upstairs_weekday
      wednesday: *upstairs_weekday
      thursday: *upstairs_weekday
      friday: *upstairs_weekday
      saturday: *upstairs_weekend
```

**Step 2: Update `iter_thermostat_entries` in `climate/ecobee/schedule.py`**

Add a `registry` parameter for ID lookup:

```python
# climate/ecobee/schedule.py
from climate.ecobee.thermostats import get_thermostat_id

def iter_thermostat_entries(data: dict, registry: dict, name_filter: str | None = None):
    """Yield (name, thermostat_id, schedule_dict) for each configured thermostat."""
    for name, entry in data["thermostats"].items():
        if name_filter and name != name_filter:
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"Thermostat '{name}' entry must be a mapping")
        try:
            thermostat_id = get_thermostat_id(registry, name)
        except KeyError:
            raise ValueError(
                f"Thermostat '{name}' in schedule.yaml not found in thermostats.yaml"
            )
        schedule_dict = entry.get("schedule")
        if not isinstance(schedule_dict, dict):
            raise ValueError(f"Thermostat '{name}' is missing 'schedule'")
        yield name, thermostat_id, schedule_dict
```

**Step 3: Update `climate/sync.py`**, load registry and pass to `iter_thermostat_entries`

Add a default path constant and load it in the sync/validate commands:

```python
# climate/sync.py, add at top with other constants:
DEFAULT_THERMOSTATS_PATH = Path(__file__).parent / "config" / "thermostats.yaml"

# Add --thermostats argument to sync and validate subparsers (same pattern as --schedule):
# sync_parser.add_argument("--thermostats", type=Path, default=DEFAULT_THERMOSTATS_PATH, ...)
# validate_parser.add_argument(...)

# In cmd_sync and cmd_validate, load registry and pass to iter_thermostat_entries:
from climate.ecobee.thermostats import load_thermostats
# ...
registry = thermostats.load_thermostats(args.thermostats)
entries = list(schedule.iter_thermostat_entries(schedule_data, registry, args.thermostat))
```

**Step 4: Smoke test sync dry-run**

```bash
uv run python -m climate.sync sync --dry-run
```
Expected: schedule preview for both downstairs and upstairs, no errors.

**Step 5: Commit**

```bash
git add climate/config/schedule.yaml climate/ecobee/schedule.py climate/sync.py
git commit -m "refactor: resolve thermostat IDs from thermostats.yaml in schedule commands"
```

---

### Task 7: Refactor `comforts.yaml`: remove `thermostat_id`

**Files:**
- Modify: `climate/config/comforts.yaml`
- Modify: `climate/ecobee/comforts.py`
- Modify: `climate/sync.py`

**Step 1: Update `climate/config/comforts.yaml`**, remove all `thermostat_id` lines

```yaml
# climate/config/comforts.yaml
# Temperature setpoints (°F) for each comfort mode (climate).
# Thermostat IDs are in climate/config/thermostats.yaml.
# Generated by 'just climate-comforts-capture'. Edit as desired.
# Run 'just climate-comforts-sync' to push changes to thermostats.

thermostats:
  cottage:
    climates:
      away:
        cool_temp: 75
        heat_temp: 55
      home:
        cool_temp: 75
        heat_temp: 55
      wakeup:
        cool_temp: 70
        heat_temp: 65
      sleep:
        cool_temp: 80
        heat_temp: 62
  upstairs:
    climates:
      away:
        cool_temp: 82
        heat_temp: 64
      home:
        cool_temp: 75
        heat_temp: 62
      sleep:
        cool_temp: 71
        heat_temp: 66
      smart1:
        cool_temp: 70
        heat_temp: 65
        name: Comfort Cool
      smart2:
        cool_temp: 75
        heat_temp: 45
        name: Comfort Heat
  downstairs:
    climates:
      away:
        cool_temp: 82
        heat_temp: 64
      home:
        cool_temp: 70
        heat_temp: 65
      sleep:
        cool_temp: 74
        heat_temp: 61
      smart1:
        cool_temp: 70
        heat_temp: 65
        name: Comfort Cool
      smart2:
        cool_temp: 73
        heat_temp: 70
        name: Comfort Heat
```

**Step 2: Update `iter_thermostat_entries` in `climate/ecobee/comforts.py`**

Same pattern as schedule.py, add `registry` parameter:

```python
# climate/ecobee/comforts.py
from climate.ecobee.thermostats import get_thermostat_id

def iter_thermostat_entries(data: dict, registry: dict, name_filter: str | None = None):
    """Yield (name, thermostat_id, climates_dict) for each configured thermostat."""
    for name, entry in data["thermostats"].items():
        if name_filter and name != name_filter:
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"Thermostat '{name}' entry must be a mapping")
        try:
            thermostat_id = get_thermostat_id(registry, name)
        except KeyError:
            raise ValueError(
                f"Thermostat '{name}' in comforts.yaml not found in thermostats.yaml"
            )
        climates_dict = entry.get("climates")
        if not isinstance(climates_dict, dict):
            raise ValueError(f"Thermostat '{name}' is missing 'climates'")
        yield name, thermostat_id, climates_dict
```

**Step 3: Update comforts commands in `climate/sync.py`**

Add `--thermostats` arg to `capture-comforts` and `sync-comforts` subparsers. Load registry and pass to `iter_thermostat_entries` in `cmd_comforts_capture` and `cmd_comforts_sync`.

**Step 4: Smoke test comforts dry-run**

```bash
uv run python -m climate.sync sync-comforts --dry-run
```
Expected: comfort preview for upstairs and downstairs (cottage too, since it's still in comforts.yaml), no errors.

**Step 5: Commit**

```bash
git add climate/config/comforts.yaml climate/ecobee/comforts.py climate/sync.py
git commit -m "refactor: resolve thermostat IDs from thermostats.yaml in comforts commands"
```

---

### Task 8: Write `status.py` (TDD)

**Files:**
- Create: `tests/climate/ecobee/test_status.py`
- Create: `climate/ecobee/status.py`

**Step 1: Write failing tests**

```python
# tests/climate/ecobee/test_status.py
from climate.ecobee.status import (
    decode_temp,
    get_equipment_description,
    get_active_hold,
    extract_thermostat_status,
)


def test_decode_temp_converts_tenths():
    assert decode_temp(704) == 70.4
    assert decode_temp(679) == 67.9


def test_decode_temp_returns_none_for_sentinel():
    assert decode_temp(-5002) is None
    assert decode_temp(0) is None  # rawTemperature=0 means not available


def test_get_equipment_description_idle():
    assert get_equipment_description("") == "idle"


def test_get_equipment_description_running():
    assert get_equipment_description("heatPump") == "heatPump"
    assert get_equipment_description("compCool1,fan") == "compCool1,fan"


def test_get_active_hold_returns_none_when_no_events():
    assert get_active_hold([]) is None


def test_get_active_hold_returns_none_when_no_running_hold():
    events = [{"type": "hold", "running": False, "name": "hold"}]
    assert get_active_hold(events) is None


def test_get_active_hold_returns_running_hold():
    events = [
        {
            "type": "hold",
            "running": True,
            "name": "auto",
            "endDate": "2026-03-17",
            "endTime": "10:00:00",
            "isIndefinite": False,
            "coolHoldTemp": 740,
            "heatHoldTemp": 690,
        }
    ]
    hold = get_active_hold(events)
    assert hold is not None
    assert hold["end"] == "2026-03-17 10:00:00"
    assert hold["cool_temp"] == 74.0
    assert hold["heat_temp"] == 69.0


def test_get_active_hold_indefinite():
    events = [
        {
            "type": "hold",
            "running": True,
            "name": "hold",
            "endDate": "2028-12-29",
            "endTime": "08:51:45",
            "isIndefinite": True,
            "coolHoldTemp": 600,
            "heatHoldTemp": 550,
        }
    ]
    hold = get_active_hold(events)
    assert hold["end"] == "indefinite"


def test_extract_thermostat_status():
    thermostat = {
        "name": "Downstairs",
        "runtime": {
            "actualTemperature": 704,
            "actualHumidity": 58,
            "actualAQScore": 51,
            "actualVOC": 520,
            "actualCO2": 508,
        },
        "equipmentStatus": "",
        "settings": {"hvacMode": "heat"},
        "events": [],
        "program": {"currentClimateRef": "smart1"},
        "weather": {
            "forecasts": [
                {
                    "temperature": 614,
                    "condition": "Rain",
                    "relativeHumidity": 89,
                    "windSpeed": 13,
                    "windDirection": "SW",
                }
            ]
        },
    }
    status = extract_thermostat_status(thermostat)
    assert status["temp"] == 70.4
    assert status["humidity"] == 58
    assert status["equipment"] == "idle"
    assert status["hvac_mode"] == "heat"
    assert status["climate_ref"] == "smart1"
    assert status["hold"] is None
    assert status["aq_score"] == 51
    assert status["voc"] == 520
    assert status["co2"] == 508
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/climate/ecobee/test_status.py -v
```
Expected: `ImportError`

**Step 3: Write implementation**

```python
# climate/ecobee/status.py


ECOBEE_SENTINEL = -5002


def decode_temp(raw: int) -> float | None:
    """Convert Ecobee's tenths-of-degree int to float °F. Returns None for sentinel/zero."""
    if raw == ECOBEE_SENTINEL or raw == 0:
        return None
    return raw / 10


def get_equipment_description(equipment_status: str) -> str:
    """Return human description of equipment status. Empty string means idle."""
    return equipment_status if equipment_status else "idle"


def get_active_hold(events: list) -> dict | None:
    """Return the first running hold event as a simplified dict, or None."""
    for event in events:
        if event.get("type") == "hold" and event.get("running"):
            end = (
                "indefinite"
                if event.get("isIndefinite")
                else f"{event['endDate']} {event['endTime']}"
            )
            return {
                "end": end,
                "cool_temp": decode_temp(event["coolHoldTemp"]),
                "heat_temp": decode_temp(event["heatHoldTemp"]),
            }
    return None


def extract_thermostat_status(thermostat: dict) -> dict:
    """Extract a flat status dict from a raw thermostat API response."""
    runtime = thermostat.get("runtime", {})
    forecasts = thermostat.get("weather", {}).get("forecasts", [])
    current_weather = forecasts[0] if forecasts else {}

    aq_score = runtime.get("actualAQScore", ECOBEE_SENTINEL)
    voc = runtime.get("actualVOC", ECOBEE_SENTINEL)
    co2 = runtime.get("actualCO2", ECOBEE_SENTINEL)

    return {
        "name": thermostat.get("name"),
        "temp": decode_temp(runtime.get("actualTemperature", 0)),
        "humidity": runtime.get("actualHumidity"),
        "equipment": get_equipment_description(thermostat.get("equipmentStatus", "")),
        "hvac_mode": thermostat.get("settings", {}).get("hvacMode"),
        "climate_ref": thermostat.get("program", {}).get("currentClimateRef"),
        "hold": get_active_hold(thermostat.get("events", [])),
        "aq_score": None if aq_score == ECOBEE_SENTINEL else aq_score,
        "voc": None if voc == ECOBEE_SENTINEL else voc,
        "co2": None if co2 == ECOBEE_SENTINEL else co2,
        "weather": {
            "temp": decode_temp(current_weather.get("temperature", 0)),
            "condition": current_weather.get("condition"),
            "humidity": current_weather.get("relativeHumidity"),
            "wind_speed": current_weather.get("windSpeed"),
            "wind_direction": current_weather.get("windDirection"),
        } if current_weather else None,
    }


def format_status(statuses: list[dict]) -> str:
    """Format a list of thermostat status dicts as a human-readable string."""
    lines = []

    for s in statuses:
        temp = f"{s['temp']}°F" if s["temp"] is not None else "?°F"
        humidity = f"{s['humidity']}%" if s["humidity"] is not None else "?"
        equipment = s["equipment"]
        hvac = s["hvac_mode"] or "?"

        hold_str = ""
        if s["hold"]:
            end = s["hold"]["end"]
            hold_str = f"  hold until {end}"

        climate = s["climate_ref"] or ""
        line = f"{s['name']:<14} {temp:<8} {humidity:<5} {equipment:<10} {climate:<14} {hvac}{hold_str}"
        lines.append(line.rstrip())

    # Weather: use first thermostat's weather (they share the same feed by location)
    weather_added = False
    for s in statuses:
        w = s.get("weather")
        if w and w.get("temp") is not None and not weather_added:
            cond = w["condition"] or ""
            wind = f"{w['wind_speed']}mph {w['wind_direction']}" if w["wind_speed"] else ""
            lines.append(f"{'Outdoor':<14} {w['temp']}°F     {w['humidity']}%   {cond} {wind}".rstrip())
            weather_added = True
            break

    # Air quality section
    aq_lines = []
    for s in statuses:
        if s["aq_score"] is not None:
            parts = [f"AQ {s['aq_score']}"]
            if s["voc"] is not None:
                parts.append(f"VOC {s['voc']}ppm")
            if s["co2"] is not None:
                parts.append(f"CO2 {s['co2']}ppm")
            aq_lines.append(f"  {s['name']}: {'  '.join(parts)}")

    if aq_lines:
        lines.append("")
        lines.append("Air quality:")
        lines.extend(aq_lines)

    return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/climate/ecobee/test_status.py -v
```
Expected: all tests PASS

**Step 5: Commit**

```bash
git add climate/ecobee/status.py tests/climate/ecobee/test_status.py
git commit -m "feat: add status.py with thermostat state extraction and formatting"
```

---

### Task 9: Add `status` subcommand to `climate/sync.py`

**Files:**
- Modify: `climate/sync.py`

**Step 1: Add import**

```python
from climate.ecobee import auth, comforts, schedule, status
from climate.ecobee.thermostats import load_thermostats, get_managed_thermostats
```

**Step 2: Add `cmd_status` function**

```python
def cmd_status(args) -> None:
    ecobee = auth.make_ecobee()

    registry_path = Path(__file__).parent / "config" / "thermostats.yaml"
    registry = load_thermostats(registry_path)
    managed = get_managed_thermostats(registry)
    managed_ids = {thermostat_id for _, thermostat_id in managed}

    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        print("Failed to fetch thermostat data from Ecobee.")
        sys.exit(1)

    statuses = [
        status.extract_thermostat_status(t)
        for t in ecobee.thermostats
        if t["identifier"] in managed_ids
    ]

    if args.json:
        import json
        print(json.dumps({"thermostats": statuses}, indent=2, default=str))
    else:
        print(status.format_status(statuses))
```

**Step 3: Register the subcommand in `main()`**

```python
status_parser = subparsers.add_parser("status", help="Show current thermostat state")
status_parser.add_argument(
    "--json",
    action="store_true",
    help="Output as JSON",
)
subparsers.choices["status"].set_defaults(func=cmd_status)
```

**Step 4: Smoke test**

```bash
uv run python -m climate.sync status
```
Expected: table showing Downstairs and Upstairs temps, humidity, equipment, no Cottage.

```bash
uv run python -m climate.sync status --json
```
Expected: JSON output with `thermostats` array, no Cottage.

**Step 5: Commit**

```bash
git add climate/sync.py
git commit -m "feat: add status subcommand showing current thermostat state"
```

---

### Task 10: Update `Justfile`

**Files:**
- Modify: `Justfile`

**Step 1: Update all ecobee tasks**

Replace all `ecobee-*` tasks with `climate-*`, update module path from `ecobee.sync` to `climate.sync`:

```just
set dotenv-load

# First-time setup: PIN flow + thermostat discovery
climate-auth:
    uv run python -m climate.sync auth

# List thermostats and climate refs on this account
climate-list:
    uv run python -m climate.sync list

# Show current thermostat state
climate-status *ARGS:
    uv run python -m climate.sync status {{ARGS}}

# Push schedule.yaml to Ecobee
climate-sync *ARGS:
    uv run python -m climate.sync sync {{ARGS}}

# Preview expanded schedule without pushing
climate-sync-dry *ARGS:
    uv run python -m climate.sync sync --dry-run {{ARGS}}

# Validate schedule.yaml matches the live schedule on Ecobee
climate-validate *ARGS:
    uv run python -m climate.sync validate {{ARGS}}

# Snapshot current comfort mode temps from Ecobee into comforts.yaml
climate-comforts-capture *ARGS:
    uv run python -m climate.sync capture-comforts {{ARGS}}

# Push comforts.yaml setpoints to Ecobee
climate-comforts-sync *ARGS:
    uv run python -m climate.sync sync-comforts {{ARGS}}

# Preview comfort changes without pushing
climate-comforts-sync-dry *ARGS:
    uv run python -m climate.sync sync-comforts --dry-run {{ARGS}}

# Install dependencies (run once after clone)
install:
    uv sync
```

**Step 2: Verify just tasks work**

```bash
just climate-status
```
Expected: same output as the smoke test above.

**Step 3: Commit**

```bash
git add Justfile
git commit -m "chore: rename Justfile tasks from ecobee-* to climate-*"
```

---

### Task 11: Remove old `ecobee/` directory

**Files:**
- Delete: `ecobee/` (entire directory)

**Step 1: Run all tests first**

```bash
uv run pytest tests/ -v
```
Expected: all tests PASS

**Step 2: Run a final smoke test of every just task (dry-run where available)**

```bash
just climate-list
just climate-status
just climate-sync-dry
just climate-validate
just climate-comforts-sync-dry
```
Expected: all commands run without errors.

**Step 3: Delete old directory**

```bash
git rm -r ecobee/
```

**Step 4: Commit**

```bash
git commit -m "chore: remove old ecobee/ directory, fully migrated to climate/"
```

---

### Task 12: Update `CLAUDE.md` and docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/ecobee-setup.md` (if it references old paths)

**Step 1: Update `CLAUDE.md` Directories section**

```markdown
## Directories

- `climate/`: HVAC/climate automation (Ecobee schedule, comfort setpoints, status)
  - `climate/ecobee/`: Python package (auth, schedule, comforts, status)
  - `climate/config/`: YAML config (thermostats, schedule, comforts)
  - `climate/spec/`: specs and docs (hvac-spec.md)
- `network/`: Network diagnostic and profiling scripts; see `network/CLAUDE.md`
```

**Step 2: Check `docs/ecobee-setup.md` for stale path references**

```bash
grep -n "ecobee/" docs/ecobee-setup.md
```

Update any references to `ecobee/schedule.yaml`, `ecobee/comforts.yaml`, etc. to their new paths under `climate/`.

**Step 3: Commit**

```bash
git add CLAUDE.md docs/
git commit -m "docs: update CLAUDE.md and docs to reflect climate/ restructure"
```
