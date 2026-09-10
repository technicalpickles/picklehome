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


def _write_comfort_switch_fixtures(tmp_path):
    """A single managed thermostat ("downstairs") whose entire schedule is
    the virtual comfort ref, on both schedule.yaml and thermostats.yaml.
    """
    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text(
        "thermostats:\n"
        "  downstairs:\n"
        "    thermostat_id: \"111\"\n"
        "    managed: true\n"
    )

    schedule_file = tmp_path / "schedule.yaml"
    schedule_file.write_text(
        "thermostats:\n"
        "  downstairs:\n"
        "    schedule:\n"
        + "".join(
            f"      {day}:\n        - time: \"00:00\"\n          climate: comfort\n"
            for day in (
                "sunday", "monday", "tuesday", "wednesday",
                "thursday", "friday", "saturday",
            )
        )
    )
    return schedule_file, thermostats_file


def _run_comfort_switch(
    monkeypatch, tmp_path, *, live_ref, hold, mode="heat", dry_run=False,
    status_name="Downstairs",
):
    """Drive the real cmd_comfort_switch, mocking only the Ecobee network
    boundary (auth.make_ecobee, push_schedule, resume_program) and status
    extraction. Everything else -- load_thermostats, schedule.load_schedule,
    iter_thermostat_entries, build_schedule_array, validate_climate_refs,
    resolve_schedule_array, diff_schedules, get_current_program -- runs for
    real against the fixture files, so a regression to the unconditional-push
    defect this task exists to fix would actually be caught here.

    `live_ref` is the climateRef the live program reports in every slot
    (controls whether the diff is empty or not); `hold` is what the mocked
    status reports for this thermostat's active hold. `status_name` is the
    name the status snapshot reports -- defaults to matching schedule.yaml's
    "downstairs" (case-insensitively); pass a different value to simulate a
    lookup miss (e.g. a thermostat renamed in the Ecobee app).

    Returns (push_mock, resume_mock, append_run_log_mock, write_last_state_mock).
    """
    import climate.sync as sync_mod
    from climate import runlog as runlog_mod

    schedule_file, thermostats_file = _write_comfort_switch_fixtures(tmp_path)

    live_program = {
        "schedule": [[live_ref] * 48 for _ in range(7)],
        "climates": [{"climateRef": r, "name": r} for r in
                     ("smart1", "smart2", "sleep", "away", "home")],
    }
    mock_ecobee = MagicMock()
    mock_ecobee.get_thermostats.return_value = True
    mock_ecobee.thermostats = [{"identifier": "111", "program": live_program}]

    push = MagicMock()
    resume = MagicMock()
    append_run_log = MagicMock()
    write_last_state = MagicMock()

    monkeypatch.setattr(sync_mod.auth, "make_ecobee", lambda: mock_ecobee)
    monkeypatch.setattr(sync_mod.schedule, "push_schedule", push)
    monkeypatch.setattr(sync_mod.schedule, "resume_program", resume)
    monkeypatch.setattr(
        sync_mod.status, "extract_thermostat_status",
        lambda t: {"name": status_name, "hold": hold},
    )
    monkeypatch.setattr(runlog_mod, "read_last_state", lambda data_dir: None)
    monkeypatch.setattr(runlog_mod, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(runlog_mod, "append_run_log", append_run_log)
    monkeypatch.setattr(runlog_mod, "write_last_state", write_last_state)

    args = argparse.Namespace(
        mode=mode,
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=tmp_path / "unused-weather.yaml",
        dry_run=dry_run,
        clear_holds=False,
    )
    sync_mod.cmd_comfort_switch(args)
    return push, resume, append_run_log, write_last_state


def test_push_not_called_when_schedule_matches(monkeypatch, tmp_path):
    # mode="heat" resolves comfort -> smart2; live is already smart2 everywhere.
    push, resume, _, _ = _run_comfort_switch(monkeypatch, tmp_path, live_ref="smart2", hold=None, mode="heat")
    push.assert_not_called()
    resume.assert_not_called()


def test_push_called_once_when_schedule_differs(monkeypatch, tmp_path):
    # mode="heat" resolves comfort -> smart2; live is smart1 (cool) everywhere -> mismatch.
    push, resume, _, _ = _run_comfort_switch(monkeypatch, tmp_path, live_ref="smart1", hold=None, mode="heat")
    assert push.call_count == 1
    # hold=None -> nothing is overriding the schedule, so the new program
    # should be resumed immediately rather than waiting for a slot boundary.
    resume.assert_called_once()


def test_resume_not_called_when_thermostat_has_active_hold(monkeypatch, tmp_path):
    # Same mismatch as above (push happens), but a real hold is active.
    push, resume, _, _ = _run_comfort_switch(
        monkeypatch, tmp_path, live_ref="smart1", hold="indefinite", mode="heat"
    )
    assert push.call_count == 1
    resume.assert_not_called()


def test_resume_not_called_when_hold_status_lookup_misses(monkeypatch, tmp_path):
    """The fail-closed regression guard: hold_by_name is keyed by the Ecobee
    device name, `pushed` by schedule.yaml's name, joined only by lowercase
    convention. If the Ecobee-side name doesn't match (e.g. renamed in the
    app), the old code's `.get(name.lower()) is None` treated "not found" the
    same as "confirmed no hold" and resumed anyway -- clearing a hold it
    never actually observed. It must fail closed instead."""
    push, resume, _, _ = _run_comfort_switch(
        monkeypatch, tmp_path, live_ref="smart1", hold=None, mode="heat",
        status_name="Some Renamed Thermostat",
    )
    assert push.call_count == 1
    resume.assert_not_called()


def test_dry_run_writes_nothing_persistent(monkeypatch, tmp_path):
    """--dry-run must be zero persistent writes, full stop: no push, no
    resume, no run-log entry, no last-state mutation. This is what makes it
    safe to run `climate-comfort-switch-dry` against real thermostats -- a
    dry run that clears a hold or injects a sample into the rolling window
    isn't a dry run."""
    push, resume, append_run_log, write_last_state = _run_comfort_switch(
        monkeypatch, tmp_path, live_ref="smart1", hold=None, mode="heat", dry_run=True,
    )
    push.assert_not_called()
    resume.assert_not_called()
    append_run_log.assert_not_called()
    write_last_state.assert_not_called()


def test_unmanaged_thermostat_in_schedule_yaml_is_never_pushed_to(monkeypatch, tmp_path):
    """schedule.yaml has no `managed` filter of its own -- cmd_sync/cmd_validate
    intentionally act on whatever it lists. But cmd_comfort_switch is the
    unattended timer, and thermostats.yaml's `managed: false` is the only
    thing marking a property as out of scope for it (e.g. a `cottage` entry
    that's a different property's thermostat). If schedule.yaml ever lists an
    unmanaged thermostat, the timer must not act on it."""
    import climate.sync as sync_mod
    from climate import runlog as runlog_mod

    thermostats_file = tmp_path / "thermostats.yaml"
    thermostats_file.write_text(
        "thermostats:\n"
        "  downstairs:\n"
        "    thermostat_id: \"111\"\n"
        "    managed: true\n"
        "  cottage:\n"
        "    thermostat_id: \"222\"\n"
        "    managed: false  # separate property\n"
    )
    schedule_file = tmp_path / "schedule.yaml"
    day_block = "".join(
        f"      {day}:\n        - time: \"00:00\"\n          climate: comfort\n"
        for day in (
            "sunday", "monday", "tuesday", "wednesday",
            "thursday", "friday", "saturday",
        )
    )
    schedule_file.write_text(
        "thermostats:\n"
        "  downstairs:\n"
        "    schedule:\n" + day_block +
        "  cottage:\n"  # accidentally added to schedule.yaml despite managed: false
        "    schedule:\n" + day_block
    )

    live_program = {
        "schedule": [["smart1"] * 48 for _ in range(7)],  # mismatches mode="heat" -> would diff
        "climates": [{"climateRef": r, "name": r} for r in
                     ("smart1", "smart2", "sleep", "away", "home")],
    }
    mock_ecobee = MagicMock()
    mock_ecobee.get_thermostats.return_value = True
    mock_ecobee.thermostats = [
        {"identifier": "111", "program": live_program},
        {"identifier": "222", "program": live_program},
    ]

    push = MagicMock()
    get_current_program = MagicMock(wraps=lambda ecobee, tid: live_program)

    monkeypatch.setattr(sync_mod.auth, "make_ecobee", lambda: mock_ecobee)
    monkeypatch.setattr(sync_mod.schedule, "push_schedule", push)
    monkeypatch.setattr(sync_mod.schedule, "resume_program", MagicMock())
    monkeypatch.setattr(sync_mod.schedule, "get_current_program", get_current_program)
    monkeypatch.setattr(
        sync_mod.status, "extract_thermostat_status",
        lambda t: {"name": "Downstairs" if t["identifier"] == "111" else "Cottage", "hold": None},
    )
    monkeypatch.setattr(runlog_mod, "read_last_state", lambda data_dir: None)
    monkeypatch.setattr(runlog_mod, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(runlog_mod, "append_run_log", lambda *a, **kw: None)
    monkeypatch.setattr(runlog_mod, "write_last_state", lambda *a, **kw: None)

    args = argparse.Namespace(
        mode="heat",
        schedule=schedule_file,
        thermostats=thermostats_file,
        weather=tmp_path / "unused-weather.yaml",
        dry_run=False,
        clear_holds=False,
    )
    sync_mod.cmd_comfort_switch(args)

    # get_current_program is only ever called for entries that survived the
    # managed-set intersection -- if "cottage" leaked through, it would be
    # called with thermostat_id "222".
    called_ids = {call.args[1] for call in get_current_program.call_args_list}
    assert called_ids == {"111"}
    assert push.call_count == 1
    assert push.call_args.args[1] == "111"


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


def test_invalid_token_during_get_thermostats_exits_cleanly(monkeypatch, capsys):
    """The real-world failure mode: tokens expire before the *first* network
    call in the function (ecobee.get_thermostats()), not mid-loop. pyecobee
    propagates InvalidTokenError from that call directly rather than
    returning False, so it must be guarded there specifically -- a guard
    later in the function (e.g. around get_current_program) never gets a
    chance to run."""
    import climate.sync as sync_mod
    from climate import runlog as runlog_mod

    mock_ecobee = MagicMock()
    mock_ecobee.get_thermostats.side_effect = InvalidTokenError("expired")

    monkeypatch.setattr(sync_mod.auth, "make_ecobee", lambda: mock_ecobee)
    monkeypatch.setattr(sync_mod, "load_thermostats", lambda path: {})
    monkeypatch.setattr(sync_mod, "get_managed_thermostats", lambda registry: [])
    monkeypatch.setattr(runlog_mod, "read_last_state", lambda data_dir: None)
    monkeypatch.setattr(runlog_mod, "get_data_dir", lambda: Path("/tmp/test"))
    # If the code under test reached this far, the guard failed -- the
    # exception should stop the function before any schedule I/O happens.
    monkeypatch.setattr(
        sync_mod.schedule, "load_schedule",
        MagicMock(side_effect=AssertionError("should not reach schedule I/O")),
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


def test_invalid_token_during_push_prints_message_and_exits_nonzero(monkeypatch, capsys):
    """A narrower case than the get_thermostats guard above: tokens are
    valid for the initial fetch but expire before a specific thermostat's
    get_current_program call (e.g. a long-lived process, or the token
    expiring mid-run). Guards the per-thermostat try/except independently."""
    import climate.sync as sync_mod
    from climate import runlog as runlog_mod

    mock_ecobee = MagicMock()
    mock_ecobee.get_thermostats.return_value = True
    mock_ecobee.thermostats = [MagicMock()]  # non-empty so the "failed to fetch" guard passes

    # `runlog` is imported locally inside cmd_comfort_switch (`from climate
    # import runlog`), so patching the actual `climate.runlog` module -- not
    # an attribute of `climate.sync` -- is what that local import picks up.
    monkeypatch.setattr(sync_mod.auth, "make_ecobee", lambda: mock_ecobee)
    monkeypatch.setattr(sync_mod, "load_thermostats", lambda path: {})
    # Must include thermostat_id "123" -- cmd_comfort_switch now intersects
    # schedule.yaml entries with the managed set before pushing to them.
    monkeypatch.setattr(sync_mod, "get_managed_thermostats", lambda registry: [("downstairs", "123")])
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
