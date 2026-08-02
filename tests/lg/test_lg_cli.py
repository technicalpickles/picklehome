import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from lg import lg_cli
from lg.lg_cli import (
    DEVICE_TYPE_DRYER,
    DEVICE_TYPE_REFRIGERATOR,
    DEVICE_TYPE_WASHER,
    _describe_failure,
    _fmt_minutes,
    _last_cycle_line,
    _print_fridge_detail,
    _print_laundry_detail,
    _print_status_line,
    _state_label,
    cmd_status,
)
from lg.thinq.client import DeviceRef, Laundry, LGThinQAuthError, LGThinQError, Refrigerator
from lg.thinq.observations import append_observation

WASHER_DEVICE = DeviceRef(
    device_id="washer-1", alias="Top Load Washer", device_type=DEVICE_TYPE_WASHER, model="T1789EFH_F"
)
DRYER_DEVICE = DeviceRef(
    device_id="dryer-1", alias="Dryer", device_type=DEVICE_TYPE_DRYER, model="RV13U6AM8W_D_US_WIFI"
)
FRIDGE_DEVICE = DeviceRef(device_id="fridge-1", alias="Refrigerator", device_type="DEVICE_REFRIGERATOR", model="2REF11EIDG__4")


def _laundry(**overrides) -> Laundry:
    defaults = dict(
        device_id="washer-1",
        appliance="washer",
        name="Top Load Washer",
        model="T1789EFH_F",
        state="POWER_OFF",
        active=False,
        remain_minutes=None,
        total_minutes=None,
        remote_available=False,
        cycle_count=None,
    )
    defaults.update(overrides)
    return Laundry(**defaults)


def test_fmt_minutes():
    assert _fmt_minutes(9) == "9m"
    assert _fmt_minutes(60) == "1h"
    assert _fmt_minutes(65) == "1h 5m"


def test_state_label_maps_power_off_to_off():
    assert _state_label("POWER_OFF") == "off"
    assert _state_label("RINSING") == "rinsing"


def test_fridge_setpoints_always_labeled(capsys):
    fridge = Refrigerator(
        device_id="fridge-1",
        name="Refrigerator",
        model="2REF11EIDG__4",
        door_state="closed",
        fridge_setpoint=37,
        fridge_setpoint_unit="F",
        freezer_setpoint=0,
        freezer_setpoint_unit="F",
        power_save=True,
        express_mode=False,
        sabbath_mode=False,
    )

    _print_fridge_detail(FRIDGE_DEVICE, fridge)

    out = capsys.readouterr().out
    assert "37 F  (setpoint)" in out
    assert "0 F  (setpoint)" in out
    # The label isn't optional decoration -- it must appear on every temperature line.
    assert out.count("(setpoint)") == 2


def test_unavailable_device_rendering_in_status_line(capsys):
    _print_status_line(WASHER_DEVICE, TimeoutError("boom"))

    out = capsys.readouterr().out
    assert "Top Load Washer" in out
    assert "unavailable" in out


def test_unavailable_device_rendering_in_fridge_detail(capsys):
    _print_fridge_detail(FRIDGE_DEVICE, LGThinQError("device status failed"))

    out = capsys.readouterr().out
    assert "unavailable" in out


def test_describe_failure_classifies_auth_error():
    assert _describe_failure(LGThinQAuthError("token bad")) == "auth error"


def test_describe_failure_classifies_timeout():
    import asyncio

    assert _describe_failure(asyncio.TimeoutError()) == "timeout"


def test_describe_failure_falls_back_to_str():
    assert _describe_failure(RuntimeError("some other problem")) == "some other problem"


# ---------------------------------------------------------------------------
# _last_cycle_line / _print_laundry_detail: idle, DETECTING, PAUSE, dryer
# ---------------------------------------------------------------------------


def test_idle_washer_renders_no_remaining_line(capsys):
    laundry = _laundry(state="POWER_OFF", active=False, cycle_count=48)

    _print_laundry_detail(WASHER_DEVICE, laundry)

    out = capsys.readouterr().out
    assert "Remaining:" not in out


