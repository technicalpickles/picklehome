import pytest

from climate.ecobee.comfort_mode import (
    COMFORT_REF,
    MIN_SAMPLES,
    decide_mode,
    detect_live_mode,
    resolve_ref,
    resolve_schedule_array,
)


def test_resolve_ref_maps_modes():
    assert resolve_ref("cool") == "smart1"
    assert resolve_ref("heat") == "smart2"


def test_resolve_ref_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unknown mode"):
        resolve_ref("warm")


def test_resolve_schedule_array_replaces_only_the_virtual_ref():
    array = [[COMFORT_REF, "sleep", "away", "home"]]
    assert resolve_schedule_array(array, "heat") == [["smart2", "sleep", "away", "home"]]


def test_resolve_schedule_array_leaves_no_virtual_ref_behind():
    array = [[COMFORT_REF] * 48 for _ in range(7)]
    resolved = resolve_schedule_array(array, "cool")
    assert not any(COMFORT_REF in day for day in resolved)


def test_detect_live_mode_reads_cool():
    program = {"schedule": [["sleep", "smart1"]]}
    assert detect_live_mode(program) == "cool"


def test_detect_live_mode_reads_heat():
    program = {"schedule": [["sleep", "smart2"]]}
    assert detect_live_mode(program) == "heat"


def test_detect_live_mode_none_when_neither_present():
    program = {"schedule": [["sleep", "away", "home"]]}
    assert detect_live_mode(program) is None


def test_detect_live_mode_none_when_both_present():
    # Hand-edited in the Ecobee app; ambiguous, so refuse to guess.
    program = {"schedule": [["smart1", "smart2"]]}
    assert detect_live_mode(program) is None


def test_decide_mode_below_threshold_is_heat():
    mode, info = decide_mode([50.0] * MIN_SAMPLES, heat_below=60, cool_above=65)
    assert mode == "heat"
    assert info["mean"] == 50.0


def test_decide_mode_above_threshold_is_cool():
    mode, info = decide_mode([80.0] * MIN_SAMPLES, heat_below=60, cool_above=65)
    assert mode == "cool"


def test_decide_mode_inside_band_makes_no_change():
    mode, info = decide_mode([62.0] * MIN_SAMPLES, heat_below=60, cool_above=65)
    assert mode is None
    assert info["reason"] == "hysteresis_band"


def test_decide_mode_exactly_on_threshold_makes_no_change():
    # Thresholds are exclusive on both sides, matching the documented band.
    assert decide_mode([60.0] * MIN_SAMPLES, 60, 65)[0] is None
    assert decide_mode([65.0] * MIN_SAMPLES, 60, 65)[0] is None


def test_decide_mode_refuses_on_too_few_samples():
    mode, info = decide_mode([20.0] * (MIN_SAMPLES - 1), heat_below=60, cool_above=65)
    assert mode is None
    assert info["reason"] == "insufficient_samples"
    assert info["samples"] == MIN_SAMPLES - 1


def test_decide_mode_refuses_on_empty_window():
    mode, info = decide_mode([], heat_below=60, cool_above=65)
    assert mode is None
    assert info["reason"] == "insufficient_samples"


def test_decide_mode_averages_a_swinging_day():
    # The shoulder-season case this design exists for: a day spanning the band
    # in both directions must not flip the mode.
    temps = [45.0] * 48 + [80.0] * 48
    mode, info = decide_mode(temps, heat_below=60, cool_above=65)
    assert mode is None
    assert info["mean"] == 62.5
