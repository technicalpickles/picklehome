# Climate Sensor History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `just climate-history`, an on-demand command that reads room-sensor temperature and occupancy history from the Ecobee `runtimeReport` API.

**Architecture:** New `climate/ecobee/history.py` holds pure parse/summarize/format functions plus one I/O function (`fetch_runtime_report`). A `cmd_history` in `climate/sync.py` wires them: fetch the report per managed thermostat, parse the sensor columns into per-sensor series, summarize hourly (single day) or daily (multi-day), and print. Mirrors the existing `status.py` split (pure logic separate from I/O) so the logic is testable offline.

**Tech Stack:** Python 3.12, `requests`, `pyecobee` (for auth/token only), `pytest` + `unittest.mock`, `uv`, `just`.

**Design doc:** `docs/plans/2026-06-12-climate-sensor-history.md`

---

## Background the engineer needs

The Ecobee `runtimeReport` endpoint (`GET https://api.ecobee.com/1/runtimeReport`) returns 5-minute interval history. With `includeSensors=true` the response has a `sensorList`, one entry per thermostat, shaped like:

```python
{
  "thermostatIdentifier": "532572869586",
  "sensors": [
    {"sensorId": "rs2:100:1", "sensorName": "Tracy Office", "sensorType": "temperature", "sensorUsage": "indoor"},
    {"sensorId": "rs2:100:2", "sensorName": "Tracy Office", "sensorType": "occupancy",  "sensorUsage": "monitor"},
    {"sensorId": "ei:0:1",    "sensorName": "Thermostat Temperature", "sensorType": "temperature", "sensorUsage": "indoor"},
    {"sensorId": "ei:0:3",    "sensorName": "Thermostat Motion",      "sensorType": "occupancy",  "sensorUsage": "indoor"},
    {"sensorId": "ei:0:5",    "sensorName": "Thermostat AirQuality",  "sensorType": "airQuality", "sensorUsage": "monitor"},
    # ...more monitor-only sensors (airPressure, VOCppm, co2PPM, humidity)...
  ],
  "columns": ["date", "time", "rs2:100:1", "rs2:100:2", "ei:0:1", "ei:0:3", "ei:0:5", ...],
  "data": [
    "2026-06-11,22:00:00,,,73.2,1,49",      # Tracy columns blank: sensor not paired yet
    "2026-06-11,22:05:00,75.6,0,73.3,1,88", # Tracy's first reading
    "2026-06-12,09:45:00,74.9,1,71.5,0,64", # occupied
    # ...
  ],
}
```

**Critical facts that drive the parser:**

1. **Group sensors by sensorId prefix, not by name.** A `sensorId` is `<code>:<instance>:<capabilityIndex>`. `rs2:100:1` and `rs2:100:2` are the temperature and occupancy capabilities of one physical remote (Tracy Office). `ei:0:1` (temperature) and `ei:0:3` (occupancy/motion) are the thermostat's own interface — note these have *different* `sensorName`s ("Thermostat Temperature" vs "Thermostat Motion"), so grouping by name would split one physical unit. The prefix is `sensorId.rsplit(":", 1)[0]`.

