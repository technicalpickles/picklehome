# Climate Directory Restructure + Status Command

**Date:** 2026-03-16
**Status:** Planned

## Goal

Restructure the existing `ecobee/` automation into a `climate/` directory with better separation of concerns, consolidate thermostat configuration into a single registry, and add a `status` command for situational awareness and debugging.

## Context

The existing `ecobee/` directory is entirely write/push focused (sync schedules, sync comfort setpoints, validate). This work adds read/observability capability and reorganizes the code for long-term growth.

The Ecobee API already returns all needed data in a single `get_thermostats()` call — runtime temperature, humidity, equipment status, active holds, weather, and air quality.

## Directory Structure

```
climate/
  ecobee/             ← Python package
    __init__.py
    auth.py
    schedule.py
    comforts.py
    status.py         ← new
  config/
    thermostats.yaml  ← new: canonical thermostat registry
    schedule.yaml     ← moved, thermostat_id removed (resolved via thermostats.yaml)
    comforts.yaml     ← moved, thermostat_id removed (resolved via thermostats.yaml)
  spec/
    hvac-spec.md      ← moved
  sync.py             ← CLI entrypoint, all subcommands
```

`network/` and other domains remain self-contained. No shared root package until duplication actually warrants it.

## Thermostat Registry

`climate/config/thermostats.yaml` becomes the single source of truth for thermostat IDs:

```yaml
thermostats:
  downstairs:
    thermostat_id: "xxx"
    managed: true
  upstairs:
    thermostat_id: "xxx"
    managed: true
  cottage:
    thermostat_id: "xxx"
    managed: false   # separate property, excluded from all home automation
```

`managed: false` is explicit — Cottage is registered so the exclusion is clearly intentional.

`schedule.yaml` and `comforts.yaml` drop their `thermostat_id` fields and use the thermostat name as the key. ID lookup happens at runtime via `thermostats.yaml`.

## Status Command

```
$ just climate-status

Downstairs   70.4°F  58% humidity  idle        Comfort Cool  heat mode
Upstairs     70.1°F  62% humidity  idle        hold until 10:00am tomorrow
Outdoor      61.4°F  Rain · 13mph SW  (station NCQ)

Air quality — Downstairs: AQ 51  VOC 520ppm  CO2 508ppm
              Upstairs:   AQ 50  VOC 506ppm  CO2 502ppm
```

With `--json` flag: structured output suitable for piping to future tools.

Data surfaced per thermostat:
- `runtime.actualTemperature` + `actualHumidity`
- `equipmentStatus` (what's actively running; empty = idle)
- Active `events` (holds — type, setpoints, end time)
- `settings.hvacMode` (heat/cool/auto)
- `program.currentClimateRef` (which comfort mode is scheduled)
- Air quality: `actualAQScore`, `actualVOC`, `actualCO2` (filter `-5002` sentinel = N/A)

Weather from `weather.forecasts[0]` (current conditions from Ecobee's feed).

Only `managed: true` thermostats are shown.

## Implementation Order

1. Rename `ecobee/` → `climate/ecobee/`, update imports
2. Create `climate/config/` and `climate/spec/`, move files
3. Move `sync.py` → `climate/sync.py`, update default config paths
4. Create `climate/config/thermostats.yaml`
5. Refactor `schedule.yaml` + `comforts.yaml` — drop `thermostat_id`, resolve via registry
6. Update all `sync.py` commands to resolve IDs through `thermostats.yaml`
7. Write `climate/ecobee/status.py` — read logic
8. Add `status` subcommand to `climate/sync.py`
9. Update `Justfile` — rename tasks to `climate-*`, update paths
10. Delete `ecobee/explore_api.py` — one-off exploration, no longer needed

## Out of Scope

- Time-series logging / history (future)
- Feeding data to Home Assistant, InfluxDB, or dashboards (future)
- Shared root Python package (extract only when duplication warrants it)
- Extended runtime / interval data
