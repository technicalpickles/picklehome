import argparse
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from climate.sync import _apply_comfort_mode

SCHEDULE_WITH_COOL = "        - time: \"06:00\"\n          climate: smart1\n"
SCHEDULE_WITH_HEAT = "        - time: \"06:00\"\n          climate: smart2\n"
SCHEDULE_WITH_COMMENT = "          climate: smart1  # was smart2 before\n"


def test_heat_replaces_cool_value():
    result = _apply_comfort_mode(SCHEDULE_WITH_COOL, "heat")
    assert "climate: smart2" in result
    assert "climate: smart1" not in result


def test_cool_replaces_heat_value():
    result = _apply_comfort_mode(SCHEDULE_WITH_HEAT, "cool")
    assert "climate: smart1" in result
    assert "climate: smart2" not in result


def test_comment_text_not_replaced():
    # Comment mentions "smart2" but value is smart1 — only value should flip
    result = _apply_comfort_mode(SCHEDULE_WITH_COMMENT, "heat")
    assert "climate: smart2" in result
    assert "# was smart2 before" in result  # comment preserved


def test_non_climate_smart_refs_untouched():
    text = "# smart1 is for cooling\n          climate: smart1\n"
    result = _apply_comfort_mode(text, "heat")
    assert "# smart1 is for cooling" in result  # comment unchanged
    assert "climate: smart2" in result


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown mode"):
        _apply_comfort_mode("", "warm")


def test_no_change_when_already_set():
    result = _apply_comfort_mode(SCHEDULE_WITH_HEAT, "heat")
    assert result == SCHEDULE_WITH_HEAT


# --- cmd_comfort_switch tests ---

@contextmanager
def _mock_infrastructure(previous_mode=None):
    """Patches auth, thermostat registry, and runlog so tests don't need real credentials or config."""
    mock_ecobee = MagicMock()
    mock_ecobee.get_thermostats.return_value = True
    mock_ecobee.thermostats = [MagicMock()]  # non-empty so the "failed to fetch" guard passes
    last_state = {"mode": previous_mode, "outdoor_temp_f": 70.0, "thermostats": []} if previous_mode else None
    with patch("climate.ecobee.auth.make_ecobee", return_value=mock_ecobee), \
         patch("climate.sync.load_thermostats", return_value={}), \
         patch("climate.sync.get_managed_thermostats", return_value=[]), \
         patch("climate.runlog.read_last_state", return_value=last_state), \
         patch("climate.runlog.append_run_log"), \
         patch("climate.runlog.write_last_state"), \
         patch("climate.runlog.get_data_dir", return_value=Path("/tmp/test")):
        yield mock_ecobee


def test_cmd_comfort_switch_heat(tmp_path):
    from climate.sync import cmd_comfort_switch
    schedule_file = tmp_path / "schedule.yaml"
    schedule_file.write_text(SCHEDULE_WITH_COOL)
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text("")
    args = argparse.Namespace(
        mode="heat",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=tmp_path / "weather.yaml",
        dry_run=False,
        clear_holds=False,
    )
    with _mock_infrastructure():
        with patch("climate.sync.cmd_sync") as mock_sync:
            cmd_comfort_switch(args)
    assert "smart2" in schedule_file.read_text()
    mock_sync.assert_called_once()


def test_cmd_comfort_switch_cool(tmp_path):
    from climate.sync import cmd_comfort_switch
    schedule_file = tmp_path / "schedule.yaml"
    schedule_file.write_text(SCHEDULE_WITH_HEAT)
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text("")
    args = argparse.Namespace(
        mode="cool",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=tmp_path / "weather.yaml",
        dry_run=False,
        clear_holds=False,
    )
    with _mock_infrastructure():
        with patch("climate.sync.cmd_sync") as mock_sync:
            cmd_comfort_switch(args)
    assert "smart1" in schedule_file.read_text()
    mock_sync.assert_called_once()


def test_cmd_comfort_switch_auto_heat(tmp_path):
    from climate.sync import cmd_comfort_switch
    schedule_file = tmp_path / "schedule.yaml"
    schedule_file.write_text(SCHEDULE_WITH_COOL)
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text("")
    weather_file = tmp_path / "weather.yaml"
    weather_file.write_text(
        "stations:\n  - mac: AA:BB\nthresholds:\n  heat_below: 60\n  cool_above: 65\n"
    )
    args = argparse.Namespace(
        mode="auto",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=weather_file,
        dry_run=False,
        clear_holds=False,
    )
    with _mock_infrastructure():
        with patch("climate.ambient.client.get_outdoor_temp_from_stations", return_value=("AA:BB", 45.0, 2.0)):
            with patch("climate.sync.cmd_sync") as mock_sync:
                cmd_comfort_switch(args)
    assert "smart2" in schedule_file.read_text()
    mock_sync.assert_called_once()


