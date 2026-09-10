import pytest

from climate.ecobee.schedule import validate_climate_refs

PROGRAM = {"climates": [
    {"climateRef": "smart1"}, {"climateRef": "smart2"},
    {"climateRef": "sleep"}, {"climateRef": "away"}, {"climateRef": "home"},
]}


def test_virtual_comfort_ref_is_accepted():
    schedule = {"monday": [{"time": "00:00", "climate": "comfort"}]}
    validate_climate_refs(schedule, PROGRAM)  # must not raise


def test_real_refs_still_accepted():
    schedule = {"monday": [{"time": "00:00", "climate": "sleep"}]}
    validate_climate_refs(schedule, PROGRAM)


def test_unknown_ref_still_raises():
    schedule = {"monday": [{"time": "00:00", "climate": "nonsense"}]}
    with pytest.raises(ValueError, match="Unknown climate"):
        validate_climate_refs(schedule, PROGRAM)


def test_error_message_does_not_suggest_comfort_is_a_real_ref():
    schedule = {"monday": [{"time": "00:00", "climate": "nonsense"}]}
    with pytest.raises(ValueError) as exc:
        validate_climate_refs(schedule, PROGRAM)
    assert "comfort" not in str(exc.value).split("Valid climateRefs")[-1]