2. **Temperatures are already in display units.** A cell reads `"75.6"` and means 75.6°F. Do NOT apply `decode_temp()` (that is for `get_thermostats()`'s tenths-of-a-degree ints). Applying it would make every reading 10x too small. This is an explicit test case.

3. **Blank cells are normal.** Before a sensor was paired (or on a dropped reading) its cell is `""`. Skip blanks per-column; do not treat them as 0.

4. **Each row in `data` is a comma-joined string**, not a list. Split on `,`. The first two fields are always `date` and `time`.

5. We only care about the `temperature` and `occupancy` capabilities within each group. Ignore `airQuality`, `vocPPM`, `co2PPM`, `airPressure`, `humidity`.

## File Structure

- **Create** `climate/ecobee/history.py` — all history logic:
  - `INTERVAL_MINUTES = 5` constant
  - `parse_sensor_series(report: dict) -> list[dict]` (pure)
  - `summarize_hourly(series: dict) -> dict` (pure)
  - `summarize_daily(series: dict) -> dict` (pure)
  - `format_history(thermostat_name: str, summaries: list[dict], granularity: str) -> str` (pure)
  - `format_raw(thermostat_name: str, series_list: list[dict]) -> str` (pure)
  - `fetch_runtime_report(access_token: str, thermostat_id: str, start_date: str, end_date: str) -> dict` (I/O)
- **Create** `tests/climate/ecobee/test_history.py` — offline tests with an inline fixture (per the project's per-file-fixture, no-conftest convention).
- **Modify** `climate/sync.py` — add `cmd_history`, the `history` subparser, and its `set_defaults`.
- **Modify** `Justfile` — add the `climate-history` recipe.
- **Modify** `climate/README.md` — replace the "inspect sensors through the API directly until it does" note with the new command, and document the column-prefix/display-units findings.

## Data shapes (define once, used across tasks)

`parse_sensor_series` returns a list of per-sensor dicts, one per physical temperature sensor:

```python
{
    "name": "Tracy Office",          # display name (see Task 1 for the "Thermostat" rule)
    "temps": [(datetime(2026,6,11,22,5), 75.6), ...],   # blanks skipped
    "occupancy": [(datetime(2026,6,11,22,5), 0), ...],  # ints 0/1, blanks skipped
}
```

`summarize_hourly` / `summarize_daily` return:

```python
{
    "name": "Tracy Office",
    "buckets": [
        {"label": "09:00", "avg": 75.6, "min": 74.9, "max": 76.3, "occupied_min": 10},
        # daily uses label "2026-06-12"
    ],
    "overall": {"min": 71.2, "max": 82.6, "occupied_min": 105},
}
```

---

## Task 1: `parse_sensor_series`

**Files:**
- Create: `climate/ecobee/history.py`
- Create: `tests/climate/ecobee/test_history.py`

- [ ] **Step 1: Write the failing test**

Create `tests/climate/ecobee/test_history.py`:

```python
from datetime import datetime

from climate.ecobee.history import parse_sensor_series

# Trimmed real runtimeReport sensorList entry. Columns:
# date, time, rs2:100:1 (Tracy temp), rs2:100:2 (Tracy occ),
# ei:0:1 (thermostat temp), ei:0:3 (thermostat motion), ei:0:5 (AQ monitor)
REPORT = {
    "thermostatIdentifier": "532572869586",
    "sensors": [
        {"sensorId": "rs2:100:1", "sensorName": "Tracy Office", "sensorType": "temperature", "sensorUsage": "indoor"},
        {"sensorId": "rs2:100:2", "sensorName": "Tracy Office", "sensorType": "occupancy", "sensorUsage": "monitor"},
        {"sensorId": "ei:0:1", "sensorName": "Thermostat Temperature", "sensorType": "temperature", "sensorUsage": "indoor"},
        {"sensorId": "ei:0:3", "sensorName": "Thermostat Motion", "sensorType": "occupancy", "sensorUsage": "indoor"},
        {"sensorId": "ei:0:5", "sensorName": "Thermostat AirQuality", "sensorType": "airQuality", "sensorUsage": "monitor"},
    ],
    "columns": ["date", "time", "rs2:100:1", "rs2:100:2", "ei:0:1", "ei:0:3", "ei:0:5"],
    "data": [
        "2026-06-11,22:00:00,,,73.2,1,49",       # Tracy blank (pre-pairing)
        "2026-06-11,22:05:00,75.6,0,73.3,1,88",  # Tracy first reading
        "2026-06-12,09:45:00,74.9,1,71.5,0,64",  # occupied
        "2026-06-12,09:50:00,76.3,1,71.3,0,64",  # occupied
        "2026-06-12,10:30:00,72.4,0,71.8,0,60",  # not occupied
    ],
}


def _by_name(series_list):
    return {s["name"]: s for s in series_list}


def test_groups_remote_sensor_capabilities_by_id_prefix():
    series = _by_name(parse_sensor_series(REPORT))
    tracy = series["Tracy Office"]
    # blank 22:00 row skipped; 4 real temp readings
    assert tracy["temps"] == [
        (datetime(2026, 6, 11, 22, 5), 75.6),
        (datetime(2026, 6, 12, 9, 45), 74.9),
        (datetime(2026, 6, 12, 9, 50), 76.3),
        (datetime(2026, 6, 12, 10, 30), 72.4),
    ]
    assert tracy["occupancy"] == [
        (datetime(2026, 6, 11, 22, 5), 0),
        (datetime(2026, 6, 12, 9, 45), 1),
        (datetime(2026, 6, 12, 9, 50), 1),
        (datetime(2026, 6, 12, 10, 30), 0),
    ]


def test_thermostat_builtin_named_thermostat_and_joins_temp_with_motion():
    series = _by_name(parse_sensor_series(REPORT))
    # ei:0:* group: temp from ei:0:1, occupancy from ei:0:3, named "Thermostat"
    assert "Thermostat" in series
    thermo = series["Thermostat"]
    assert thermo["temps"][0] == (datetime(2026, 6, 11, 22, 0), 73.2)
    assert thermo["occupancy"][0] == (datetime(2026, 6, 11, 22, 0), 1)


def test_temps_are_display_units_not_decidegrees():
    # 75.6 must stay 75.6, never become 7.56 (no decode_temp)
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    assert tracy["temps"][0][1] == 75.6


def test_monitor_only_sensors_excluded():
    # AirQuality (ei:0:5) is not a temperature sensor and must not appear
    names = {s["name"] for s in parse_sensor_series(REPORT)}
    assert names == {"Tracy Office", "Thermostat"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/ecobee/test_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'climate.ecobee.history'`

- [ ] **Step 3: Write minimal implementation**

Create `climate/ecobee/history.py`:

```python
"""Read and summarize Ecobee runtimeReport sensor history.

The runtimeReport endpoint returns 5-minute interval data. Unlike
get_thermostats() (which returns temperatures as tenths-of-a-degree ints),
runtimeReport temperatures are already in display units (e.g. "75.6" == 75.6F),
so we must NOT apply decode_temp here.
"""

from datetime import datetime

INTERVAL_MINUTES = 5


def _sensor_group_prefix(sensor_id: str) -> str:
    # sensorId is "<code>:<instance>:<capabilityIndex>"; the prefix identifies
    # the physical sensor. rs2:100:1 and rs2:100:2 are one remote's temp and
    # occupancy; ei:0:1 and ei:0:3 are the thermostat's own temp and motion.
    return sensor_id.rsplit(":", 1)[0]


def parse_sensor_series(report: dict) -> list[dict]:
    """Turn a runtimeReport sensorList entry into per-sensor temp/occupancy series.

    Groups capabilities by sensorId prefix so a physical sensor's temperature
    and occupancy columns end up together, even when their sensorNames differ
    (the thermostat's built-in does this). Only emits groups that have a
    temperature capability. Blank cells are skipped.
    """
    columns = report["columns"]
    col_index = {col: i for i, col in enumerate(columns)}

    # Group the sensor metadata by physical-sensor prefix.
    groups: dict[str, dict] = {}
    for s in report["sensors"]:
        prefix = _sensor_group_prefix(s["sensorId"])
        g = groups.setdefault(prefix, {"temp_col": None, "occ_col": None, "temp_name": None})
        if s["sensorType"] == "temperature":
            g["temp_col"] = s["sensorId"]
            g["temp_name"] = s["sensorName"]
        elif s["sensorType"] == "occupancy":
            g["occ_col"] = s["sensorId"]

    rows = [row.split(",") for row in report["data"]]

    series_list = []
    for prefix, g in groups.items():
        if g["temp_col"] is None:
            continue  # monitor-only group (AQ, VOC, humidity, ...)
        # The thermostat's own interface (ei:*) reports temp as
        # "Thermostat Temperature"; show it simply as "Thermostat".
        name = "Thermostat" if prefix.startswith("ei:") else g["temp_name"]

        temps = []
        occupancy = []
        ti = col_index[g["temp_col"]]
        oi = col_index[g["occ_col"]] if g["occ_col"] else None
        for parts in rows:
            ts = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y-%m-%d %H:%M:%S")
            if parts[ti] != "":
                temps.append((ts, float(parts[ti])))
            if oi is not None and parts[oi] != "":
                occupancy.append((ts, int(parts[oi])))
        series_list.append({"name": name, "temps": temps, "occupancy": occupancy})

    return series_list
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/climate/ecobee/test_history.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add climate/ecobee/history.py tests/climate/ecobee/test_history.py
git commit -m "feat(climate): parse Ecobee runtimeReport sensor series"
```

---

## Task 2: `summarize_hourly`

**Files:**
- Modify: `climate/ecobee/history.py`
- Test: `tests/climate/ecobee/test_history.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/climate/ecobee/test_history.py`:

```python
from climate.ecobee.history import summarize_hourly


def test_summarize_hourly_buckets_by_hour_with_occupied_minutes():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    summary = summarize_hourly(tracy)
    assert summary["name"] == "Tracy Office"
    buckets = {b["label"]: b for b in summary["buckets"]}
    # 09:00 hour has 74.9 and 76.3, both occupied (2 intervals * 5 min)
    assert buckets["09:00"]["avg"] == 75.6
    assert buckets["09:00"]["min"] == 74.9
    assert buckets["09:00"]["max"] == 76.3
    assert buckets["09:00"]["occupied_min"] == 10
    # 10:00 hour: single 72.4 reading, not occupied
    assert buckets["10:00"]["occupied_min"] == 0
    # overall spans all readings
    assert summary["overall"]["min"] == 72.4
    assert summary["overall"]["max"] == 76.3
    assert summary["overall"]["occupied_min"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/ecobee/test_history.py::test_summarize_hourly_buckets_by_hour_with_occupied_minutes -v`
Expected: FAIL with `ImportError: cannot import name 'summarize_hourly'`

- [ ] **Step 3: Write minimal implementation**

Add to `climate/ecobee/history.py`:

```python
def _overall(temps: list, occupancy: list) -> dict:
    vals = [t for _, t in temps]
    return {
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
        "occupied_min": sum(INTERVAL_MINUTES for _, v in occupancy if v == 1),
    }


def _summarize(series: dict, key_fn, label_fn) -> dict:
    """Group a sensor's readings into buckets by key_fn(timestamp).

    Groups by explicit dict bucketing (one pass over temps, one over
    occupancy) rather than re-scanning with predicates, so there are no
    closure/shadowing pitfalls. key_fn maps a datetime to a bucket key;
    label_fn maps that key to its display label.
    """
    temps, occupancy = series["temps"], series["occupancy"]
    temp_groups: dict = {}
    occ_groups: dict = {}
    for ts, t in temps:
        temp_groups.setdefault(key_fn(ts), []).append(t)
    for ts, v in occupancy:
        occ_groups.setdefault(key_fn(ts), []).append(v)

    buckets = []
    for k in sorted(temp_groups):
        vals = temp_groups[k]
        occ = occ_groups.get(k, [])
        buckets.append(
            {
                "label": label_fn(k),
                "avg": round(sum(vals) / len(vals), 1),
                "min": min(vals),
                "max": max(vals),
                "occupied_min": sum(INTERVAL_MINUTES for v in occ if v == 1),
            }
        )
    return {"name": series["name"], "buckets": buckets, "overall": _overall(temps, occupancy)}


def summarize_hourly(series: dict) -> dict:
    return _summarize(
        series,
        key_fn=lambda ts: (ts.date(), ts.hour),
        label_fn=lambda k: f"{k[1]:02d}:00",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/climate/ecobee/test_history.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add climate/ecobee/history.py tests/climate/ecobee/test_history.py
git commit -m "feat(climate): hourly sensor history summaries"
```

---

## Task 3: `summarize_daily`

**Files:**
- Modify: `climate/ecobee/history.py`
- Test: `tests/climate/ecobee/test_history.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/climate/ecobee/test_history.py`:

```python
from climate.ecobee.history import summarize_daily


def test_summarize_daily_buckets_by_date():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    summary = summarize_daily(tracy)
    buckets = {b["label"]: b for b in summary["buckets"]}
    # 2026-06-11: only the 75.6 reading, not occupied
    assert buckets["2026-06-11"]["min"] == 75.6
    assert buckets["2026-06-11"]["max"] == 75.6
    assert buckets["2026-06-11"]["occupied_min"] == 0
    # 2026-06-12: 74.9, 76.3, 72.4; two occupied intervals
    assert buckets["2026-06-12"]["min"] == 72.4
    assert buckets["2026-06-12"]["max"] == 76.3
    assert buckets["2026-06-12"]["occupied_min"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/ecobee/test_history.py::test_summarize_daily_buckets_by_date -v`
Expected: FAIL with `ImportError: cannot import name 'summarize_daily'`

- [ ] **Step 3: Write minimal implementation**

Add to `climate/ecobee/history.py`:

```python
def summarize_daily(series: dict) -> dict:
    return _summarize(
        series,
        key_fn=lambda ts: ts.date(),
        label_fn=lambda k: k.isoformat(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/climate/ecobee/test_history.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add climate/ecobee/history.py tests/climate/ecobee/test_history.py
git commit -m "feat(climate): daily sensor history summaries"
```

---

## Task 4: `format_history` and `format_raw`

**Files:**
- Modify: `climate/ecobee/history.py`
- Test: `tests/climate/ecobee/test_history.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/climate/ecobee/test_history.py`:

```python
from climate.ecobee.history import format_history, format_raw


def test_format_history_single_day_has_hour_header_and_range():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    out = format_history("Downstairs", [summarize_hourly(tracy)], "hourly")
    assert "=== Downstairs ===" in out
    assert "Tracy Office" in out
    assert "hour" in out
    assert "09:00" in out
    # range line uses overall min-max and total occupied
    assert "72.4" in out and "76.3" in out
    assert "10min" in out


def test_format_history_multi_day_has_date_header():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    out = format_history("Downstairs", [summarize_daily(tracy)], "daily")
    assert "date" in out
    assert "2026-06-12" in out


def test_format_raw_lists_intervals():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    out = format_raw("Downstairs", [tracy])
    assert "2026-06-11 22:05:00" in out
    assert "75.6" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/ecobee/test_history.py -k "format" -v`
Expected: FAIL with `ImportError: cannot import name 'format_history'`

- [ ] **Step 3: Write minimal implementation**

Add to `climate/ecobee/history.py`:

```python
def _fmt_temp(v) -> str:
    return f"{v:.1f}" if v is not None else "-"


def format_history(thermostat_name: str, summaries: list[dict], granularity: str) -> str:
    label_header = "hour" if granularity == "hourly" else "date"
    col_width = 5 if granularity == "hourly" else 10
    lines = [f"=== {thermostat_name} ==="]
    for s in summaries:
        lines.append(s["name"])
        lines.append(f"  {label_header:<{col_width}}  avg   min   max   occupied")
        for b in s["buckets"]:
            lines.append(
                f"  {b['label']:<{col_width}}  "
                f"{_fmt_temp(b['avg']):<5} {_fmt_temp(b['min']):<5} {_fmt_temp(b['max']):<5} "
                f"{b['occupied_min']}min"
            )
        o = s["overall"]
        lines.append(
            f"  range: {_fmt_temp(o['min'])}-{_fmt_temp(o['max'])}F   "
            f"occupied {o['occupied_min']}min"
        )
        lines.append("")
    return "\n".join(lines).rstrip()


def format_raw(thermostat_name: str, series_list: list[dict]) -> str:
    lines = [f"=== {thermostat_name} ==="]
    for s in series_list:
        lines.append(s["name"])
        occ_by_ts = dict(s["occupancy"])
        lines.append("  timestamp            temp   occ")
        for ts, temp in s["temps"]:
            occ = occ_by_ts.get(ts, "-")
            lines.append(f"  {ts.isoformat(sep=' '):<20} {temp:<6} {occ}")
        lines.append("")
    return "\n".join(lines).rstrip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/climate/ecobee/test_history.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add climate/ecobee/history.py tests/climate/ecobee/test_history.py
git commit -m "feat(climate): format sensor history output (summary + raw)"
```

---

## Task 5: `fetch_runtime_report` (I/O)

**Files:**
- Modify: `climate/ecobee/history.py`
- Test: `tests/climate/ecobee/test_history.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/climate/ecobee/test_history.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from climate.ecobee.history import fetch_runtime_report


def test_fetch_runtime_report_builds_request_and_returns_sensorlist_entry():
    fake = {
        "status": {"code": 0, "message": ""},
        "sensorList": [{"thermostatIdentifier": "532572869586", "sensors": [], "columns": [], "data": []}],
    }
    resp = MagicMock(status_code=200)
    resp.json.return_value = fake
    with patch("climate.ecobee.history.requests.get", return_value=resp) as mock_get:
        result = fetch_runtime_report("TOK", "532572869586", "2026-06-11", "2026-06-12")
    assert result == fake["sensorList"][0]
    # request was built correctly
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer TOK"
    body = json.loads(kwargs["params"]["body"])
    assert body["selection"]["selectionMatch"] == "532572869586"
    assert body["startDate"] == "2026-06-11"
    assert body["endDate"] == "2026-06-12"
    assert body["includeSensors"] is True


def test_fetch_runtime_report_raises_on_http_error():
    resp = MagicMock(status_code=500, text="Internal Server Error")
    with patch("climate.ecobee.history.requests.get", return_value=resp):
        with pytest.raises(RuntimeError, match="runtimeReport"):
            fetch_runtime_report("TOK", "532572869586", "2026-06-11", "2026-06-12")


def test_fetch_runtime_report_raises_on_api_error_code():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"status": {"code": 4, "message": "bad"}, "sensorList": []}
    with patch("climate.ecobee.history.requests.get", return_value=resp):
        with pytest.raises(RuntimeError, match="bad"):
            fetch_runtime_report("TOK", "532572869586", "2026-06-11", "2026-06-12")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/ecobee/test_history.py -k "fetch" -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_runtime_report'`

- [ ] **Step 3: Write minimal implementation**

Add to the top of `climate/ecobee/history.py` (with the other imports):

```python
import requests
```

Add the function:

```python
RUNTIME_REPORT_URL = "https://api.ecobee.com/1/runtimeReport"


def fetch_runtime_report(
    access_token: str, thermostat_id: str, start_date: str, end_date: str
) -> dict:
    """Fetch a runtimeReport sensorList entry for one thermostat.

    Dates are "YYYY-MM-DD", inclusive. Raises RuntimeError with diagnostic
    context on transport or API errors rather than returning None, so callers
    can distinguish a real failure from empty data (per the repo's
    don't-swallow-errors convention).
    """
    body = {
        "startDate": start_date,
        "endDate": end_date,
        # columns is required by the API even though we read sensor data, not
        # thermostat columns; zoneAveTemp is the cheapest valid choice.
        "columns": "zoneAveTemp",
        "selection": {"selectionType": "thermostats", "selectionMatch": thermostat_id},
        "includeSensors": True,
    }
    resp = requests.get(
        RUNTIME_REPORT_URL,
        params={"format": "json", "body": json.dumps(body)},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"runtimeReport request failed ({resp.status_code}) for "
            f"thermostat {thermostat_id}: {resp.text[:200]}"
        )
    payload = resp.json()
    status = payload.get("status", {})
    if status.get("code", 0) != 0:
        raise RuntimeError(
            f"runtimeReport API error for thermostat {thermostat_id}: "
            f"{status.get('message', 'unknown')}"
        )
    sensor_list = payload.get("sensorList") or []
    if not sensor_list:
        raise RuntimeError(
            f"runtimeReport returned no sensor data for thermostat {thermostat_id}"
        )
    return sensor_list[0]
```

Also add `import json` at the top if not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/climate/ecobee/test_history.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add climate/ecobee/history.py tests/climate/ecobee/test_history.py
git commit -m "feat(climate): fetch Ecobee runtimeReport sensor data"
```

---

## Task 6: Wire `cmd_history`, argparse, Justfile, README

**Files:**
- Modify: `climate/sync.py` (imports near line 11; add `cmd_history`; add subparser near the other `subparsers.add_parser(...)` calls ~line 727; add `set_defaults` ~line 815)
- Modify: `Justfile` (after the `climate-status` recipe, ~line 14)
- Modify: `climate/README.md`

- [ ] **Step 1: Add the import**

In `climate/sync.py`, the existing import line is:

```python
from climate.ecobee import auth, comforts, schedule, status
```

Change it to:

```python
from climate.ecobee import auth, comforts, history, schedule, status
```

Also add at the top with the stdlib imports:

```python
from datetime import date, timedelta
```

- [ ] **Step 2: Add `cmd_history`**

Add this function next to `cmd_status` in `climate/sync.py`:

```python
def cmd_history(args) -> None:
    ecobee = auth.make_ecobee()

    registry = load_thermostats(args.thermostats)
    managed = get_managed_thermostats(registry)
    if args.thermostat:
        managed = [(n, tid) for n, tid in managed if n == args.thermostat]
        if not managed:
            print(f"No managed thermostat named '{args.thermostat}'.")
            sys.exit(1)

    # A valid access token is needed for the report GET; get_thermostats()
    # triggers pyecobee's refresh-if-expired, same as cmd_status.
    if not ecobee.get_thermostats():
        print("Failed to authenticate with Ecobee.")
        sys.exit(1)
    token = ecobee.access_token

    end = date.today()
    start = end - timedelta(days=args.days - 1)

    if args.raw or args.json:
        granularity = "raw"
    elif args.days > 1:
        granularity = "daily"
    else:
        granularity = "hourly"

    json_out = []
    blocks = []
    for name, thermostat_id in managed:
        report = history.fetch_runtime_report(
            token, thermostat_id, start.isoformat(), end.isoformat()
        )
        series_list = history.parse_sensor_series(report)

        if args.json:
            json_out.append({"thermostat": name, "sensors": series_list})
        elif args.raw:
            blocks.append(history.format_raw(name, series_list))
        elif granularity == "daily":
            summaries = [history.summarize_daily(s) for s in series_list]
            blocks.append(history.format_history(name, summaries, "daily"))
        else:
            summaries = [history.summarize_hourly(s) for s in series_list]
            blocks.append(history.format_history(name, summaries, "hourly"))

    if args.json:
        import json as _json
        print(_json.dumps(json_out, indent=2, default=str))
    else:
        print("\n\n".join(blocks))
```

- [ ] **Step 3: Add the subparser**

Next to the `status_parser` block in `build_parser`/`main` in `climate/sync.py`, add:

```python
history_parser = subparsers.add_parser(
    "history", help="Show room-sensor temperature and occupancy history"
)
history_parser.add_argument(
    "--thermostat",
    metavar="NAME",
    default=None,
    help="Only this managed thermostat (default: all)",
)
history_parser.add_argument(
    "--days",
    type=int,
    default=1,
    metavar="N",
    help="Number of calendar days back to include, ending today (default: 1)",
)
history_parser.add_argument(
    "--raw",
    action="store_true",
    help="Print every 5-minute interval instead of summaries",
)
history_parser.add_argument(
    "--json",
    action="store_true",
    help="Output structured JSON (full granularity)",
)
history_parser.add_argument(
    "--thermostats",
    type=Path,
    default=DEFAULT_THERMOSTATS_PATH,
    metavar="PATH",
    help="Path to thermostats YAML (default: climate/config/thermostats.yaml)",
)
```

And in the `set_defaults` block add:

```python
subparsers.choices["history"].set_defaults(func=cmd_history)
```

- [ ] **Step 4: Add the Justfile recipe**

In `Justfile`, after the `climate-status` recipe (lines 11-14), add:

```makefile
# Show room-sensor temperature and occupancy history
climate-history *ARGS:
    uv run python -m climate.sync history {{ARGS}}
```

- [ ] **Step 5: Verify wiring (commands resolve, help works)**

Run: `just --list | grep climate-history`
Expected: the `climate-history` recipe is listed.

Run: `uv run python -m climate.sync history --help`
Expected: help text showing `--thermostat`, `--days`, `--raw`, `--json`.

Run: `uv run pytest tests/climate/ecobee/test_history.py -v`
Expected: PASS (12 tests, unchanged).

- [ ] **Step 6: Update README**

In `climate/README.md`, find the "Room sensors" line in the Ecobee API notes that currently ends with:

> `climate-status` requests sensor data (`includeSensors`) but the code does not parse it yet; inspect sensors through the API directly until it does.

Replace that final sentence with:

> Historical sensor data (temperature + occupancy, 5-minute intervals) is available via `just climate-history` (`--days N`, `--raw`, `--json`), which reads the Ecobee `runtimeReport` endpoint. `climate-status` still shows only the current snapshot.

Then add to the Ecobee API notes (near the other findings) these two:

```markdown
- **runtimeReport sensor columns:** Sensor capability columns use ids like `rs2:100:1` (a remote sensor's temperature) and `rs2:100:2` (its occupancy). The id is `<code>:<instance>:<capabilityIndex>`; group by the prefix (everything before the last `:`) to join a physical sensor's temperature and occupancy, since the thermostat's built-in reports them under different names ("Thermostat Temperature" vs "Thermostat Motion").
- **runtimeReport temperatures are in display units:** A cell reads `75.6` and means 75.6°F, unlike `get_thermostats()` which returns tenths-of-a-degree ints. Do not apply `decode_temp` to runtimeReport values.
```

- [ ] **Step 7: Commit**

```bash
git add climate/sync.py Justfile climate/README.md
git commit -m "feat(climate): add just climate-history command"
```

---

## Task 7: End-to-end verification against the live API

This task confirms the command works against real data. It hits the Ecobee API, so it must run with the sandbox disabled if the access token has expired (the token refresh writes to `~/.local/state/picklehome/ecobee-tokens.json`, which the sandbox blocks).

- [ ] **Step 1: Run today's history for the Downstairs thermostat**

Run: `just climate-history --thermostat Downstairs`
Expected: a `=== Downstairs ===` block with a `Tracy Office` section (hourly rows) and a `Thermostat` section. Temperatures in the low 70s°F. If it errors with `PermissionError` / `Operation not permitted` on the token file, re-run with the sandbox disabled.

- [ ] **Step 2: Run a multi-day report**

Run: `just climate-history --thermostat Downstairs --days 3`
Expected: per-day rows (labels like `2026-06-11`, `2026-06-12`), not hourly. The 2026-06-11 row for Tracy Office should show a high near 82.6°F (the post-pairing spike).

- [ ] **Step 3: Spot-check raw and json**

Run: `just climate-history --thermostat Downstairs --raw`
Expected: 5-minute interval rows with timestamps, temp, occ.

Run: `just climate-history --thermostat Downstairs --json`
Expected: valid JSON; pipe through `| python -m json.tool` to confirm it parses.

- [ ] **Step 4: Run the full test suite**

Run: `uv run pytest tests/climate/ -v`
Expected: all climate tests pass, including the 12 new history tests.

- [ ] **Step 5: Record any follow-ups**

If anything surfaced that is out of scope (e.g. long-term logging, `--sensor` filter), capture it:

```bash
task add project:picklehome.climate.ecobee "<follow-up>"
```

---

## Self-Review Notes

- **Spec coverage:** command shape + flags (Task 6), today default / `--days` calendar-back (Task 6 Step 2), all-sensors no-filter (Task 1 groups every temp sensor), single-day hourly / multi-day daily / raw+json full granularity (Task 6 Step 2 granularity logic + Tasks 2-4), display-units-not-deci-degrees (Task 1 test + README), blank-cell skipping (Task 1), per-thermostat column mapping via prefix (Task 1), don't-swallow-errors fetch (Task 5), offline tests with inline fixture (Tasks 1-5), README update (Task 6 Step 6), sandbox note (Task 7). All covered.
- **Type consistency:** `parse_sensor_series` returns `{name, temps, occupancy}`; `summarize_hourly`/`summarize_daily` return `{name, buckets, overall}`; `format_history(name, summaries, granularity)` and `format_raw(name, series_list)` and `fetch_runtime_report(access_token, thermostat_id, start_date, end_date)` signatures are used identically in Task 6's `cmd_history`.
- **No placeholders:** every code step shows complete code.
