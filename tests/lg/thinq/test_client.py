import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from lg.thinq.client import (
    DEVICE_TYPE_DRYER,
    DEVICE_TYPE_REFRIGERATOR,
    DEVICE_TYPE_WASHER,
    DeviceRef,
    Laundry,
    LGThinQAuthError,
    LGThinQError,
    LGThinQRateLimitError,
    Refrigerator,
    _as_dict,
    get_appliance,
    get_appliances,
    get_laundry,
    get_refrigerator,
    list_devices,
)
from thinqconnect import ThinQAPIException

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    with (FIXTURES / f"{name}.json").open() as f:
        return json.load(f)


def _mock_api(*, device_list=None, profile=None, status=None):
    api = AsyncMock()
    api.async_get_device_list = AsyncMock(return_value=device_list)
    api.async_get_device_profile = AsyncMock(return_value=profile)
    api.async_get_device_status = AsyncMock(return_value=status)
    return api


WASHER_DEVICE = DeviceRef(
    device_id="washer-0000-0000-0000-000000000001",
    alias="Top Load Washer",
    device_type=DEVICE_TYPE_WASHER,
    model="T1789EFH_F",
)
DRYER_DEVICE = DeviceRef(
    device_id="dryer-0000-0000-0000-000000000002",
    alias="Dryer",
    device_type=DEVICE_TYPE_DRYER,
    model="RV13U6AM8W_D_US_WIFI",
)
FRIDGE_DEVICE = DeviceRef(
    device_id="fridge-0000-0000-0000-00000000003",
    alias="Refrigerator",
    device_type=DEVICE_TYPE_REFRIGERATOR,
    model="2REF11EIDG__4",
)


# ---------------------------------------------------------------------------
# list_devices
# ---------------------------------------------------------------------------


def test_list_devices_parses_real_device_list():
    api = _mock_api(device_list=_load("device_list"))

    devices = asyncio.run(list_devices(api))

    assert devices == [WASHER_DEVICE, DRYER_DEVICE, FRIDGE_DEVICE]


def test_list_devices_raises_on_none_response():
    api = _mock_api(device_list=None)

    with pytest.raises(LGThinQError, match="no data"):
        asyncio.run(list_devices(api))


def test_device_info_connected_null_is_not_exposed_or_treated_as_availability():
    # Confirmed against the account: deviceInfo.connected is always null.
    # device_list.json now carries it explicitly -- prove parsing tolerates
    # it and DeviceRef never surfaces it as an online/offline signal.
    api = _mock_api(device_list=_load("device_list"))

    devices = asyncio.run(list_devices(api))

    assert devices == [WASHER_DEVICE, DRYER_DEVICE, FRIDGE_DEVICE]
    field_names = {f for f in DeviceRef.__dataclass_fields__}
    assert not any("connect" in f.lower() for f in field_names)


# ---------------------------------------------------------------------------
# get_laundry: washer (JSON list, per-device-type active states, cycle counter)
# ---------------------------------------------------------------------------


def test_washer_running_reports_active_with_remain_and_total():
    api = _mock_api(status=_load("washer_status_running"))

    laundry = asyncio.run(get_laundry(api, WASHER_DEVICE, "washer"))

    assert laundry == Laundry(
        device_id=WASHER_DEVICE.device_id,
        appliance="washer",
        name="Top Load Washer",
        model="T1789EFH_F",
        state="RUNNING",
        active=True,
        remain_minutes=38,
        total_minutes=38,
        remote_available=False,
        cycle_count=48,
    )


def test_washer_spinning_reports_active_with_remain_and_total():
    api = _mock_api(status=_load("washer_status_spinning"))

    laundry = asyncio.run(get_laundry(api, WASHER_DEVICE, "washer"))

    assert laundry.state == "SPINNING"
    assert laundry.active is True
    assert laundry.remain_minutes == 9
    assert laundry.total_minutes == 35
    assert laundry.cycle_count == 48


def test_washer_detecting_remain_zero_is_not_yet_computed():
    # Confirmed against the account: DETECTING reports remain 0h00m / total
    # 0h58m. remain must not be rendered as "0m left" -- it's not computed
    # yet, not done.
    api = _mock_api(status=_load("washer_status_detecting"))

    laundry = asyncio.run(get_laundry(api, WASHER_DEVICE, "washer"))

    assert laundry.state == "DETECTING"
    assert laundry.active is True
    assert laundry.remain_minutes is None
    assert laundry.total_minutes == 58


def test_washer_idle_has_no_timer_values():
    # POWER_OFF retains a stale total (35m from the prior cycle) -- timer
    # values are meaningless while not active, so both must read None.
    api = _mock_api(status=_load("washer_status_idle"))

    laundry = asyncio.run(get_laundry(api, WASHER_DEVICE, "washer"))

    assert laundry.state == "POWER_OFF"
    assert laundry.active is False
    assert laundry.remain_minutes is None
    assert laundry.total_minutes is None
    assert laundry.cycle_count == 48


