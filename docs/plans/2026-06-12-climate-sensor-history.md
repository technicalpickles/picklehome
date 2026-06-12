# Climate sensor history (`just climate-history`)

Point-in-time design doc. Date: 2026-06-12.

## Goal

Read historical room-sensor data (temperature + occupancy) from the Ecobee
`runtimeReport` API on demand. Motivated by the newly paired "Tracy Office"
SmartSensor (paired 2026-06-11 22:05 to the Downstairs thermostat), whose
history is available from the API but not surfaced by any existing command.

`climate-status` only reads the current snapshot. pyecobee wraps
`get_thermostats` / `get_remote_sensors` but not `runtimeReport`, so this calls
the endpoint directly with an authenticated HTTP GET.

Long-term logging of sensor data (beyond Ecobee's retention) is explicitly out
of scope here, but the parse layer is designed to be reusable by a future
logger.

## Command

```
just climate-history [--thermostat NAME] [--days N] [--raw] [--json]
```

- Default range: **today** (calendar day).
- `--days N`: widen the window back N calendar days (default 1 = today).
- `--thermostat NAME`: restrict to one managed thermostat (default: all managed).
- `--raw`: print every 5-minute interval row instead of summaries.
- `--json`: emit structured data (full granularity) for piping/plotting.
- All sensors on each thermostat are included. No per-sensor filter for now
  (only Tracy Office exists as a remote today); add `--sensor` later if needed.

## Output

### Single day (default, summarized hourly)

```
=== Downstairs ===
Tracy Office
  hour   avg   min   max   occupied
  09:00  72.4  71.9  73.1  20min
  10:00  73.0  72.6  73.4  35min
  ...
  range: 71.2-82.6F   occupied 105min
```

Temperature and occupancy per sensor. One sensor block per remote/built-in
sensor on the thermostat.

### Multi-day (`--days N`, N > 1)

Roll up to **per-day** rows (hourly rows would be too long):

```
=== Downstairs ===
Tracy Office
  date        avg   min   max   occupied
  2026-06-11  74.8  71.2  82.6  0min
  2026-06-12  72.9  71.5  74.0  105min
```

### `--raw` and `--json`

Always full 5-minute granularity regardless of `--days`. `--raw` prints a table;
`--json` prints structured per-sensor series.

## Architecture

Mirrors the `status.py` split: pure parse/format functions separated from I/O so
the logic is testable offline with a saved fixture.

New module `climate/ecobee/history.py`:

- `fetch_runtime_report(ecobee, thermostat_id, start, end)` -> raw report dict.
  **I/O.** Builds the `runtimeReport` request (`includeSensors=true`,
  `columns=zoneAveTemp` as a required-but-unused thermostat column), GETs
  `https://api.ecobee.com/1/runtimeReport` with the bearer token. Raises with
  diagnostic context on a non-200 response (per the don't-swallow-errors
  convention), never returns `None`.

- `parse_sensor_series(report)` -> list of
  `{name, sensor_type, temps: [(datetime, float)], occupancy: [(datetime, int)]}`.
  **Pure.** Joins the `rs2:*` / `ei:*` data columns back to named sensors using
  the report's `sensors` metadata, grouping a sensor's temperature and occupancy
  capabilities under one entry by name. Skips blank cells (sensor had no reading
  for that interval, e.g. before it was paired).

- `summarize_hourly(series)` -> per-hour avg/min/max temp + occupied-minutes.
  **Pure.** Used for the single-day view.

- `summarize_daily(series)` -> per-day avg/min/max temp + occupied-minutes.
  **Pure.** Used for the multi-day view.

- `format_history(summaries, granularity)` -> string. **Pure.**

`cmd_history(args)` in `sync.py` wires it: `make_ecobee()` -> resolve managed
thermostats (all, or `--thermostat`) -> compute date range from `--days` ->
`fetch_runtime_report` per thermostat -> `parse_sensor_series` ->
`summarize_hourly` or `summarize_daily` (or raw/json) -> print.

Registered as a `history` subparser in `sync.py` and a `climate-history *ARGS`
recipe in the `Justfile`, matching the existing `climate-*` pattern.

## Correctness notes

- **Display units, not deci-degrees.** `runtimeReport` returns temperatures
  already in display units (e.g. `75.6`), unlike `get_thermostats()` which
  returns deci-degrees requiring `decode_temp()`. The history path must NOT
  reuse `decode_temp`, or every reading is 10x too small. This is a code comment
  and an explicit test case.

- **Blank cells are normal.** A sensor reports no value for intervals before it
  was paired (and occasionally for dropped readings). Parsing skips blanks
  rather than treating them as zero.

- **Sensor column mapping is per-thermostat.** Column ids like `rs2:100:1`
  (temperature) and `rs2:100:2` (occupancy) are not stable across thermostats;
  always resolve them through the report's `sensors` metadata, never hardcode.

## Testing

`tests/climate/ecobee/test_history.py`, offline, using a saved `runtimeReport`
JSON fixture (per the project's mock-at-the-client-boundary convention):

- `parse_sensor_series`: column-to-sensor join, temperature + occupancy grouped
  under one named sensor, blank cells skipped.
- Display-units case: a `75.6` cell parses to `75.6`, not `7.56`.
- `summarize_hourly`: correct avg/min/max and occupied-minutes per hour.
- `summarize_daily`: correct rollup across days.
- `format_history`: stable rendering for single-day and multi-day.

## Sandbox

The data fetch is read-only and `api.ecobee.com` is allowlisted, so it works
in-sandbox while the token is valid. If the access token has expired, pyecobee
auto-refreshes and writes the new token to
`~/.local/state/picklehome/ecobee-tokens.json`, which the sandbox blocks
(same behavior as `climate-status`). In that case run with the sandbox disabled
once to let the refresh persist.

## Out of scope

- Long-term logging of sensor readings to our own store (beyond Ecobee's
  retention). The `parse_sensor_series` seam is the intended reuse point when we
  build it.
- `--sensor` filtering.
- Plotting/visualization (covered by `--json` feeding an external tool).
