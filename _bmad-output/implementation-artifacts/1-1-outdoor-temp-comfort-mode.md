# Story 1.1: Outdoor Temperature Comfort Mode

Status: done

## Story

As a homeowner,
I want the Ecobee schedule to automatically switch between Comfort Cool and Comfort Heat based on current outdoor temperature from nearby Ambient Weather Network stations,
so that I don't have to manually change the comfort mode when the seasons transition.

## Acceptance Criteria

1. `aioambient==2024.08.0` is installed and `HOME_LAT`/`HOME_LON` are documented in `.env.template` and loaded from 1Password.
2. `climate/ambient/client.py` fetches outdoor temp from one or more station MACs concurrently (not serially), with a configurable timeout, graceful error handling for network failures, plausibility guard, and data-freshness check. Only `RequestError` and `TimeoutError` are caught — no bare `Exception`.
3. `climate/config/weather.yaml` exists with valid YAML structure, and at least one station MAC is populated (discovered via `just climate-weather-discover`) and confirmed reporting a plausible current temp.
4. `just climate-weather-discover [--radius N]` lists nearby outdoor stations with MAC, name, and current temp.
5. `just climate-weather` prints current outdoor temp, the age of the reading (e.g. `4 min old`), the station MAC it came from, and whether heat/cool/neutral is recommended.
6. `just climate-comfort-switch heat|cool|auto` rewrites `schedule.yaml` and syncs to Ecobee; `auto` reads outdoor temp and applies thresholds with a hysteresis band.
7. `_apply_comfort_mode` replaces only `climate: smart1/smart2` YAML value lines — not comment text — and is covered by tests.
8. If Ecobee sync fails after `schedule.yaml` is rewritten, the file is restored to its original content.
9. All new functions have unit tests; test infrastructure (`tests/` package, `pytest` config) is initialized. Includes tests for `is_temp_plausible` and `is_data_fresh` as standalone pure-function tests.
10. `climate/spec/hvac-spec.md` Comfort mode semantics are updated with exact threshold values, and a new Seasonal switching section is added referencing `just climate-comfort-switch auto`. (Schedule tables already reflect Comfort Heat as of this session — no table changes needed.)

## Tasks / Subtasks

- [x] Task 1: Dependency and env setup (AC: 1)
  - [x] 1.1 Add `aioambient==2024.08.0` to `pyproject.toml` dependencies
  - [x] 1.2 Add `HOME_LAT` and `HOME_LON` to `.env.template` referencing 1Password `picklehome/Home/latitude` and `picklehome/Home/longitude`
  - [x] 1.3 Run `just dotenv` and `uv sync`; verify `import aioambient` works

- [x] Task 2: Test infrastructure (AC: 9)
  - [x] 2.1 Create `tests/__init__.py` (empty)
  - [x] 2.2 Create `tests/ambient/__init__.py` (empty)
  - [x] 2.3 Add `[tool.pytest.ini_options] testpaths = ["tests"]` to `pyproject.toml`
  - [x] 2.4 Verify `uv run pytest --collect-only` shows 0 errors

- [x] Task 3: Ambient weather client module (AC: 2, 9)
  - [x] 3.1 Write failing tests in `tests/ambient/test_client.py` covering all public functions including `is_temp_plausible` and `is_data_fresh` (see Dev Notes)
  - [x] 3.2 Confirm tests fail (ImportError expected)
  - [x] 3.3 Implement `climate/ambient/__init__.py` (empty)
  - [x] 3.4 Implement `climate/ambient/client.py` — concurrent station fetch with timeout, explicit exception handling only (`RequestError`, `TimeoutError`), plausibility guard, and freshness check (see Dev Notes)
  - [x] 3.5 Run `uv run pytest tests/ambient/ -v` — all tests must pass

- [x] Task 4: Weather config (AC: 3)
  - [x] 4.1 Create `climate/config/weather.yaml` with valid YAML list syntax (see Dev Notes for correct structure)
  - [x] 4.2 Add `load_weather_config` and `get_configured_macs` to `climate/ambient/client.py` — imports at top of file
  - [x] 4.3 Write tests for `load_weather_config` (missing file, empty file, valid file) and `get_configured_macs`
  - [x] 4.4 Run full test suite — all pass

