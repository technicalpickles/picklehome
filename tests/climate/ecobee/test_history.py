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
    assert "Thermostat" in series
    thermo = series["Thermostat"]
    assert thermo["temps"][0] == (datetime(2026, 6, 11, 22, 0), 73.2)
    assert thermo["occupancy"][0] == (datetime(2026, 6, 11, 22, 0), 1)


def test_temps_are_display_units_not_decidegrees():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    assert tracy["temps"][0][1] == 75.6


def test_monitor_only_sensors_excluded():
    names = {s["name"] for s in parse_sensor_series(REPORT)}
    assert names == {"Tracy Office", "Thermostat"}


from climate.ecobee.history import summarize_hourly


def test_summarize_hourly_buckets_by_hour_with_occupied_minutes():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    summary = summarize_hourly(tracy)
    assert summary["name"] == "Tracy Office"
    buckets = {b["label"]: b for b in summary["buckets"]}
    assert buckets["09:00"]["avg"] == 75.6
    assert buckets["09:00"]["min"] == 74.9
    assert buckets["09:00"]["max"] == 76.3
    assert buckets["09:00"]["occupied_min"] == 10
    assert buckets["10:00"]["occupied_min"] == 0
    assert summary["overall"]["min"] == 72.4
    assert summary["overall"]["max"] == 76.3
    assert summary["overall"]["occupied_min"] == 10


from climate.ecobee.history import summarize_daily


def test_summarize_daily_buckets_by_date():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    summary = summarize_daily(tracy)
    buckets = {b["label"]: b for b in summary["buckets"]}
    assert buckets["2026-06-11"]["min"] == 75.6
    assert buckets["2026-06-11"]["max"] == 75.6
    assert buckets["2026-06-11"]["occupied_min"] == 0
    assert buckets["2026-06-12"]["min"] == 72.4
    assert buckets["2026-06-12"]["max"] == 76.3
    assert buckets["2026-06-12"]["occupied_min"] == 10


from climate.ecobee.history import format_history, format_raw


def test_format_history_single_day_has_hour_header_and_range():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    out = format_history("Downstairs", [summarize_hourly(tracy)], "hourly")
    assert "=== Downstairs ===" in out
    assert "Tracy Office" in out
    assert "hour" in out
    assert "09:00" in out
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


def test_format_raw_temps_are_one_decimal():
    tracy = _by_name(parse_sensor_series(REPORT))["Tracy Office"]
    out = format_raw("Downstairs", [tracy])
    # every temperature reading renders with exactly one decimal place
    assert "75.6" in out
    assert "72.4" in out
    # the occupancy "occupied" first reading (75.6 @ 22:05) shows occ 0
    assert "2026-06-11 22:05:00" in out


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


# --- date windows, chunking, merging, equipment ---------------------------------

from datetime import date

from climate.ecobee.history import (
    chunk_date_range,
    fetch_range,
    format_equipment,
    merge_equipment,
    merge_series,
    parse_equipment_rows,
    resolve_window,
    summarize_equipment_daily,
)

TODAY = date(2026, 10, 18)


def test_resolve_window_defaults_to_today():
    assert resolve_window(None, None, None, TODAY) == (TODAY, TODAY)


def test_resolve_window_days_counts_back_inclusive():
    assert resolve_window(7, None, None, TODAY) == (date(2026, 10, 12), TODAY)


def test_resolve_window_start_defaults_end_to_today():
    assert resolve_window(None, date(2026, 3, 11), None, TODAY) == (date(2026, 3, 11), TODAY)


@pytest.mark.parametrize(
    "days,start,end",
    [
        (7, date(2026, 10, 1), None),  # --days with --start
        (None, None, date(2026, 10, 1)),  # --end without --start
        (None, date(2026, 10, 5), date(2026, 10, 1)),  # end before start
        (0, None, None),
    ],
)
def test_resolve_window_rejects_bad_combinations(days, start, end):
    with pytest.raises(ValueError):
        resolve_window(days, start, end, TODAY)


def test_chunk_date_range_short_range_is_one_chunk():
    assert chunk_date_range(date(2026, 10, 1), date(2026, 10, 7)) == [
        (date(2026, 10, 1), date(2026, 10, 7))
    ]


def test_chunk_date_range_splits_without_gaps_or_overlap():
    chunks = chunk_date_range(date(2026, 3, 11), date(2026, 10, 18), max_days=31)
    assert chunks[0][0] == date(2026, 3, 11)
    assert chunks[-1][1] == date(2026, 10, 18)
    for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:]):
        assert (next_start - prev_end).days == 1
    assert all((e - s).days + 1 <= 31 for s, e in chunks)


