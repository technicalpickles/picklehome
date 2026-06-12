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
            lines.append(f"  {ts.isoformat(sep=' '):<20} {temp:<6} {occ}")
        lines.append("")
    return "\n".join(lines).rstrip()