- [x] Task 5: discover-stations CLI command (AC: 4)
  - [x] 5.1 Add `cmd_weather_discover` to `climate/sync.py` with explicit `HOME_LAT`/`HOME_LON` guard (see Dev Notes)
  - [x] 5.2 Wire `discover-stations` subparser in `main()` with `--radius` arg
  - [x] 5.3 Add `climate-weather-discover *ARGS` task to `Justfile`
  - [x] 5.4 Run `just --list | grep weather` — task appears
  - [x] 5.5 Run `just climate-weather-discover --radius 2` — makes live network call, lists stations (note: requires network + `just dotenv` for HOME_LAT/HOME_LON)

- [x] Task 6: weather CLI command (AC: 5)
  - [x] 6.1 Add `cmd_weather` to `climate/sync.py` — output includes temp, reading age in minutes, source MAC, and heat/cool/neutral recommendation (see Dev Notes)
  - [x] 6.2 Wire `weather` subparser; import `DEFAULT_WEATHER_PATH` from `climate.ambient.client` at top of `sync.py`
  - [x] 6.3 Add `climate-weather *ARGS` task to `Justfile`
  - [x] 6.4 Run `just climate-weather` — output shows e.g. `Outdoor temp: 45.2°F (4 min old, AA:BB:CC:DD:EE:FF)` (requires stations in weather.yaml)

- [x] Task 7: comfort-switch CLI command (AC: 6, 7, 8)
  - [x] 7.1 Write failing tests for `_apply_comfort_mode` (see Dev Notes for correct regex — comment-safe)
  - [x] 7.2 Implement `_apply_comfort_mode` in `climate/sync.py` (imports at top of file)
  - [x] 7.3 Run `uv run pytest tests/test_comfort_switch.py -v` — all pass
  - [x] 7.4 Implement `cmd_comfort_switch` with: auto mode, dry-run, atomic file write with restore on sync failure (see Dev Notes)
  - [x] 7.5 Wire `comfort-switch` subparser in `main()`
  - [x] 7.6 Add `climate-comfort-switch MODE *ARGS` and `climate-comfort-switch-dry MODE *ARGS` to `Justfile`
  - [x] 7.7 Write tests for `cmd_comfort_switch` covering: heat, cool, auto-heat, auto-cool, hysteresis band, sync failure rollback
  - [x] 7.8 Run full test suite — all pass
  - [x] 7.9 Run `just climate-comfort-switch-dry auto` — dry-run output shows changed lines (requires weather.yaml populated)

- [x] Task 8: hvac-spec.md update (AC: 10)
  - [x] 8.1 Update Comfort mode semantics section with exact replacement text (see Dev Notes) — schedule tables already show Comfort Heat correctly from current session, no table changes needed
  - [x] 8.2 Add new "Seasonal switching" section after Comfort mode semantics (see Dev Notes for exact text)

## Dev Notes

### Project Structure

- CLI entry point: `climate/sync.py` — `python -m climate.sync <subcommand>`. Add new subcommands here following existing pattern.
- Module home for new code: `climate/ambient/` (new package)
- Config files: `climate/config/` — follow YAML convention of existing files
- Task runner: `Justfile` — follow existing `*ARGS` pattern for passthrough args
- Secrets: `.env.template` → 1Password → `.env` via `just dotenv`. See `CLAUDE.md`.
- Tests: `tests/` (new — no existing tests). `pytest` is already in `dev` dependencies.

### aioambient API (source: vendor/ha-core manifest.json + coordinator.py)