def test_merge_series_dedupes_overlap_and_sorts():
    t1, t2, t3 = (datetime(2026, 6, 1, 0, m) for m in (0, 5, 10))
    a = [{"name": "Tracy Office", "temps": [(t1, 70.0), (t2, 71.0)], "occupancy": [(t1, 0)]}]
    b = [{"name": "Tracy Office", "temps": [(t2, 71.0), (t3, 72.0)], "occupancy": []}]
    [merged] = merge_series([b, a])
    assert merged["temps"] == [(t1, 70.0), (t2, 71.0), (t3, 72.0)]
    assert merged["occupancy"] == [(t1, 0)]


EQUIP_PAYLOAD = {
    "columns": "compCool1,compCool2,compHeat1,compHeat2,auxHeat1,auxHeat2,fan,outdoorTemp",
    "reportList": [
        {
            "rowList": [
                "2026-10-15,09:00:00,300,0,0,0,0,0,300,80.0",
                "2026-10-15,09:05:00,150,60,0,0,0,0,300,82.0",  # stage 2 inside stage 1
                "2026-10-15,09:10:00,,,,,,,,",  # blank row
                "2026-10-16,09:00:00,0,0,0,0,0,0,0,70.0",
            ]
        }
    ],
}


def test_parse_equipment_rows_takes_larger_stage_and_handles_blanks():
    rows = parse_equipment_rows(EQUIP_PAYLOAD)
    assert rows[0]["cool"] == 300 and rows[0]["outdoor"] == 80.0
    assert rows[1]["cool"] == 150  # max of the two stages, not the sum
    assert rows[2]["cool"] == 0 and rows[2]["outdoor"] is None


def test_parse_equipment_rows_without_report_list_is_empty():
    assert parse_equipment_rows({"columns": "", "reportList": []}) == []


def test_summarize_equipment_daily_weights_runtime_by_interval():
    daily = summarize_equipment_daily(parse_equipment_rows(EQUIP_PAYLOAD))
    first, second = daily
    assert first["label"] == "2026-10-15"
    # 300 + 150 + 0 seconds out of 3 full intervals
    assert first["cool_pct"] == 50
    assert first["fan_pct"] == 67
    assert first["outdoor_avg"] == 81.0
    assert second["cool_pct"] == 0


def test_format_equipment_has_header_and_rows():
    out = format_equipment("Downstairs", summarize_equipment_daily(parse_equipment_rows(EQUIP_PAYLOAD)), "daily")
    assert "=== Downstairs: equipment ===" in out
    assert "2026-10-15" in out and "81.0 (80-82)" in out


def test_fetch_range_requests_each_chunk_and_merges():
    seen = []

    def fake_get(url, params, headers):
        body = json.loads(params["body"])
        seen.append((body["startDate"], body["endDate"], body["columns"]))
        payload = {
            "status": {"code": 0},
            "columns": EQUIP_PAYLOAD["columns"],
            "reportList": EQUIP_PAYLOAD["reportList"],
            "sensorList": [{"sensors": [], "columns": ["date", "time"], "data": []}],
        }
        return MagicMock(status_code=200, json=lambda: payload)

    with patch("climate.ecobee.history.requests.get", side_effect=fake_get):
        series, equipment = fetch_range(
            "TOK", "532572869586", date(2026, 8, 1), date(2026, 9, 15), with_equipment=True
        )
    assert len(seen) == 2  # 46 days -> two chunks under the API's 33-day cap
    assert seen[0][0] == "2026-08-01" and seen[-1][1] == "2026-09-15"
    assert "compCool1" in seen[0][2]
    assert len(equipment) == 4  # identical rows from both chunks de-duplicate
    assert series == []


def test_fetch_range_without_equipment_asks_for_cheap_column_only():
    seen = []

    def fake_get(url, params, headers):
        seen.append(json.loads(params["body"])["columns"])
        payload = {
            "status": {"code": 0},
            "sensorList": [{"sensors": [], "columns": ["date", "time"], "data": []}],
        }
        return MagicMock(status_code=200, json=lambda: payload)

    with patch("climate.ecobee.history.requests.get", side_effect=fake_get):
        _, equipment = fetch_range("TOK", "x", date(2026, 10, 1), date(2026, 10, 2))
    assert seen == ["zoneAveTemp"] and equipment == []
