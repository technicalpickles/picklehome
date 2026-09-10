import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pyecobee.errors import InvalidTokenError

from climate.ecobee.comfort_mode import COMFORT_REF, resolve_schedule_array


def _program(ref):
    """A live program whose occupied slots all use `ref`."""
    return {
        "schedule": [["sleep"] * 15 + [ref] * 33 for _ in range(7)],
        "climates": [{"climateRef": r, "name": r} for r in
                     ("smart1", "smart2", "sleep", "away", "home")],
    }


def _local_array():
    return [["sleep"] * 15 + [COMFORT_REF] * 33 for _ in range(7)]


def test_resolved_array_matches_live_when_mode_unchanged():
    # The idempotence property: same decision, same live state -> nothing to push.
    from climate.ecobee.schedule import diff_schedules
    live = _program("smart1")
    desired = resolve_schedule_array(_local_array(), "cool")
    assert diff_schedules(desired, live["schedule"], live) == []


def test_resolved_array_differs_when_mode_changes():
    from climate.ecobee.schedule import diff_schedules
    live = _program("smart1")
    desired = resolve_schedule_array(_local_array(), "heat")
    assert diff_schedules(desired, live["schedule"], live) != []


def test_resolved_array_never_contains_the_virtual_ref():
    # Guard the global constraint: `comfort` must never reach the Ecobee API.
    for mode in ("cool", "heat"):
        desired = resolve_schedule_array(_local_array(), mode)
        assert not any(COMFORT_REF in day for day in desired)


def test_push_not_called_when_schedule_matches(monkeypatch):
    from climate.ecobee import schedule as schedule_mod
    push = MagicMock()
    monkeypatch.setattr(schedule_mod, "push_schedule", push)

    live = _program("smart1")
    desired = resolve_schedule_array(_local_array(), "cool")
    if schedule_mod.diff_schedules(desired, live["schedule"], live):
        schedule_mod.push_schedule(MagicMock(), "tid", desired, live["climates"])
    push.assert_not_called()


def test_push_called_once_when_schedule_differs(monkeypatch):
    from climate.ecobee import schedule as schedule_mod
    push = MagicMock()
    monkeypatch.setattr(schedule_mod, "push_schedule", push)

    live = _program("smart1")
    desired = resolve_schedule_array(_local_array(), "heat")
    if schedule_mod.diff_schedules(desired, live["schedule"], live):
        schedule_mod.push_schedule(MagicMock(), "tid", desired, live["climates"])
    assert push.call_count == 1


def test_comfort_switch_never_sets_hvac_mode():
    """The timer must not write hvacMode. Regression guard for 'cannot turn it off'."""
    import climate.sync as sync_mod
    src = __import__("inspect").getsource(sync_mod.cmd_comfort_switch)
    assert "set_hvac_mode" not in src


def test_apply_comfort_mode_is_gone():
    """The text-mutation approach is deleted, not merely unused."""
    import climate.sync as sync_mod
    assert not hasattr(sync_mod, "_apply_comfort_mode")


# --- _resolve_mode_for_push: not covered by the brief's test list, added
# here because this is the function that stops the whole system from
# silently defaulting a season it can't determine. ---


def _live_program(*refs):
    """A live program whose occupied slots use the given climateRefs."""
    return {"schedule": [[r] for r in refs], "climates": []}


def test_explicit_mode_wins_over_live_and_window():
    from climate.sync import _resolve_mode_for_push
    program = _live_program("smart1")  # live = cool
    mode, info = _resolve_mode_for_push(program, "heat", {}, MagicMock())
    assert mode == "heat"
    assert info["reason"] == "explicit_mode"


def test_preserves_live_mode_when_no_explicit_mode():
    from climate.sync import _resolve_mode_for_push
    program = _live_program("smart2")  # live = heat
    mode, info = _resolve_mode_for_push(program, None, {}, MagicMock())
    assert mode == "heat"
    assert info["reason"] == "preserved_live_mode"