- Version: `aioambient==2024.08.0` (pinned from HA's `manifest.json`)
- `OpenAPI()` — no auth required, public data
- `await api.get_devices_by_location(lat, lon, radius=miles)` → list of station dicts
- `await api.get_device_details(mac)` → station dict with `lastData.tempf`
- Station dict keys: `macAddress`, `info.name`, `info.coords.location`, `info.indoor`, `lastData.tempf`
- HA catches `aioambient.errors.RequestError` — we must do the same

### client.py — Concurrent fetch with timeout, plausibility, and freshness (Task 3)

All module-level imports MUST be at the top of the file (PEP 8).

**CRITICAL:** Only catch `RequestError` and `asyncio.TimeoutError` in `_fetch_temp` — no bare `Exception`. Unexpected errors must surface, not be silently swallowed.

```python
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from aioambient import OpenAPI
from aioambient.errors import RequestError

FETCH_TIMEOUT = 10        # seconds — HTTP request timeout
MAX_DATA_AGE_MINUTES = 30 # readings older than this are treated as stale
TEMP_MIN_PLAUSIBLE = -20.0  # °F
TEMP_MAX_PLAUSIBLE = 120.0  # °F

DEFAULT_WEATHER_PATH = Path(__file__).parent.parent / "config" / "weather.yaml"


def is_temp_plausible(temp: float) -> bool:
    """Return True if temp is within a physically reasonable range for this region."""
    return TEMP_MIN_PLAUSIBLE <= temp <= TEMP_MAX_PLAUSIBLE


def is_data_fresh(last_data: dict, max_age_minutes: int = MAX_DATA_AGE_MINUTES) -> bool:
    """Return True if lastData timestamp is recent enough to trust."""
    ts = last_data.get("dateutc")
    if ts is None:
        return False
    age_minutes = (time.time() - ts / 1000) / 60
    return age_minutes <= max_age_minutes


def get_data_age_minutes(last_data: dict) -> float | None:
    """Return age of lastData in minutes, or None if no timestamp."""
    ts = last_data.get("dateutc")
    if ts is None:
        return None
    return (time.time() - ts / 1000) / 60


async def _fetch_temp(mac: str) -> tuple[str, float, float] | None:
    """Fetch temp from a single station.

    Returns (mac, tempf, age_minutes) if reading is valid, or None if unavailable/stale/implausible.
    Only catches expected network errors — programming errors will propagate.
    """
    try:
        api = OpenAPI()
        data = await asyncio.wait_for(api.get_device_details(mac), timeout=FETCH_TIMEOUT)
        last_data = data.get("lastData", {})
        temp = last_data.get("tempf")
        if temp is None:
            return None
        if not is_data_fresh(last_data):
            return None
        if not is_temp_plausible(temp):
            return None
        age = get_data_age_minutes(last_data) or 0.0
        return (mac, temp, age)
    except (RequestError, asyncio.TimeoutError):
        return None


async def _fetch_all_temps(macs: list[str]) -> list[tuple[str, float, float] | None]:
    """Fetch temps from all stations concurrently."""
    return await asyncio.gather(*[_fetch_temp(mac) for mac in macs])


def get_outdoor_temp_from_stations(macs: list[str]) -> tuple[str, float, float] | None:
    """Return (mac, tempf, age_minutes) from first valid station, or None."""
    if not macs:
        return None
    results = asyncio.run(_fetch_all_temps(macs))
    return next((r for r in results if r is not None), None)


async def _discover(lat: float, lon: float, radius_miles: float) -> list[dict[str, Any]]:
    try:
        api = OpenAPI()
        stations = await asyncio.wait_for(
            api.get_devices_by_location(lat, lon, radius=radius_miles),
            timeout=FETCH_TIMEOUT,
        )
        return [s for s in stations if not s.get("info", {}).get("indoor", False)]
    except (RequestError, asyncio.TimeoutError) as e:
        raise RuntimeError(f"Failed to discover stations: {e}") from e


def discover_stations_sync(lat: float, lon: float, radius_miles: float = 1.0) -> list[dict[str, Any]]:
    return asyncio.run(_discover(lat, lon, radius_miles))


def load_weather_config(path: Path = DEFAULT_WEATHER_PATH) -> dict:
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except OSError as e:
        print(f"Cannot read weather config: {path}: {e}")
        sys.exit(1)


def get_configured_macs(config: dict) -> list[str]:
    return [s["mac"] for s in config.get("stations", []) if "mac" in s]
```

Note: `get_outdoor_temp_from_stations` now returns a 3-tuple `(mac, temp, age_minutes)` instead of bare `float | None`. Update all callers (`cmd_weather`, `cmd_comfort_switch`) accordingly.

### Tests for client.py (Task 3.1)

Must cover ALL public functions. Use `unittest.mock.patch` and `AsyncMock`.

```python
# tests/ambient/test_client.py
import time
from unittest.mock import AsyncMock, patch
import pytest

from climate.ambient.client import (
    is_temp_plausible,
    is_data_fresh,
    get_outdoor_temp_from_stations,
    discover_stations_sync,
    load_weather_config,
    get_configured_macs,
)

# --- is_temp_plausible ---

def test_plausible_temp_passes():
    assert is_temp_plausible(45.0) is True

def test_implausible_low_temp():
    assert is_temp_plausible(-99.0) is False

def test_implausible_high_temp():
    assert is_temp_plausible(150.0) is False

def test_boundary_min_plausible():
    assert is_temp_plausible(-20.0) is True

def test_boundary_max_plausible():
    assert is_temp_plausible(120.0) is True

# --- is_data_fresh ---

def test_fresh_data():
    last_data = {"dateutc": int(time.time() * 1000) - 60_000}  # 1 minute ago
    assert is_data_fresh(last_data) is True

def test_stale_data():
    last_data = {"dateutc": int(time.time() * 1000) - 3_600_000}  # 1 hour ago
    assert is_data_fresh(last_data) is False

def test_missing_timestamp():
    assert is_data_fresh({}) is False

def test_custom_max_age():
    last_data = {"dateutc": int(time.time() * 1000) - 600_000}  # 10 minutes ago
    assert is_data_fresh(last_data, max_age_minutes=5) is False
    assert is_data_fresh(last_data, max_age_minutes=15) is True

# --- get_outdoor_temp_from_stations ---

def test_get_outdoor_temp_returns_first_valid():
    # Returns (mac, temp, age) tuples; None for failures
    with patch("climate.ambient.client._fetch_all_temps",
               new=AsyncMock(return_value=[None, ("BB", 52.3, 4.0), ("CC", 48.0, 2.0)])):
        result = get_outdoor_temp_from_stations(["A", "B", "C"])
    assert result == ("BB", 52.3, 4.0)

def test_get_outdoor_temp_returns_none_when_all_fail():
    with patch("climate.ambient.client._fetch_all_temps",
               new=AsyncMock(return_value=[None, None])):
        result = get_outdoor_temp_from_stations(["A", "B"])
    assert result is None

def test_get_outdoor_temp_empty_macs():
    assert get_outdoor_temp_from_stations([]) is None

# --- discover_stations_sync ---

def test_discover_returns_outdoor_stations():
    outdoor = {"macAddress": "A", "info": {"indoor": False}, "lastData": {"tempf": 50.0}}
    with patch("climate.ambient.client._discover", new=AsyncMock(return_value=[outdoor])):
        result = discover_stations_sync(33.0, -84.0, 1.0)
    assert len(result) == 1
    assert result[0]["macAddress"] == "A"

# --- load_weather_config ---

def test_load_weather_config_valid(tmp_path):
    cfg = tmp_path / "weather.yaml"
    cfg.write_text("stations:\n  - mac: AA:BB\nthresholds:\n  heat_below: 60\n  cool_above: 65\n")
    result = load_weather_config(cfg)
    assert result["thresholds"]["heat_below"] == 60

def test_load_weather_config_empty(tmp_path):
    cfg = tmp_path / "weather.yaml"
    cfg.write_text("")
    assert load_weather_config(cfg) == {}

def test_load_weather_config_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        load_weather_config(tmp_path / "nonexistent.yaml")

# --- get_configured_macs ---

def test_get_configured_macs():
    config = {"stations": [{"mac": "AA:BB"}, {"name": "no-mac"}, {"mac": "CC:DD"}]}
    assert get_configured_macs(config) == ["AA:BB", "CC:DD"]

def test_get_configured_macs_empty():
    assert get_configured_macs({}) == []
```

### weather.yaml correct structure (Task 4.1)

The `[]` inline syntax then indented comments is misleading. Use this instead:

```yaml
# climate/config/weather.yaml
# Outdoor temperature sources and comfort-mode thresholds.
# Run 'just climate-weather-discover' to find nearby stations.
# Run 'just climate-weather' to see current outdoor temp.

# Stations tried in order — first responding station wins.
# Add discovered MACs here:
stations: []

# Temperature thresholds (°F) for comfort mode selection.
# Below heat_below  → Comfort Heat (smart2)
# Above cool_above  → Comfort Cool (smart1)
# Between the two   → no change (hysteresis band)
thresholds:
  heat_below: 60
  cool_above: 65
```

### cmd_weather — with data age output (Task 6.1)

`get_outdoor_temp_from_stations` now returns `(mac, temp, age_minutes) | None`. Use all three fields:

```python
def cmd_weather(args) -> None:
    from climate.ambient.client import load_weather_config, get_configured_macs, get_outdoor_temp_from_stations

    config = load_weather_config(args.weather)
    macs = get_configured_macs(config)

    if not macs:
        print("No stations configured. Run 'just climate-weather-discover' and add MACs to weather.yaml.")
        sys.exit(1)

    result = get_outdoor_temp_from_stations(macs)
    if result is None:
        print("Could not read a fresh, plausible outdoor temp from any configured station.")
        sys.exit(1)

    mac, temp, age_minutes = result
    age_str = f"{age_minutes:.0f} min old"

    thresholds = config.get("thresholds", {})
    heat_below = thresholds.get("heat_below", 60)
    cool_above = thresholds.get("cool_above", 65)

    if temp < heat_below:
        mode = f"heat  → Comfort Heat (smart2)"
    elif temp > cool_above:
        mode = f"cool  → Comfort Cool (smart1)"
    else:
        mode = f"neutral  (between {heat_below}°F–{cool_above}°F, no change recommended)"

    print(f"Outdoor temp: {temp}°F  ({age_str}, {mac})")
    print(f"Comfort mode: {mode}")
```

Also update `cmd_comfort_switch` auto mode: unpack the tuple from `get_outdoor_temp_from_stations`:
```python
result = get_outdoor_temp_from_stations(macs)
if result is None:
    print("Could not read outdoor temp. Cannot auto-select comfort mode.")
    sys.exit(1)
mac, temp, age_minutes = result
```

### cmd_weather_discover env guard (Task 5.1)

Do NOT use `or`-chained `sys.exit`. Use explicit checks:

```python
def cmd_weather_discover(args) -> None:
    import os
    from climate.ambient.client import discover_stations_sync

    lat_str = os.environ.get("HOME_LAT", "")
    lon_str = os.environ.get("HOME_LON", "")
    if not lat_str or not lon_str:
        print("HOME_LAT and HOME_LON must be set. Run 'just dotenv'.")
        sys.exit(1)
    try:
        lat, lon = float(lat_str), float(lon_str)
    except ValueError:
        print(f"HOME_LAT/HOME_LON are not valid floats: {lat_str!r}, {lon_str!r}")
        sys.exit(1)

    print(f"Searching within {args.radius} mile(s) of ({lat:.4f}, {lon:.4f})...")
    try:
        stations = discover_stations_sync(lat, lon, radius_miles=args.radius)
    except RuntimeError as e:
        print(f"Discovery failed: {e}")
        sys.exit(1)

    if not stations:
        print("No outdoor stations found. Try --radius 2 or larger.")
        sys.exit(1)

    print(f"\nFound {len(stations)} outdoor station(s):\n")
    for s in stations:
        mac = s.get("macAddress", "unknown")
        name = (s.get("info", {}).get("name")
                or s.get("info", {}).get("coords", {}).get("location", "unnamed"))
        temp = s.get("lastData", {}).get("tempf")
        temp_str = f"{temp}°F" if temp is not None else "no temp"
        print(f"  {mac}  {name}  ({temp_str})")
    print("\nAdd desired MACs to climate/config/weather.yaml under 'stations:'.")
```

### _apply_comfort_mode — comment-safe regex (Task 7.2)

The replacement must target only the YAML value, not comment text. Match `climate:` followed by the value:

```python
import re

def _apply_comfort_mode(schedule_text: str, mode: str) -> str:
    """Swap smart1↔smart2 in YAML `climate:` value positions only (not comments).

    mode='heat' → smart1 → smart2 (Comfort Heat)
    mode='cool' → smart2 → smart1 (Comfort Cool)
    """
    if mode == "heat":
        return re.sub(r'(climate:\s*)smart1\b', r'\1smart2', schedule_text)
    elif mode == "cool":
        return re.sub(r'(climate:\s*)smart2\b', r'\1smart1', schedule_text)
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use 'heat' or 'cool'.")
```

Tests for this (Task 7.1):

```python
# tests/test_comfort_switch.py
from climate.sync import _apply_comfort_mode
import pytest

SCHEDULE_WITH_COOL = "        - time: \"06:00\"\n          climate: smart1\n"
SCHEDULE_WITH_HEAT = "        - time: \"06:00\"\n          climate: smart2\n"
SCHEDULE_WITH_COMMENT = "          climate: smart1  # was smart2 before\n"

def test_heat_replaces_cool_value():
    result = _apply_comfort_mode(SCHEDULE_WITH_COOL, "heat")
    assert "climate: smart2" in result
    assert "climate: smart1" not in result

def test_cool_replaces_heat_value():
    result = _apply_comfort_mode(SCHEDULE_WITH_HEAT, "cool")
    assert "climate: smart1" in result
    assert "climate: smart2" not in result

def test_comment_text_not_replaced():
    # Comment mentions "smart2" but value is smart1 — only value should flip
    result = _apply_comfort_mode(SCHEDULE_WITH_COMMENT, "heat")
    assert "climate: smart2" in result
    assert "# was smart2 before" in result  # comment preserved

def test_non_climate_smart_refs_untouched():
    text = "# smart1 is for cooling\n          climate: smart1\n"
    result = _apply_comfort_mode(text, "heat")
    assert "# smart1 is for cooling" in result  # comment unchanged
    assert "climate: smart2" in result

def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown mode"):
        _apply_comfort_mode("", "warm")

def test_no_change_when_already_set():
    result = _apply_comfort_mode(SCHEDULE_WITH_HEAT, "heat")
    assert result == SCHEDULE_WITH_HEAT
```

### cmd_comfort_switch — atomic write + rollback (Task 7.4)

Use `argparse.Namespace` (not an inner class). Restore original on sync failure:

```python
import argparse

def cmd_comfort_switch(args) -> None:
    from climate.ambient.client import load_weather_config, get_configured_macs, get_outdoor_temp_from_stations

    mode = args.mode

    if mode == "auto":
        config = load_weather_config(args.weather)
        macs = get_configured_macs(config)
        if not macs:
            print("No stations configured in weather.yaml. Run 'just climate-weather-discover'.")
            sys.exit(1)
        temp = get_outdoor_temp_from_stations(macs)
        if temp is None:
            print("Could not read outdoor temp from any configured station.")
            sys.exit(1)
        thresholds = config.get("thresholds", {})
        heat_below = thresholds.get("heat_below", 60)
        cool_above = thresholds.get("cool_above", 65)
        if temp < heat_below:
            mode = "heat"
        elif temp > cool_above:
            mode = "cool"
        else:
            print(f"Outdoor temp {temp}°F is in hysteresis band ({heat_below}–{cool_above}°F). No change.")
            return
        print(f"Outdoor temp: {temp}°F → switching to {mode}")

    schedule_path = args.schedule
    original = schedule_path.read_text()
    updated = _apply_comfort_mode(original, mode)

    if updated == original:
        print(f"Schedule already set to {mode} comfort. Nothing to do.")
        return

    if args.dry_run:
        print(f"[dry run] Would switch to {mode} comfort:")
        for i, (old, new) in enumerate(zip(original.splitlines(), updated.splitlines()), 1):
            if old != new:
                print(f"  line {i}: {old.strip()!r} → {new.strip()!r}")
        return

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
```

### hvac-spec.md exact update text (Task 8.1)

Replace:
```
- **Comfort Heat** — primary occupied mode when it's cold out. Target ~70°F by heating. Not currently in use (treating as warm season).
```
With:
```
- **Comfort Heat** — primary occupied mode when it's cold out. Target ~70°F by heating. Active when outdoor temp < 60°F (threshold configurable in `climate/config/weather.yaml`).
- **Comfort Cool** — primary occupied mode when it's warm out. Target ~70°F by cooling. Active when outdoor temp > 65°F.
```

Add a new section after Comfort mode semantics:

```
### Seasonal switching

Run `just climate-comfort-switch auto` to read the current outdoor temp from configured Ambient Weather Network stations and switch the schedule automatically. The command uses a hysteresis band (60–65°F) to avoid unnecessary switching near the threshold. Station MACs and thresholds are configured in `climate/config/weather.yaml`.
```

Update schedule table notes to replace "Not currently used in schedule" with "Active when outdoor temp < 60°F" for Comfort Heat rows.

### References

- [Source: vendor/ha-core/homeassistant/components/ambient_network/manifest.json] — aioambient version
- [Source: vendor/ha-core/homeassistant/components/ambient_network/coordinator.py] — API usage pattern, RequestError handling
- [Source: vendor/ha-core/homeassistant/components/ambient_network/config_flow.py] — discover by lat/lon, indoor filter
- [Source: vendor/ha-core/homeassistant/components/ambient_network/sensor.py] — `tempf` field key
- [Source: climate/sync.py] — existing CLI subcommand pattern
- [Source: climate/ecobee/auth.py] — existing KeychainEcobee pattern (for reference only, not modified)
- [Source: docs/plans/2026-03-17-outdoor-temp-comfort-mode.md] — original superpowers plan
- [Source: CLAUDE.md] — 1Password / dotenv workflow

## Dev Agent Record

### Agent Model Used

claude-sonnet-4-6

### Debug Log References

### Completion Notes List

- Tasks 1–8 implemented. 43 tests pass (18 ambient client, 12 comfort-switch, 13 pre-existing ecobee tests). No regressions.
- `aioambient==2024.08.0` added to `pyproject.toml`; `HOME_LAT`/`HOME_LON` added to `.env.template`.
- `climate/ambient/client.py` implements concurrent station fetch via `asyncio.gather`, explicit `(RequestError, asyncio.TimeoutError)` only, plausibility/freshness guards, returning 3-tuple `(mac, temp, age_minutes)`.
- `_apply_comfort_mode` uses comment-safe regex `(climate:\s*)smart1\b` — only targets YAML value positions.
- `cmd_comfort_switch` does atomic write + rollback: writes updated schedule, calls `cmd_sync`, restores original on `SystemExit(non-zero)`.
- 3 subtasks require manual live verification with real credentials: 5.5 (discover), 6.4 (weather), 7.9 (comfort-switch-dry). Also AC 3 requires adding a real station MAC to `weather.yaml` via `just climate-weather-discover`.
- `hvac-spec.md` Comfort mode semantics updated with threshold values; Seasonal switching section added; Comfort Heat table notes updated from "Not currently used" to "Active when outdoor temp < 60°F".

### File List

- `pyproject.toml` — added `aioambient==2024.08.0` dependency; added `[tool.pytest.ini_options]`
- `.env.template` — added `HOME_LAT`, `HOME_LON`
- `climate/ambient/__init__.py` — new empty package init
- `climate/ambient/client.py` — new: concurrent fetch, plausibility/freshness guards, discover, config loading
- `climate/config/weather.yaml` — new: stations list + threshold config
- `climate/sync.py` — added `import re`, `DEFAULT_WEATHER_PATH` import; new `cmd_weather_discover`, `cmd_weather`, `_apply_comfort_mode`, `cmd_comfort_switch`; wired 3 new subparsers
- `Justfile` — added `climate-weather-discover`, `climate-weather`, `climate-comfort-switch`, `climate-comfort-switch-dry`
- `climate/spec/hvac-spec.md` — updated Comfort mode semantics, added Seasonal switching section, updated Comfort Heat table notes
- `tests/ambient/__init__.py` — new empty test package init
- `tests/ambient/test_client.py` — new: 18 unit tests for all public functions
- `tests/test_comfort_switch.py` — new: 12 unit tests for `_apply_comfort_mode` + `cmd_comfort_switch`

## Change Log

- 2026-03-17: Story created from superpowers plan + adversarial review findings applied
- 2026-03-17: Party mode review — added `is_temp_plausible` + `is_data_fresh` guards, dropped bare `Exception` catch, changed return type of `get_outdoor_temp_from_stations` to include mac+age, `cmd_weather` now shows reading age and source MAC, AC 3 now requires real station population, Task 8 clarified (schedule tables already correct from session)
- 2026-03-17: Implementation complete — 43 tests passing, all tasks checked except live network verification steps (5.5, 6.4, 7.9)
- 2026-03-17: Code review follow-ups resolved — hvac-spec.md schedule tables updated to Comfort Heat; `get_data_age_minutes` tests added; 46 tests passing
- 2026-03-17: Live verification complete — station MACs stored in 1Password (picklehome/Ambient Weather Stations/station_macs), injected via AMBIENT_STATION_MACS env var; weather.yaml stays clean (stations: []); `get_configured_macs` updated to prefer env var over yaml; 48 tests passing
