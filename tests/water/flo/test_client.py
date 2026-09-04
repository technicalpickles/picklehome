import asyncio
import json
import pathlib

import pytest
from aioflo.errors import RequestError

from water.flo.client import MoenFloError, fetch_raw, parse_valve

FIXTURE = json.loads(
    (pathlib.Path(__file__).parents[2] / "fixtures" / "flo-device.json").read_text()
)


def _device():
    return FIXTURE["devices"][0]


def test_parses_the_real_fixture_without_raising():
    valve = parse_valve(_device())
    assert valve.state in {"open", "closed", "unknown"}


def test_state_comes_from_valve_lastKnown():
    # The fixture's valve block is {"target": "open", "lastKnown": "open"} --
    # there is no valve.lastKnownState in the real payload.
    valve = parse_valve(_device())
    assert valve.state == "open"


def test_mode_comes_from_the_device_not_the_location():
    # The location's systemMode only carries a "target"; the device's
    # systemMode carries "lastKnown", which is the only observed value
    # available anywhere in the payload.
    valve = parse_valve(_device())
    assert valve.mode == "sleep"


def test_reports_unknown_rather_than_crashing_on_a_missing_valve_block():
    stripped = {k: v for k, v in _device().items() if k != "valve"}
    assert parse_valve(stripped).state == "unknown"


def test_missing_telemetry_yields_none_not_zero():
    stripped = {k: v for k, v in _device().items() if k != "telemetry"}
    valve = parse_valve(stripped)
    assert valve.gpm is None
    assert valve.psi is None
    assert valve.temp_f is None
    assert valve.telemetry_updated is None


def test_telemetry_updated_is_read_from_the_fixture():
    valve = parse_valve(_device())
    assert valve.telemetry_updated == "2026-09-04T11:57:00Z"


def test_alarm_count_is_a_list_not_an_int_and_is_excluded_from_the_sum():
    # notifications.pending.alarmCount is a list ([]) in the real payload,
    # not an int like infoCount/warningCount/criticalCount. A naive sum()
    # over every key ending in "Count" would raise TypeError on this account;
    # the isinstance(v, int) guard in parse_valve is load-bearing.
    device = _device()
    assert isinstance(device["notifications"]["pending"]["alarmCount"], list)
    valve = parse_valve(device)
    assert valve.pending_alerts == 0


def test_alarm_count_list_with_entries_still_does_not_crash():
    device = json.loads(json.dumps(_device()))
    device["notifications"]["pending"]["alarmCount"] = ["some-alarm-id"]
    valve = parse_valve(device)
    assert valve.pending_alerts == 0


def test_request_failure_after_auth_raises_moenfloerror():
    class Boom:
        class user:
            @staticmethod
            async def get_info(**kwargs):
                raise RequestError("network went away")

    async def _run():
        with pytest.raises(MoenFloError, match="network went away"):
            await fetch_raw(Boom())

    asyncio.run(_run())