def test_washer_pause_is_not_active_and_has_no_timer_values():
    # PAUSE is deliberately in neither WASHER_ACTIVE_STATES nor
    # DRYER_ACTIVE_STATES (client.py module docstring / design doc): not
    # active, and not completion either. Also proves the washer's list-wrapped
    # payload shape normalizes correctly (see module docstring point 1) using
    # a non-"running" status, rather than a test that just asserts the
    # fixture is a list.
    status = [
        {
            "cycle": {"cycleCount": 48},
            "location": {"locationName": "MAIN"},
            "remoteControlEnable": {"remoteControlEnabled": False},
            "runState": {"currentState": "PAUSE"},
            "timer": {"remainHour": 0, "remainMinute": 12, "totalHour": 0, "totalMinute": 35},
        }
    ]
    api = _mock_api(status=status)

    laundry = asyncio.run(get_laundry(api, WASHER_DEVICE, "washer"))

    assert laundry.state == "PAUSE"
    assert laundry.active is False
    assert laundry.remain_minutes is None
    assert laundry.total_minutes is None
    assert laundry.cycle_count == 48


# ---------------------------------------------------------------------------
# get_laundry: dryer (dict payloads, no cycle counter, different active states)
# ---------------------------------------------------------------------------


def test_dryer_running_reports_active():
    api = _mock_api(status=_load("dryer_status_running"))

    laundry = asyncio.run(get_laundry(api, DRYER_DEVICE, "dryer"))

    assert laundry == Laundry(
        device_id=DRYER_DEVICE.device_id,
        appliance="dryer",
        name="Dryer",
        model="RV13U6AM8W_D_US_WIFI",
        state="RUNNING",
        active=True,
        remain_minutes=30,
        total_minutes=30,
        remote_available=True,
        cycle_count=None,
    )


def test_dryer_cooling_is_active_with_remaining_time():
    api = _mock_api(status=_load("dryer_status_cooling"))

    laundry = asyncio.run(get_laundry(api, DRYER_DEVICE, "dryer"))

    assert laundry.state == "COOLING"
    assert laundry.active is True
    assert laundry.remain_minutes == 5
    assert laundry.total_minutes == 30
    assert laundry.cycle_count is None


def test_dryer_idle_has_no_timer_values_despite_placeholder():
    # POWER_OFF reads a fixed 0h01m/0h01m placeholder -- meaningless, must
    # not surface as real remaining time.
    api = _mock_api(status=_load("dryer_status_idle"))

    laundry = asyncio.run(get_laundry(api, DRYER_DEVICE, "dryer"))

    assert laundry.state == "POWER_OFF"
    assert laundry.active is False
    assert laundry.remain_minutes is None
    assert laundry.total_minutes is None
    assert laundry.cycle_count is None


def test_dryer_pause_is_not_active_and_has_no_timer_values():
    # Same PAUSE contract as the washer, dict-shaped payload this time. No
    # cycle counter on the dryer either way (module docstring point 4).
    status = {
        "remoteControlEnable": {"remoteControlEnabled": False},
        "runState": {"currentState": "PAUSE"},
        "timer": {"remainHour": 0, "remainMinute": 5, "totalHour": 0, "totalMinute": 30},
    }
    api = _mock_api(status=status)

    laundry = asyncio.run(get_laundry(api, DRYER_DEVICE, "dryer"))

    assert laundry.state == "PAUSE"
    assert laundry.active is False
    assert laundry.remain_minutes is None
    assert laundry.total_minutes is None
    assert laundry.cycle_count is None


# ---------------------------------------------------------------------------
# get_refrigerator
# ---------------------------------------------------------------------------


