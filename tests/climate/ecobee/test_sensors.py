from unittest.mock import MagicMock

import pytest

from climate.ecobee.sensors import (
    apply_enrollment,
    plan_enrollment,
    push_enrollment,
    resolve_sensor_entries,
)

REMOTES = [
    {"id": "ei:0", "name": "Downstairs", "type": "thermostat"},
    {"id": "rs2:101", "name": "Josh Office", "type": "ecobee3_remote_sensor"},
    {"id": "rs2:100", "name": "Tracy Office", "type": "ecobee3_remote_sensor"},
]

THERMOSTAT_ONLY = [{"id": "ei:0:1", "name": "Downstairs"}]


def climates(*sensor_lists):
    return [
        {"climateRef": f"c{i}", "name": f"C{i}", "sensors": s}
        for i, s in enumerate(sensor_lists)
    ]


def test_resolve_builds_climate_side_ids():
    assert resolve_sensor_entries(REMOTES, ["Josh Office", "Tracy Office"]) == [
        {"id": "rs2:101:1", "name": "Josh Office"},
        {"id": "rs2:100:1", "name": "Tracy Office"},
    ]


def test_resolve_unknown_name_raises_and_lists_known():
    with pytest.raises(ValueError, match="Josh Ofice.*Tracy Office"):
        resolve_sensor_entries(REMOTES, ["Josh Ofice"])


def test_plan_lists_only_climates_that_differ():
    desired = resolve_sensor_entries(REMOTES, ["Josh Office", "Tracy Office"])
    already = [
        {"id": "rs2:100:1", "name": "Tracy Office"},
        {"id": "rs2:101:1", "name": "Josh Office"},
    ]
    changes = plan_enrollment(climates(THERMOSTAT_ONLY, already), desired)
    assert changes == [("c0", ["Downstairs"], ["Josh Office", "Tracy Office"])]


def test_plan_empty_when_everything_matches():
    desired = resolve_sensor_entries(REMOTES, ["Josh Office"])
    assert plan_enrollment(climates(desired, desired), desired) == []


def test_apply_replaces_sensors_on_every_climate_and_keeps_other_keys():
    desired = resolve_sensor_entries(REMOTES, ["Tracy Office"])
    original = climates(THERMOSTAT_ONLY)
    original[0]["coolTemp"] = 750
    result = apply_enrollment(original, desired)
    assert result[0]["sensors"] == desired
    assert result[0]["coolTemp"] == 750
    assert original[0]["sensors"] == THERMOSTAT_ONLY


def test_push_sends_schedule_and_climates():
    ecobee = MagicMock()
    ecobee._request_with_refresh.return_value = {"status": {"code": 0}}
    push_enrollment(ecobee, "tid", [["home"]], [{"climateRef": "home"}])
    method, _endpoint, msg = ecobee._request_with_refresh.call_args[0]
    body = ecobee._request_with_refresh.call_args[1]["body"]
    assert method == "POST"
    assert "climate sensors" in msg
    assert body["selection"]["selectionMatch"] == "tid"
    assert body["thermostat"]["program"] == {
        "schedule": [["home"]],
        "climates": [{"climateRef": "home"}],
    }


def test_push_raises_on_null_response():
    ecobee = MagicMock()
    ecobee._request_with_refresh.return_value = None
    with pytest.raises(RuntimeError, match="Failed to set climate sensors"):
        push_enrollment(ecobee, "tid", [], [])