def test_falls_back_to_window_when_live_mode_undeterminable(monkeypatch):
    from climate.sync import _resolve_mode_for_push
    from climate import runlog as runlog_mod

    monkeypatch.setattr(
        runlog_mod, "read_recent_outdoor_temps", lambda data_dir: [50.0] * 48
    )
    program = _live_program()  # no smart1/smart2 present -> live is None
    mode, info = _resolve_mode_for_push(
        program, None, {"thresholds": {"heat_below": 60, "cool_above": 65}}, MagicMock()
    )
    assert mode == "heat"
    assert info["reason"] == "below_heat_threshold"


def test_raises_rather_than_defaulting_when_undeterminable(monkeypatch):
    from climate.sync import _resolve_mode_for_push
    from climate import runlog as runlog_mod

    monkeypatch.setattr(runlog_mod, "read_recent_outdoor_temps", lambda data_dir: [])
    program = _live_program()  # live is None, and the window is empty too
    with pytest.raises(RuntimeError, match="Cannot determine the comfort mode"):
        _resolve_mode_for_push(program, None, {}, MagicMock())


# --- cmd_comfort_switch: unattended-run error handling ---
#
# This runs unattended every 15 minutes on a home server. An expired token
# must produce the actionable message and a non-zero exit, not a traceback
# dumped into the journal for someone to find later.


def test_invalid_token_during_push_prints_message_and_exits_nonzero(monkeypatch, capsys):
    import climate.sync as sync_mod
    from climate import runlog as runlog_mod

    mock_ecobee = MagicMock()
    mock_ecobee.get_thermostats.return_value = True
    mock_ecobee.thermostats = [MagicMock()]  # non-empty so the "failed to fetch" guard passes

    # No managed thermostats needed for the status-logging side of the
    # function; only `iter_thermostat_entries` needs to yield the one entry
    # that drives the push loop where get_current_program is exercised.
    # `runlog` is imported locally inside cmd_comfort_switch (`from climate
    # import runlog`), so patching the actual `climate.runlog` module -- not
    # an attribute of `climate.sync` -- is what that local import picks up.
    monkeypatch.setattr(sync_mod.auth, "make_ecobee", lambda: mock_ecobee)
    monkeypatch.setattr(sync_mod, "load_thermostats", lambda path: {})
    monkeypatch.setattr(sync_mod, "get_managed_thermostats", lambda registry: [])
    monkeypatch.setattr(runlog_mod, "read_last_state", lambda data_dir: None)
    monkeypatch.setattr(runlog_mod, "get_data_dir", lambda: Path("/tmp/test"))
    monkeypatch.setattr(runlog_mod, "append_run_log", lambda *a, **kw: None)
    monkeypatch.setattr(runlog_mod, "write_last_state", lambda *a, **kw: None)
    monkeypatch.setattr(
        sync_mod.schedule, "load_schedule",
        lambda path: {"thermostats": {"downstairs": {"schedule": {}}}},
    )
    monkeypatch.setattr(
        sync_mod.schedule, "iter_thermostat_entries",
        lambda data, registry, name_filter: iter([("downstairs", "123", {})]),
    )
    monkeypatch.setattr(
        sync_mod.schedule, "get_current_program",
        MagicMock(side_effect=InvalidTokenError("expired")),
    )

    args = argparse.Namespace(
        mode="heat",
        schedule=Path("unused-schedule.yaml"),
        thermostats=Path("unused-thermostats.yaml"),
        weather=Path("unused-weather.yaml"),
        dry_run=False,
        clear_holds=False,
    )

    with pytest.raises(SystemExit) as exc_info:
        sync_mod.cmd_comfort_switch(args)

    assert exc_info.value.code == 1
    assert "Tokens invalid. Re-run 'just climate-auth'." in capsys.readouterr().out