def test_refrigerator_idle_status():
    api = _mock_api(status=_load("refrigerator_status_idle"))

    fridge = asyncio.run(get_refrigerator(api, FRIDGE_DEVICE))

    assert fridge == Refrigerator(
        device_id=FRIDGE_DEVICE.device_id,
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


def test_refrigerator_dataclass_has_no_filter_fields():
    # Both filter percentages read 0 and carry no data (see findings.md) --
    # they must not be exposed on the dataclass at all.
    field_names = {f for f in Refrigerator.__dataclass_fields__}
    assert not any("filter" in f.lower() for f in field_names)


def test_refrigerator_reads_unit_from_payload_not_hardcoded_fahrenheit():
    # The profile declares Celsius ranges; status has reported Fahrenheit on
    # this account so far but that's not guaranteed to stay true. If the
    # account's display unit ever flips, the unit must come from the payload's
    # sibling `unit` key, not an assumed literal "F".
    status = {
        "doorStatus": [{"doorState": "CLOSE", "locationName": "MAIN"}],
        "powerSave": {"powerSaveEnabled": False},
        "refrigeration": {"expressMode": False},
        "sabbath": {"sabbathMode": False},
        "temperature": [
            {"locationName": "FRIDGE", "targetTemperature": 3, "unit": "C"},
            {"locationName": "FREEZER", "targetTemperature": -18, "unit": "C"},
        ],
    }
    api = _mock_api(status=status)

    fridge = asyncio.run(get_refrigerator(api, FRIDGE_DEVICE))

    assert fridge.fridge_setpoint == 3
    assert fridge.fridge_setpoint_unit == "C"
    assert fridge.freezer_setpoint == -18
    assert fridge.freezer_setpoint_unit == "C"


def test_refrigerator_missing_unit_raises_rather_than_assuming():
    status = {
        "doorStatus": [{"doorState": "CLOSE", "locationName": "MAIN"}],
        "powerSave": {"powerSaveEnabled": False},
        "refrigeration": {"expressMode": False},
        "sabbath": {"sabbathMode": False},
        "temperature": [{"locationName": "FRIDGE", "targetTemperature": 37}],  # no "unit"
    }
    api = _mock_api(status=status)

    with pytest.raises(LGThinQError, match="unit"):
        asyncio.run(get_refrigerator(api, FRIDGE_DEVICE))


# ---------------------------------------------------------------------------
# _as_dict: washer's list-vs-dict normalization, and its error cases
# ---------------------------------------------------------------------------


def test_as_dict_passes_through_a_dict_unchanged():
    raw = {"a": 1}
    assert _as_dict(raw, "Some Device", "device status") is raw


def test_as_dict_unwraps_a_single_item_list():
    assert _as_dict([{"a": 1}], "Some Device", "device status") == {"a": 1}


def test_as_dict_raises_on_none():
    with pytest.raises(LGThinQError, match="no data"):
        _as_dict(None, "Some Device", "device status")


def test_as_dict_raises_on_empty_list():
    with pytest.raises(LGThinQError, match="empty list"):
        _as_dict([], "Some Device", "device status")


# ---------------------------------------------------------------------------
# Error handling: auth vs rate-limit vs generic, and the gather boundary
# ---------------------------------------------------------------------------


def test_wrap_auth_error_names_1password_item():
    api = _mock_api()
    api.async_get_device_status = AsyncMock(
        side_effect=ThinQAPIException(code="1103", message="invalid token", headers={})
    )

    with pytest.raises(LGThinQAuthError, match="1Password"):
        asyncio.run(get_laundry(api, WASHER_DEVICE, "washer"))


def test_wrap_rate_limit_error():
    api = _mock_api()
    api.async_get_device_status = AsyncMock(
        side_effect=ThinQAPIException(code="1306", message="too many calls", headers={})
    )

    with pytest.raises(LGThinQRateLimitError, match="transient"):
        asyncio.run(get_laundry(api, WASHER_DEVICE, "washer"))


def test_wrap_generic_error_is_not_auth_or_rate_limit():
    api = _mock_api()
    api.async_get_device_status = AsyncMock(
        side_effect=ThinQAPIException(code="2000", message="server error", headers={})
    )

    with pytest.raises(LGThinQError) as exc_info:
        asyncio.run(get_laundry(api, WASHER_DEVICE, "washer"))
    assert not isinstance(exc_info.value, LGThinQAuthError)
    assert not isinstance(exc_info.value, LGThinQRateLimitError)


def test_get_appliance_dispatches_by_device_type():
    api = _mock_api(status=_load("washer_status_running"))
    result = asyncio.run(get_appliance(api, WASHER_DEVICE))
    assert isinstance(result, Laundry)
    assert result.appliance == "washer"


def test_get_appliance_rejects_unsupported_device_type():
    unknown_device = DeviceRef(device_id="x", alias="Mystery", device_type="DEVICE_WASHTOWER", model="?")
    api = _mock_api()

    with pytest.raises(LGThinQError, match="unsupported"):
        asyncio.run(get_appliance(api, unknown_device))


def test_get_appliances_one_failure_does_not_cancel_the_others():
    api = AsyncMock()

    async def fake_status(device_id, *args, **kwargs):
        if device_id == DRYER_DEVICE.device_id:
            raise ThinQAPIException(code="1103", message="invalid token", headers={})
        return _load("washer_status_running")

    api.async_get_device_status = AsyncMock(side_effect=fake_status)

    results = asyncio.run(get_appliances(api, [WASHER_DEVICE, DRYER_DEVICE]))

    assert len(results) == 2
    (washer_device, washer_result), (dryer_device, dryer_result) = results
    assert washer_device == WASHER_DEVICE
    assert isinstance(washer_result, Laundry)
    assert dryer_device == DRYER_DEVICE
    assert isinstance(dryer_result, LGThinQAuthError)
