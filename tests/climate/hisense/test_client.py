import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from climate.hisense.client import (
    HisenseError,
    build_control_properties,
    get_units,
    set_unit,
    unit_from_appliance,
)


def _appliance(**overrides):
    """A fake ConnectLifeAppliance. status_list values are ints, as the
    library's convert() coerces them."""
    status = {
        "t_power": 0,
        "t_work_mode": 2,
        "t_temp": 70,
        "f_temp_in": 73,
        "f_humidity": 128,  # sentinel: no reading
        "t_fan_speed": 0,
        "f_e_waterfull": 0,
        "f_e_inwifi": 0,
    }
    status.update(overrides.pop("status", {}))
    data = {
        "puid": "puid-1",
        "device_nickname": "Master Bedroom AC",
        "room_name": "Master Bedroom",
        "offline_state": 1,
        "device_type_code": "009",
        "status_list": status,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


# --- unit_from_appliance decode ---


def test_decode_basic_fields():
    unit = unit_from_appliance(_appliance())
    assert unit.puid == "puid-1"
    assert unit.name == "Master Bedroom AC"
    assert unit.room == "Master Bedroom"
    assert unit.offline_state == 1  # raw passthrough; not an availability signal
    assert unit.power is False
    assert unit.mode == "cool"  # t_work_mode 2
    assert unit.target_temp == 70
    assert unit.current_temp == 73
    assert unit.fan == "auto"  # t_fan_speed 0


def test_decode_humidity_sentinel_becomes_none():
    assert unit_from_appliance(_appliance()).humidity is None
    ok = unit_from_appliance(_appliance(status={"f_humidity": 45}))
    assert ok.humidity == 45


def test_decode_offline_state_passthrough():
    # We store the raw flag but never interpret it (it reads 1 on online units).
    assert unit_from_appliance(_appliance(offline_state=0)).offline_state == 0
    assert unit_from_appliance(_appliance(offline_state=1)).offline_state == 1


def test_decode_modes_and_fan_lookup():
    assert unit_from_appliance(_appliance(status={"t_work_mode": 1})).mode == "heat"
    assert unit_from_appliance(_appliance(status={"t_work_mode": 4})).mode == "auto"
    assert unit_from_appliance(_appliance(status={"t_fan_speed": 9})).fan == "high"
    # unknown raw value degrades to "unknown", never crashes
    assert unit_from_appliance(_appliance(status={"t_work_mode": 99})).mode == "unknown"


def test_decode_faults_collect_nonzero_flags():
    unit = unit_from_appliance(_appliance(status={"f_e_waterfull": 1, "f_e_inwifi": 1}))
    assert unit.faults == ["inwifi", "waterfull"]  # sorted
    assert unit_from_appliance(_appliance()).faults == []


def test_decode_power_on():
    assert unit_from_appliance(_appliance(status={"t_power": 1})).power is True


# --- build_control_properties ---


def test_build_power():
    assert build_control_properties(power=True) == {"t_power": "1"}
    assert build_control_properties(power=False) == {"t_power": "0"}


def test_build_mode_and_fan():
    assert build_control_properties(mode="cool") == {"t_work_mode": "2"}
    assert build_control_properties(fan="low") == {"t_fan_speed": "5"}


def test_build_temp_in_range():
    assert build_control_properties(temp=72) == {"t_temp": "72"}


def test_build_temp_out_of_range_raises():
    with pytest.raises(ValueError):
        build_control_properties(temp=95)
    with pytest.raises(ValueError):
        build_control_properties(temp=50)


def test_build_unknown_mode_and_fan_raise():
    with pytest.raises(ValueError):
        build_control_properties(mode="turbo")
    with pytest.raises(ValueError):
        build_control_properties(fan="ludicrous")


def test_build_empty_raises():
    with pytest.raises(ValueError):
        build_control_properties()


def test_build_combines_multiple():
    assert build_control_properties(power=True, mode="heat", temp=68, fan="high") == {
        "t_power": "1",
        "t_work_mode": "1",
        "t_temp": "68",
        "t_fan_speed": "9",
    }


# --- get_units / set_unit (library patched at the boundary) ---


def test_get_units_filters_to_air_conditioners():
    ac = _appliance()
    other = _appliance(puid="fridge", device_type_code="026")
    fake_api = SimpleNamespace(get_appliances=AsyncMock(return_value=[ac, other]))

    with patch("climate.hisense.client.SandboxConnectLifeApi", return_value=fake_api) as mk:
        units = asyncio.run(get_units("user", "pass"))

    mk.assert_called_once_with("user", "pass")
    assert [u.puid for u in units] == ["puid-1"]


def test_get_units_wraps_errors():
    fake_api = SimpleNamespace(get_appliances=AsyncMock(side_effect=RuntimeError("boom")))
    with patch("climate.hisense.client.SandboxConnectLifeApi", return_value=fake_api):
        with pytest.raises(HisenseError):
            asyncio.run(get_units("user", "pass"))


def test_set_unit_calls_update_appliance():
    fake_api = SimpleNamespace(update_appliance=AsyncMock())
    with patch("climate.hisense.client.SandboxConnectLifeApi", return_value=fake_api):
        asyncio.run(set_unit("user", "pass", "puid-1", {"t_temp": "72"}))
    fake_api.update_appliance.assert_awaited_once_with("puid-1", {"t_temp": "72"})


def test_set_unit_wraps_errors():
    fake_api = SimpleNamespace(update_appliance=AsyncMock(side_effect=RuntimeError("nope")))
    with patch("climate.hisense.client.SandboxConnectLifeApi", return_value=fake_api):
        with pytest.raises(HisenseError):
            asyncio.run(set_unit("user", "pass", "puid-1", {"t_temp": "72"}))
