"""Tests for get_current_program's schedule-shape validation.

diff_schedules is built on nested zip(), which silently truncates to the
shorter iterable. A missing, empty, or ragged remote schedule would zip to
zero diffs and read as "already correct" forever -- with nothing to
self-correct it, since the diff is now the only thing gating the push
(see hvac-spec.md / the 2026-09-10 design). get_current_program must catch
this shape before it ever reaches diff_schedules.
"""
from unittest.mock import MagicMock

import pytest

from climate.ecobee.schedule import get_current_program


def _thermostat(program):
    return {"identifier": "111", "program": program}


def _valid_schedule():
    return [["home"] * 48 for _ in range(7)]


def _make_ecobee(program):
    mock_ecobee = MagicMock()
    mock_ecobee.get_thermostats.return_value = True
    mock_ecobee.thermostats = [_thermostat(program)]
    return mock_ecobee


def test_valid_schedule_shape_passes():
    program = {"schedule": _valid_schedule(), "climates": []}
    ecobee = _make_ecobee(program)
    result = get_current_program(ecobee, "111")
    assert result is program


def test_missing_schedule_key_raises():
    program = {"climates": []}
    ecobee = _make_ecobee(program)
    with pytest.raises(RuntimeError, match="malformed schedule"):
        get_current_program(ecobee, "111")


def test_empty_schedule_list_raises():
    # This is the degenerate case that would previously zip() to [] diffs
    # and be reported as "already correct" forever.
    program = {"schedule": [], "climates": []}
    ecobee = _make_ecobee(program)
    with pytest.raises(RuntimeError, match="malformed schedule"):
        get_current_program(ecobee, "111")


def test_wrong_day_count_raises():
    program = {"schedule": _valid_schedule()[:3], "climates": []}
    ecobee = _make_ecobee(program)
    with pytest.raises(RuntimeError, match="malformed schedule"):
        get_current_program(ecobee, "111")


def test_ragged_day_raises():
    schedule = _valid_schedule()
    schedule[2] = []
    program = {"schedule": schedule, "climates": []}
    ecobee = _make_ecobee(program)
    with pytest.raises(RuntimeError, match="malformed schedule"):
        get_current_program(ecobee, "111")


def test_no_program_data_still_raises_original_message():
    ecobee = MagicMock()
    ecobee.get_thermostats.return_value = True
    ecobee.thermostats = [{"identifier": "111"}]  # no "program" key
    with pytest.raises(RuntimeError, match="returned no program data"):
        get_current_program(ecobee, "111")
