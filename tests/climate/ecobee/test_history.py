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