def test_cmd_comfort_switch_auto_cool(tmp_path):
    from climate.sync import cmd_comfort_switch
    schedule_file = tmp_path / "schedule.yaml"
    schedule_file.write_text(SCHEDULE_WITH_HEAT)
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text("")
    weather_file = tmp_path / "weather.yaml"
    weather_file.write_text(
        "stations:\n  - mac: AA:BB\nthresholds:\n  heat_below: 60\n  cool_above: 65\n"
    )
    args = argparse.Namespace(
        mode="auto",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=weather_file,
        dry_run=False,
        clear_holds=False,
    )
    with _mock_infrastructure():
        with patch("climate.ambient.client.get_outdoor_temp_from_stations", return_value=("AA:BB", 75.0, 2.0)):
            with patch("climate.sync.cmd_sync") as mock_sync:
                cmd_comfort_switch(args)
    assert "smart1" in schedule_file.read_text()
    mock_sync.assert_called_once()


def test_cmd_comfort_switch_auto_hysteresis(tmp_path, capsys):
    from climate.sync import cmd_comfort_switch
    schedule_file = tmp_path / "schedule.yaml"
    original = SCHEDULE_WITH_HEAT
    schedule_file.write_text(original)
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text("")
    weather_file = tmp_path / "weather.yaml"
    weather_file.write_text(
        "stations:\n  - mac: AA:BB\nthresholds:\n  heat_below: 60\n  cool_above: 65\n"
    )
    args = argparse.Namespace(
        mode="auto",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=weather_file,
        dry_run=False,
        clear_holds=False,
    )
    with _mock_infrastructure():
        with patch("climate.ambient.client.get_outdoor_temp_from_stations", return_value=("AA:BB", 62.0, 2.0)):
            with patch("climate.sync.cmd_sync") as mock_sync:
                cmd_comfort_switch(args)
    # No change — in hysteresis band
    assert schedule_file.read_text() == original
    mock_sync.assert_not_called()


def test_cmd_comfort_switch_sync_failure_rollback(tmp_path):
    from climate.sync import cmd_comfort_switch
    schedule_file = tmp_path / "schedule.yaml"
    original = SCHEDULE_WITH_COOL
    schedule_file.write_text(original)
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text("")
    args = argparse.Namespace(
        mode="heat",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=tmp_path / "weather.yaml",
        dry_run=False,
        clear_holds=False,
    )
    with _mock_infrastructure():
        with patch("climate.sync.cmd_sync", side_effect=SystemExit(1)):
            with pytest.raises(SystemExit):
                cmd_comfort_switch(args)
    # File should be restored to original content
    assert schedule_file.read_text() == original


def test_cmd_comfort_switch_skips_when_schedule_already_correct(tmp_path):
    # If schedule.yaml already has the right comfort ref, the file should not be
    # modified, but the schedule is still synced to Ecobee. This is intentional:
    # the auto-switch runs inside an ephemeral Docker container where schedule.yaml
    # is baked into the image and starts fresh each run. Always syncing ensures
    # Ecobee stays in the right state even if a previous sync failed mid-run.
    from climate.sync import cmd_comfort_switch
    schedule_file = tmp_path / "schedule.yaml"
    schedule_file.write_text(SCHEDULE_WITH_COOL)  # already smart1 = cool
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text("")
    args = argparse.Namespace(
        mode="cool",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=tmp_path / "weather.yaml",
        dry_run=False,
        clear_holds=False,
    )
    with _mock_infrastructure(previous_mode="cool"):
        with patch("climate.sync.cmd_sync") as mock_sync:
            cmd_comfort_switch(args)
    mock_sync.assert_called_once()  # sync always runs; container schedule.yaml is ephemeral
    assert schedule_file.read_text() == SCHEDULE_WITH_COOL  # file unchanged (already correct)


def test_cmd_comfort_switch_syncs_when_previous_mode_matches_but_schedule_stale(tmp_path):
    # Regression: previous_mode=="cool" in last-state but schedule.yaml still has smart2
    # (heat). This was the bug: the old code skipped the sync, leaving Ecobee on
    # Comfort Heat all summer. The fix: skip based on schedule content, not last-state.
    from climate.sync import cmd_comfort_switch
    schedule_file = tmp_path / "schedule.yaml"
    schedule_file.write_text(SCHEDULE_WITH_HEAT)  # stale — still has smart2
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text("")
    args = argparse.Namespace(
        mode="cool",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=tmp_path / "weather.yaml",
        dry_run=False,
        clear_holds=False,
    )
    with _mock_infrastructure(previous_mode="cool"):  # last-state says cool, but file is wrong
        with patch("climate.sync.cmd_sync") as mock_sync:
            cmd_comfort_switch(args)
    assert "smart1" in schedule_file.read_text()
    mock_sync.assert_called_once()
