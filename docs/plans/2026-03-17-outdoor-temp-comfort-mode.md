# Outdoor Temperature Comfort Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pull outdoor temperature from nearby public Ambient Weather Network stations and use it to automatically select between Comfort Cool (`smart1`) and Comfort Heat (`smart2`) in the Ecobee schedule.

**Architecture:** A new `climate/ambient/` module wraps `aioambient.OpenAPI` (no API key needed, public data) to discover nearby outdoor stations and read their current `tempf`. A `weather.yaml` config stores chosen station MAC addresses and heat/cool thresholds. New CLI subcommands in `climate/sync.py` expose discovery, current-temp display, and comfort-mode switching (edit `schedule.yaml` → sync to Ecobee).

**Tech Stack:** `aioambient==2024.08.0`, `asyncio.run()` to bridge async→sync, `pyyaml`, existing `climate.sync` CLI pattern, `just` task runner.

---

## Task 1: Add dependency and lat/lon env vars

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.template`

**Step 1: Add aioambient to project deps**

In `pyproject.toml`, add to `dependencies`:
```
"aioambient==2024.08.0",
```

**Step 2: Add lat/lon to env template**

In `.env.template`, add after `HOME_ZIP_CODE`:
```
HOME_LAT={{ op://picklehome/Home/latitude }}
HOME_LON={{ op://picklehome/Home/longitude }}
```

**Step 3: Add to 1Password**

In 1Password, open the `picklehome` vault → `Home` item. Add two fields:
- `latitude`: your home latitude (decimal degrees, e.g. `33.7490`)
- `longitude`: your home longitude (decimal degrees, e.g. `-84.3880`)

Use Google Maps: right-click your address → copy the coordinates shown.

**Step 4: Regenerate .env and install deps**

```bash
just dotenv
uv sync
```

Expected: `.env` now contains `HOME_LAT` and `HOME_LON`. `uv sync` installs `aioambient`.

**Step 5: Verify**

```bash
uv run python -c "import aioambient; print('ok')"
```

Expected: `ok`

**Step 6: Commit**

```bash
git add pyproject.toml uv.lock .env.template
git commit -m "feat: add aioambient dep and lat/lon env vars"
```

---

## Task 2: Create ambient weather client module

**Files:**
- Create: `climate/ambient/__init__.py`
- Create: `climate/ambient/client.py`

**Step 1: Create `climate/ambient/__init__.py`** (empty)

```python
```

**Step 2: Write failing test**

Create `tests/ambient/test_client.py`:

```python
from unittest.mock import AsyncMock, patch
from climate.ambient.client import get_outdoor_temp_sync

def test_get_outdoor_temp_sync_returns_float():
    mock_data = {"lastData": {"tempf": 52.3}}
    with patch("climate.ambient.client.OpenAPI") as MockAPI:
        instance = MockAPI.return_value
        instance.get_device_details = AsyncMock(return_value=mock_data)
        result = get_outdoor_temp_sync("AA:BB:CC:DD:EE:FF")
    assert result == 52.3

def test_get_outdoor_temp_sync_returns_none_when_missing():
    mock_data = {"lastData": {}}
    with patch("climate.ambient.client.OpenAPI") as MockAPI:
        instance = MockAPI.return_value
        instance.get_device_details = AsyncMock(return_value=mock_data)
        result = get_outdoor_temp_sync("AA:BB:CC:DD:EE:FF")
    assert result is None
```

**Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/ambient/test_client.py -v
```

Expected: `ImportError` or `ModuleNotFoundError`, `client` doesn't exist yet.

**Step 4: Implement `climate/ambient/client.py`**

```python
import asyncio
from typing import Any

from aioambient import OpenAPI


async def _get_device_details(mac: str) -> dict[str, Any]:
    api = OpenAPI()
    return await api.get_device_details(mac)


async def _get_devices_by_location(lat: float, lon: float, radius_miles: float) -> list[dict[str, Any]]:
    api = OpenAPI()
    return await api.get_devices_by_location(lat, lon, radius=radius_miles)


def get_outdoor_temp_sync(mac: str) -> float | None:
    """Return outdoor temp in °F from a single station, or None if unavailable."""
    data = asyncio.run(_get_device_details(mac))
    return data.get("lastData", {}).get("tempf")


def get_outdoor_temp_from_stations(macs: list[str]) -> float | None:
    """Try each station MAC in order; return the first successful temp reading."""
    for mac in macs:
        temp = get_outdoor_temp_sync(mac)
        if temp is not None:
            return temp
    return None


def discover_stations_sync(lat: float, lon: float, radius_miles: float = 1.0) -> list[dict[str, Any]]:
    """Return list of nearby outdoor station dicts with MAC, name, and current temp."""
    stations = asyncio.run(_get_devices_by_location(lat, lon, radius_miles))
    outdoor = [s for s in stations if not s.get("info", {}).get("indoor", False)]
    return outdoor
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/ambient/test_client.py -v
```

Expected: 2 passed.

**Step 6: Commit**

```bash
git add climate/ambient/ tests/ambient/
git commit -m "feat: add ambient weather client module"
```

---

## Task 3: Create weather.yaml config

**Files:**
- Create: `climate/config/weather.yaml`

**Step 1: Create `climate/config/weather.yaml`**

You'll fill in real MAC addresses after running `climate-weather-discover` (Task 4). For now create a placeholder:

```yaml
# climate/config/weather.yaml
# Outdoor temperature sources and comfort-mode thresholds.
# MACs are from the Ambient Weather Network (ambientweather.net).
# Run 'just climate-weather-discover' to find nearby stations.
# Run 'just climate-weather' to see current outdoor temp.

# Stations to try in order: first responding station wins.
stations: []
  # - mac: "AA:BB:CC:DD:EE:FF"
  #   name: "Neighbor's WS-2902"

# Temperature thresholds (°F) for comfort mode selection.
# Below heat_threshold → use Comfort Heat (smart2)
# Above cool_threshold → use Comfort Cool (smart1)
# Between thresholds → no automatic change (hysteresis band)
thresholds:
  heat_below: 60
  cool_above: 65
```

**Step 2: Add a loader function**

In `climate/ambient/client.py`, add at the bottom:

```python
import sys
from pathlib import Path
import yaml

DEFAULT_WEATHER_PATH = Path(__file__).parent.parent / "config" / "weather.yaml"


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

**Step 3: Commit**

```bash
git add climate/config/weather.yaml climate/ambient/client.py
git commit -m "feat: add weather.yaml config and loader"
```

---

## Task 4: Add discover-stations CLI subcommand

**Files:**
- Modify: `climate/sync.py`
- Modify: `Justfile`

**Step 1: Add `cmd_weather_discover` to `climate/sync.py`**

After the existing `cmd_status` function, add:

```python
def cmd_weather_discover(args) -> None:
    import os
    from climate.ambient.client import discover_stations_sync

    lat = float(os.environ.get("HOME_LAT", "") or (print("HOME_LAT not set. Run 'just dotenv'.") or sys.exit(1)))
    lon = float(os.environ.get("HOME_LON", "") or (print("HOME_LON not set. Run 'just dotenv'.") or sys.exit(1)))

    print(f"Searching within {args.radius} mile(s) of ({lat:.4f}, {lon:.4f})...")
    stations = discover_stations_sync(lat, lon, radius_miles=args.radius)

    if not stations:
        print("No outdoor stations found nearby. Try increasing --radius.")
        sys.exit(1)

    print(f"\nFound {len(stations)} outdoor station(s):\n")
    for s in stations:
        mac = s.get("macAddress", "unknown")
        name = s.get("info", {}).get("name") or s.get("info", {}).get("coords", {}).get("location", "unnamed")
        temp = s.get("lastData", {}).get("tempf")
        temp_str = f"{temp}°F" if temp is not None else "no temp"
        print(f"  {mac}  {name}  ({temp_str})")

    print("\nAdd desired MACs to climate/config/weather.yaml under 'stations:'.")
```

**Step 2: Wire up in `main()`**

In the `main()` function, add a new subparser before `args = parser.parse_args()`:

```python
    discover_parser = subparsers.add_parser(
        "discover-stations", help="Find nearby Ambient Weather Network outdoor stations"
    )
    discover_parser.add_argument(
        "--radius",
        type=float,
        default=1.0,
        metavar="MILES",
        help="Search radius in miles (default: 1.0)",
    )
    subparsers.choices["discover-stations"].set_defaults(func=cmd_weather_discover)
```

**Step 3: Add `just` task to Justfile**

```just
# Discover nearby Ambient Weather Network stations
climate-weather-discover *ARGS:
    uv run python -m climate.sync discover-stations {{ARGS}}
```

**Step 4: Verify**

```bash
just --list | grep weather
just climate-weather-discover --radius 2
```

Expected: lists nearby stations with MACs and current temps.

**Step 5: Populate weather.yaml**

Using the output from `climate-weather-discover`, edit `climate/config/weather.yaml` and add the 1-3 closest outdoor stations under `stations:`.

**Step 6: Commit**

```bash
git add climate/sync.py Justfile climate/config/weather.yaml
git commit -m "feat: add discover-stations command and populate weather.yaml"
```

---

## Task 5: Add weather (current temp) CLI subcommand

**Files:**
- Modify: `climate/sync.py`
- Modify: `Justfile`

**Step 1: Add `cmd_weather` to `climate/sync.py`**

```python
def cmd_weather(args) -> None:
    from climate.ambient.client import load_weather_config, get_configured_macs, get_outdoor_temp_from_stations

    config = load_weather_config(args.weather)
    macs = get_configured_macs(config)

    if not macs:
        print("No stations configured. Run 'just climate-weather-discover' and add MACs to weather.yaml.")
        sys.exit(1)

    temp = get_outdoor_temp_from_stations(macs)
    if temp is None:
        print("Could not read outdoor temp from any configured station.")
        sys.exit(1)

    thresholds = config.get("thresholds", {})
    heat_below = thresholds.get("heat_below", 60)
    cool_above = thresholds.get("cool_above", 65)

    if temp < heat_below:
        mode = "heat  → Comfort Heat (smart2)"
    elif temp > cool_above:
        mode = "cool  → Comfort Cool (smart1)"
    else:
        mode = f"neutral  (between {heat_below}°F–{cool_above}°F, no change recommended)"

    print(f"Outdoor temp: {temp}°F")
    print(f"Comfort mode: {mode}")
```

**Step 2: Wire up in `main()`**

```python
    weather_parser = subparsers.add_parser(
        "weather", help="Show current outdoor temp and comfort mode recommendation"
    )
    weather_parser.add_argument(
        "--weather",
        type=Path,
        default=DEFAULT_WEATHER_PATH,
        metavar="PATH",
        help="Path to weather YAML (default: climate/config/weather.yaml)",
    )
    subparsers.choices["weather"].set_defaults(func=cmd_weather)
```

Also add to the top of `sync.py`:
```python
from climate.ambient.client import DEFAULT_WEATHER_PATH
```

**Step 3: Add `just` task**

```just
# Show current outdoor temp and comfort mode recommendation
climate-weather *ARGS:
    uv run python -m climate.sync weather {{ARGS}}
```

**Step 4: Verify**

```bash
just climate-weather
```

Expected output like:
```
Outdoor temp: 45.2°F
Comfort mode: heat  → Comfort Heat (smart2)
```

**Step 5: Commit**

```bash
git add climate/sync.py Justfile
git commit -m "feat: add weather command: outdoor temp and comfort mode recommendation"
```

---

## Task 6: Add comfort-switch CLI subcommand

This command rewrites `schedule.yaml` to swap all `smart1`↔`smart2` references for the desired mode, then syncs to Ecobee.

**Files:**
- Modify: `climate/sync.py`
- Modify: `Justfile`

**Step 1: Write failing test**

In `tests/test_comfort_switch.py`:

```python
from climate.sync import _apply_comfort_mode

SCHEDULE_HEAT = """
thermostats:
  downstairs:
    schedule:
      sunday:
        - time: "00:00"
          climate: sleep
        - time: "06:00"
          climate: smart2
"""

SCHEDULE_COOL = """
thermostats:
  downstairs:
    schedule:
      sunday:
        - time: "00:00"
          climate: sleep
        - time: "06:00"
          climate: smart1
"""

def test_apply_comfort_mode_heat_replaces_cool():
    result = _apply_comfort_mode(SCHEDULE_COOL.strip(), "heat")
    assert "smart2" in result
    assert "smart1" not in result
    assert "sleep" in result  # non-smart entries untouched

def test_apply_comfort_mode_cool_replaces_heat():
    result = _apply_comfort_mode(SCHEDULE_HEAT.strip(), "cool")
    assert "smart1" in result
    assert "smart2" not in result

def test_apply_comfort_mode_preserves_comments():
    text = "climate: smart1  # Comfort Cool\n"
    result = _apply_comfort_mode(text, "heat")
    assert "smart2" in result
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_comfort_switch.py -v
```

Expected: `ImportError`, `_apply_comfort_mode` not defined yet.

**Step 3: Implement `_apply_comfort_mode` in `climate/sync.py`**

Add near the top of `sync.py` (after imports):

```python
import re

def _apply_comfort_mode(schedule_text: str, mode: str) -> str:
    """Rewrite schedule text: swap smart1↔smart2 to match the desired comfort mode.

    mode='heat' → replace smart1 with smart2 (Comfort Heat)
    mode='cool' → replace smart2 with smart1 (Comfort Cool)
    """
    if mode == "heat":
        return re.sub(r'\bsmart1\b', 'smart2', schedule_text)
    elif mode == "cool":
        return re.sub(r'\bsmart2\b', 'smart1', schedule_text)
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use 'heat' or 'cool'.")
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_comfort_switch.py -v
```

Expected: 3 passed.

**Step 5: Add `cmd_comfort_switch` to `climate/sync.py`**

```python
def cmd_comfort_switch(args) -> None:
    from climate.ambient.client import load_weather_config, get_configured_macs, get_outdoor_temp_from_stations

    mode = args.mode

    if mode == "auto":
        config = load_weather_config(args.weather)
        macs = get_configured_macs(config)
        if not macs:
            print("No stations configured in weather.yaml.")
            sys.exit(1)
        temp = get_outdoor_temp_from_stations(macs)
        if temp is None:
            print("Could not read outdoor temp. Cannot auto-select comfort mode.")
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
            sys.exit(0)
        print(f"Outdoor temp: {temp}°F → switching to {mode}")

    schedule_path = args.schedule
    text = schedule_path.read_text()
    updated = _apply_comfort_mode(text, mode)

    if updated == text:
        print(f"Schedule already set to {mode} comfort. Nothing to do.")
        return

    if args.dry_run:
        print(f"[dry run] Would switch schedule to {mode} comfort:")
        # Show which lines changed
        for i, (old, new) in enumerate(zip(text.splitlines(), updated.splitlines()), 1):
            if old != new:
                print(f"  line {i}: {old.strip()!r} → {new.strip()!r}")
        return

    schedule_path.write_text(updated)
    print(f"schedule.yaml updated to {mode} comfort. Syncing to Ecobee...")

    # Reuse cmd_sync logic
    class SyncArgs:
        schedule = schedule_path
        thermostats = args.thermostats
        thermostat = None
        dry_run = False

    cmd_sync(SyncArgs())
```

**Step 6: Wire up in `main()`**

```python
    switch_parser = subparsers.add_parser(
        "comfort-switch",
        help="Switch schedule between Comfort Cool/Heat and sync to Ecobee",
    )
    switch_parser.add_argument(
        "mode",
        choices=["heat", "cool", "auto"],
        help="'heat', 'cool', or 'auto' (reads outdoor temp from weather.yaml stations)",
    )
    switch_parser.add_argument("--dry-run", action="store_true")
    switch_parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE_PATH)
    switch_parser.add_argument("--thermostats", type=Path, default=DEFAULT_THERMOSTATS_PATH)
    switch_parser.add_argument("--weather", type=Path, default=DEFAULT_WEATHER_PATH)
    subparsers.choices["comfort-switch"].set_defaults(func=cmd_comfort_switch)
```

**Step 7: Add `just` tasks**

```just
# Switch comfort mode (heat/cool/auto) and sync to Ecobee
climate-comfort-switch MODE *ARGS:
    uv run python -m climate.sync comfort-switch {{MODE}} {{ARGS}}

# Preview comfort-switch without pushing
climate-comfort-switch-dry MODE *ARGS:
    uv run python -m climate.sync comfort-switch {{MODE}} --dry-run {{ARGS}}
```

**Step 8: Verify**

```bash
just climate-comfort-switch-dry auto
just --list | grep comfort
```

Expected dry run output shows which lines would change, then `just --list` shows all 3 new tasks.

**Step 9: Commit**

```bash
git add climate/sync.py Justfile tests/test_comfort_switch.py
git commit -m "feat: add comfort-switch command with auto outdoor-temp detection"
```

---

## Task 7: Update hvac-spec.md

**Files:**
- Modify: `climate/spec/hvac-spec.md`

Update the Comfort mode semantics section to reflect that `Comfort Heat` is now actively used and the switching is driven by outdoor temp, and add a note about the thresholds. Also update the schedule tables to show `Comfort Heat` as the current active mode.

**Step 1: Edit `climate/spec/hvac-spec.md`**

In the Comfort mode semantics section, change:
```
- **Comfort Heat**: primary occupied mode when it's cold out. Target ~70°F by heating. Not currently in use (treating as warm season).
```
To:
```
- **Comfort Heat**: primary occupied mode when it's cold out. Target ~70°F by heating. Active when outdoor temp < 60°F.
- **Comfort Cool**: primary occupied mode when it's warm out. Target ~70°F by cooling. Active when outdoor temp > 65°F.
```

Update the schedule tables to note the active mode is determined by `just climate-comfort-switch auto` based on outdoor temp from Ambient Weather Network stations.

**Step 2: Commit**

```bash
git add climate/spec/hvac-spec.md
git commit -m "docs: update hvac-spec to reflect outdoor-temp-driven comfort switching"
```

---

## Execution notes

- `just climate-weather-discover` must be run before Task 4 Step 5 to get real MAC addresses.
- The `auto` mode uses hysteresis: temps between 60–65°F don't force a switch, avoiding thrash around the threshold.
- `aioambient` is async; we use `asyncio.run()` which is fine for CLI scripts (one call per run).
- Station data is polled live on each CLI invocation, no caching needed for a manual tool.