def test_detecting_washer_never_renders_bare_0m(capsys):
    # remain=0 while active means "not yet computed", not "0m left"
    # (client.py already encodes this as None) -- this is the renderer-layer
    # check that a regression there couldn't slip a literal "0m" past.
    laundry = _laundry(state="DETECTING", active=True, remain_minutes=None, total_minutes=58, cycle_count=48)

    _print_laundry_detail(WASHER_DEVICE, laundry)

    out = capsys.readouterr().out
    assert "0m" not in out
    assert "calculating" in out


def test_last_cycle_line_dryer_always_returns_none():
    # The dryer has no cycle counter -- it must never get a "Last cycle"
    # line, no matter what's in the log (module docstring / design doc
    # "Completion detection" section).
    dryer = _laundry(
        device_id="dryer-1", appliance="dryer", name="Dryer", model="RV13U6AM8W_D_US_WIFI", cycle_count=None
    )

    assert _last_cycle_line(DRYER_DEVICE, dryer) is None


def test_paused_washer_prints_no_last_cycle_line(monkeypatch, tmp_path, capsys):
    # PAUSE is not active, so without the explicit PAUSE exclusion this would
    # otherwise render "Last cycle: finished ..." directly under
    # "State: pause" -- reading as if the load in the machine right now just
    # finished, when it describes the previous one.
    log_path = tmp_path / "observations.jsonl"
    monkeypatch.setattr(lg_cli, "LOG_PATH", log_path)
    now = datetime.now(timezone.utc)
    append_observation(log_path, "washer-1", now - timedelta(hours=2), {"cycle_count": 47})
    append_observation(log_path, "washer-1", now - timedelta(hours=1, minutes=55), {"cycle_count": 48})

    laundry = _laundry(state="PAUSE", active=False, cycle_count=48)

    _print_laundry_detail(WASHER_DEVICE, laundry)

    out = capsys.readouterr().out
    assert "Last cycle" not in out
    assert "State:      pause" in out


# ---------------------------------------------------------------------------
# cmd_status end to end: the test that would have caught finding #1
# ---------------------------------------------------------------------------


def test_cmd_status_end_to_end_covers_all_three_device_types(monkeypatch, tmp_path, capsys):
    # cmd_status (and therefore `just lg status`) crashed on any command
    # touching the fridge, because _log_result assumed every result had a
    # `.state` -- Refrigerator doesn't. Exercise the real fetch -> log ->
    # print path for washer + dryer + fridge together, against a real
    # tmp_path observation log (not mocked away), so a crash anywhere in that
    # path fails this test instead of 50 green unit tests hiding it.
    log_path = tmp_path / "observations.jsonl"
    monkeypatch.setattr(lg_cli, "LOG_PATH", log_path)

    washer_result = _laundry(
        state="RINSING", active=True, remain_minutes=22, total_minutes=35, remote_available=True, cycle_count=48
    )
    dryer_result = _laundry(
        device_id="dryer-1", appliance="dryer", name="Dryer", model="RV13U6AM8W_D_US_WIFI", state="POWER_OFF"
    )
    fridge_result = Refrigerator(
        device_id="fridge-1",
        name="Refrigerator",
        model="2REF11EIDG__4",
        door_state="closed",
        fridge_setpoint=37,
        fridge_setpoint_unit="F",
        freezer_setpoint=0,
        freezer_setpoint_unit="F",
        power_save=True,
        express_mode=False,
        sabbath_mode=False,
    )

    fake_session = AsyncMock()
    monkeypatch.setattr(lg_cli.auth, "connect", AsyncMock(return_value=(AsyncMock(), fake_session)))
    monkeypatch.setattr(lg_cli, "list_devices", AsyncMock(return_value=[WASHER_DEVICE, DRYER_DEVICE, FRIDGE_DEVICE]))
    monkeypatch.setattr(
        lg_cli,
        "get_appliances",
        AsyncMock(
            return_value=[
                (WASHER_DEVICE, washer_result),
                (DRYER_DEVICE, dryer_result),
                (FRIDGE_DEVICE, fridge_result),
            ]
        ),
    )

    asyncio.run(cmd_status(json_output=False))

    out = capsys.readouterr().out
    assert "Top Load Washer" in out
    assert "Dryer" in out
    assert "Refrigerator" in out
    fake_session.close.assert_awaited_once()

    # All three results, including the fridge, must have been logged --
    # proving _log_result didn't just silently swallow the fridge via the
    # broadened except, but actually recorded something for it.
    log_lines = log_path.read_text().strip().splitlines()
    assert len(log_lines) == 3
