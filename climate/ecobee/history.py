"""Read and summarize Ecobee runtimeReport sensor history.

The runtimeReport endpoint returns 5-minute interval data. Unlike
get_thermostats() (which returns temperatures as tenths-of-a-degree ints),
runtimeReport temperatures are already in display units (e.g. "75.6" == 75.6F),
so we must NOT apply decode_temp here.
"""

import json
import requests
from datetime import date, datetime, timedelta

INTERVAL_MINUTES = 5

# runtimeReport rejects ranges over 33 days ("Report is limited to 33 days per
# request"), so longer windows are fetched in chunks of this size.
MAX_REPORT_DAYS = 31

# Equipment/outdoor columns, in the order they are requested. Runtime columns
# are seconds the equipment ran within each 5-minute interval (0-300).
EQUIPMENT_COLUMNS = (
    "compCool1",
    "compCool2",
    "compHeat1",
    "compHeat2",
    "auxHeat1",
    "auxHeat2",
    "fan",
    "outdoorTemp",
)


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


def summarize_daily(series: dict) -> dict:
    return _summarize(
        series,
        key_fn=lambda ts: ts.date(),
        label_fn=lambda k: k.isoformat(),
    )


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
            lines.append(f"  {ts.isoformat(sep=' '):<20} {_fmt_temp(temp):<6} {occ}")
        lines.append("")
    return "\n".join(lines).rstrip()


RUNTIME_REPORT_URL = "https://api.ecobee.com/1/runtimeReport"


def fetch_runtime_payload(
    access_token: str,
    thermostat_id: str,
    start_date: str,
    end_date: str,
    columns: str = "zoneAveTemp",
) -> dict:
    """Fetch a whole runtimeReport payload (sensorList and reportList) for one thermostat.

    Dates are "YYYY-MM-DD", inclusive, and limited to 33 days per request.
    Raises RuntimeError with diagnostic context on transport or API errors
    rather than returning None, so callers can distinguish a real failure from
    empty data (per the repo's don't-swallow-errors convention).
    """
    body = {
        "startDate": start_date,
        "endDate": end_date,
        # columns is required by the API even when we only read sensor data;
        # zoneAveTemp is the cheapest valid choice.
        "columns": columns,
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
    return payload


def fetch_runtime_report(
    access_token: str, thermostat_id: str, start_date: str, end_date: str
) -> dict:
    """Fetch a runtimeReport sensorList entry for one thermostat."""
    payload = fetch_runtime_payload(access_token, thermostat_id, start_date, end_date)
    sensor_list = payload.get("sensorList") or []
    if not sensor_list:
        raise RuntimeError(
            f"runtimeReport returned no sensor data for thermostat {thermostat_id}"
        )
    return sensor_list[0]


def resolve_window(
    days: int | None, start: date | None, end: date | None, today: date
) -> tuple[date, date]:
    """Turn the CLI's --days / --start / --end into an inclusive (start, end)."""
    if days is not None and (start is not None or end is not None):
        raise ValueError("--days can't be combined with --start/--end")
    if start is None and end is not None:
        raise ValueError("--end needs --start")
    if start is None:
        n = 1 if days is None else days
        if n < 1:
            raise ValueError("--days must be at least 1")
        return today - timedelta(days=n - 1), today
    end = end or today
    if end < start:
        raise ValueError(f"--end {end} is before --start {start}")
    return start, end


def chunk_date_range(
    start: date, end: date, max_days: int = MAX_REPORT_DAYS
) -> list[tuple[date, date]]:
    """Split an inclusive [start, end] range into consecutive inclusive chunks."""
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def merge_series(per_chunk: list[list[dict]]) -> list[dict]:
    """Merge per-chunk parse_sensor_series() output into one series per sensor.

    Sensors are matched by name. Readings are de-duplicated by timestamp and
    sorted, so adjacent chunks can overlap safely. The API also answers a
    request that predates the thermostat's first data with one stub row for
    its earliest reading, which de-duplicates the same way.
    """
    merged: dict[str, dict] = {}
    for series_list in per_chunk:
        for s in series_list:
            m = merged.setdefault(s["name"], {"name": s["name"], "temps": {}, "occupancy": {}})
            m["temps"].update(dict(s["temps"]))
            m["occupancy"].update(dict(s["occupancy"]))
    return [
        {
            "name": m["name"],
            "temps": sorted(m["temps"].items()),
            "occupancy": sorted(m["occupancy"].items()),
        }
        for m in merged.values()
    ]


def parse_equipment_rows(payload: dict) -> list[dict]:
    """Turn a runtimeReport reportList entry into one dict per 5-minute interval.

    Each dict has ts (datetime), cool/heat/aux/fan (seconds run, 0-300), and
    outdoor (F, or None when blank). cool/heat/aux take the larger of the two
    stages, since stage 2 runs alongside stage 1.
    """
    report_list = payload.get("reportList") or []
    if not report_list:
        return []
    names = payload["columns"].split(",")
    idx = {name: i for i, name in enumerate(names)}

    def secs(parts, *cols):
        vals = [int(parts[idx[c]]) for c in cols if parts[idx[c]] != ""]
        return max(vals) if vals else 0

    rows = []
    for line in report_list[0]["rowList"]:
        f = line.split(",")
        parts = f[2:]  # after date and time
        outdoor = parts[idx["outdoorTemp"]]
        rows.append(
            {
                "ts": datetime.strptime(f"{f[0]} {f[1]}", "%Y-%m-%d %H:%M:%S"),
                "cool": secs(parts, "compCool1", "compCool2"),
                "heat": secs(parts, "compHeat1", "compHeat2"),
                "aux": secs(parts, "auxHeat1", "auxHeat2"),
                "fan": secs(parts, "fan"),
                "outdoor": float(outdoor) if outdoor != "" else None,
            }
        )
    return rows


def merge_equipment(per_chunk: list[list[dict]]) -> list[dict]:
    """Merge per-chunk equipment rows, de-duplicated by timestamp and sorted."""
    by_ts = {r["ts"]: r for rows in per_chunk for r in rows}
    return [by_ts[ts] for ts in sorted(by_ts)]


def fetch_range(
    access_token: str,
    thermostat_id: str,
    start: date,
    end: date,
    with_equipment: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Fetch sensor series (and optionally equipment rows) over any date range."""
    columns = ",".join(EQUIPMENT_COLUMNS) if with_equipment else "zoneAveTemp"
    sensor_chunks, equipment_chunks = [], []
    for chunk_start, chunk_end in chunk_date_range(start, end):
        payload = fetch_runtime_payload(
            access_token, thermostat_id, chunk_start.isoformat(), chunk_end.isoformat(), columns
        )
        sensor_list = payload.get("sensorList") or []
        if not sensor_list:
            raise RuntimeError(
                f"runtimeReport returned no sensor data for thermostat {thermostat_id} "
                f"({chunk_start} to {chunk_end})"
            )
        sensor_chunks.append(parse_sensor_series(sensor_list[0]))
        if with_equipment:
            equipment_chunks.append(parse_equipment_rows(payload))
    return merge_series(sensor_chunks), merge_equipment(equipment_chunks)


def _summarize_equipment(rows: list[dict], key_fn, label_fn) -> list[dict]:
    groups: dict = {}
    for r in rows:
        groups.setdefault(key_fn(r["ts"]), []).append(r)
    full = INTERVAL_MINUTES * 60
    buckets = []
    for k in sorted(groups):
        g = groups[k]
        outdoor = [r["outdoor"] for r in g if r["outdoor"] is not None]
        pct = lambda field: round(100 * sum(r[field] for r in g) / (full * len(g)))
        buckets.append(
            {
                "label": label_fn(k),
                "outdoor_avg": round(sum(outdoor) / len(outdoor), 1) if outdoor else None,
                "outdoor_min": min(outdoor) if outdoor else None,
                "outdoor_max": max(outdoor) if outdoor else None,
                "cool_pct": pct("cool"),
                "heat_pct": pct("heat"),
                "aux_pct": pct("aux"),
                "fan_pct": pct("fan"),
            }
        )
    return buckets


def summarize_equipment_hourly(rows: list[dict]) -> list[dict]:
    return _summarize_equipment(
        rows, lambda ts: (ts.date(), ts.hour), lambda k: f"{k[1]:02d}:00"
    )


def summarize_equipment_daily(rows: list[dict]) -> list[dict]:
    return _summarize_equipment(rows, lambda ts: ts.date(), lambda k: k.isoformat())


def format_equipment(thermostat_name: str, buckets: list[dict], granularity: str) -> str:
    label_header = "hour" if granularity == "hourly" else "date"
    col_width = 5 if granularity == "hourly" else 10
    lines = [
        f"=== {thermostat_name}: equipment ===",
        "Runtime is the share of each period the equipment ran. Outdoor is in F.",
        f"  {label_header:<{col_width}}  outdoor avg (min-max)   cool%  heat%  aux%  fan%",
    ]
    for b in buckets:
        if b["outdoor_avg"] is None:
            outdoor = "-"
        else:
            outdoor = f"{b['outdoor_avg']:.1f} ({b['outdoor_min']:.0f}-{b['outdoor_max']:.0f})"
        lines.append(
            f"  {b['label']:<{col_width}}  {outdoor:<22}  "
            f"{b['cool_pct']:<5}  {b['heat_pct']:<5}  {b['aux_pct']:<4}  {b['fan_pct']}"
        )
    return "\n".join(lines)
