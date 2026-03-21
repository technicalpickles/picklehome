"""Tests for climate.blueair.client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from climate.blueair.client import (
    SETTABLE_PROPERTIES,
    _clean_value,
    discover_devices,
    extract_device_status,
    get_device_status,
    parse_set_value,
    set_device_property,
)


# ---------------------------------------------------------------------------
# _clean_value
# ---------------------------------------------------------------------------


def test_clean_value_none_passthrough():
    assert _clean_value(None) is None


def test_clean_value_normal_values():
    assert _clean_value(42) == 42
    assert _clean_value("hello") == "hello"
    assert _clean_value(True) is True


def test_clean_value_not_implemented_becomes_none():
    assert _clean_value(NotImplemented) is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_device(uuid="uuid-1", name="Bedroom", sku="110092", **overrides):
    """Build a MagicMock that quacks like a refreshed DeviceAws."""
    device = MagicMock()
    device.uuid = uuid
    device.name = name
    device.sku = sku
    device.firmware = "1.2.3"
    device.pm1 = 2
    device.pm2_5 = 5
    device.pm10 = 8
    device.total_voc = NotImplemented  # simulate unsupported field
    device.voc = NotImplemented
    device.temperature = 22
    device.humidity = 45
    device.fan_speed = 50
    device.fan_auto_mode = True
    device.standby = False
    device.night_mode = False
    device.germ_shield = True
    device.brightness = 3
    device.child_lock = False
    device.filter_usage_percentage = 30
    device.wifi_working = True
    device.model = MagicMock()
    device.model.value = "311i"

    device.refresh = AsyncMock()

    for key, val in overrides.items():
        setattr(device, key, val)

    return device


# ---------------------------------------------------------------------------
# extract_device_status
# ---------------------------------------------------------------------------


def test_extract_device_status_basic():
    device = _make_fake_device()
    status = extract_device_status(device)

    assert status["name"] == "Bedroom"
    assert status["uuid"] == "uuid-1"
    assert status["pm2_5"] == 5
    assert status["model"] == "311i"


def test_extract_device_status_not_implemented_cleaned():
    device = _make_fake_device()
    status = extract_device_status(device)

    # total_voc and voc were set to NotImplemented
    assert status["total_voc"] is None
    assert status["voc"] is None


def test_extract_device_status_all_keys_present():
    device = _make_fake_device()
    status = extract_device_status(device)

    expected_keys = {
        "name", "uuid", "model", "sku", "firmware",
        "pm1", "pm2_5", "pm10", "total_voc", "voc",
        "temperature", "humidity",
        "fan_speed", "fan_auto_mode", "standby", "night_mode",
        "germ_shield", "brightness", "child_lock",
        "filter_usage_percentage", "wifi_working",
    }
    assert set(status.keys()) == expected_keys


# ---------------------------------------------------------------------------
# discover_devices
# ---------------------------------------------------------------------------


def test_discover_devices_calls_api():
    fake_api = MagicMock()
    fake_devices = [_make_fake_device()]

    async def _run():
        with patch(
            "climate.blueair.client.get_aws_devices",
            new_callable=AsyncMock,
            return_value=(fake_api, fake_devices),
        ) as mock_get:
            devices, api = await discover_devices("user", "pass", "us")
        mock_get.assert_awaited_once_with("user", "pass", "us")
        assert devices == fake_devices
        assert api is fake_api

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# get_device_status
# ---------------------------------------------------------------------------


def test_get_device_status_filters_to_managed():
    managed = [("Bedroom", "uuid-1")]
    dev1 = _make_fake_device(uuid="uuid-1", name="Bedroom")
    dev2 = _make_fake_device(uuid="uuid-2", name="Kitchen")
    fake_api = MagicMock()

    async def _run():
        with patch(
            "climate.blueair.client.get_aws_devices",
            new_callable=AsyncMock,
            return_value=(fake_api, [dev1, dev2]),
        ):
            statuses, api = await get_device_status("u", "p", "us", managed)

        assert len(statuses) == 1
        assert statuses[0]["uuid"] == "uuid-1"
        # Only the managed device should have been refreshed
        dev1.refresh.assert_awaited_once()
        dev2.refresh.assert_not_awaited()

    asyncio.run(_run())


def test_get_device_status_empty_when_no_match():
    managed = [("Ghost", "uuid-999")]
    dev1 = _make_fake_device(uuid="uuid-1")
    fake_api = MagicMock()

    async def _run():
        with patch(
            "climate.blueair.client.get_aws_devices",
            new_callable=AsyncMock,
            return_value=(fake_api, [dev1]),
        ):
            statuses, api = await get_device_status("u", "p", "us", managed)

        assert statuses == []
        dev1.refresh.assert_not_awaited()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# parse_set_value
# ---------------------------------------------------------------------------


def test_parse_set_value_bool_on():
    assert parse_set_value("on", "bool") is True
    assert parse_set_value("ON", "bool") is True
    assert parse_set_value("true", "bool") is True


def test_parse_set_value_bool_off():
    assert parse_set_value("off", "bool") is False
    assert parse_set_value("OFF", "bool") is False
    assert parse_set_value("false", "bool") is False


def test_parse_set_value_bool_invalid():
    with pytest.raises(ValueError, match="Expected on/off"):
        parse_set_value("maybe", "bool")


def test_parse_set_value_int():
    assert parse_set_value("50", "int") == 50
    assert parse_set_value("0", "int") == 0


def test_parse_set_value_int_invalid():
    with pytest.raises(ValueError):
        parse_set_value("fast", "int")


# ---------------------------------------------------------------------------
# set_device_property
# ---------------------------------------------------------------------------


def test_set_device_property_all_managed():
    dev1 = _make_fake_device(uuid="uuid-1", name="Bedroom")
    dev1.set_night_mode = AsyncMock()
    dev2 = _make_fake_device(uuid="uuid-2", name="Media Room")
    dev2.set_night_mode = AsyncMock()
    fake_api = MagicMock()
    fake_api.cleanup_client_session = AsyncMock()
    managed = [("Bedroom", "uuid-1"), ("Media Room", "uuid-2")]

    async def _run():
        with patch(
            "climate.blueair.client.get_aws_devices",
            new_callable=AsyncMock,
            return_value=(fake_api, [dev1, dev2]),
        ):
            msgs = await set_device_property("u", "p", "us", managed, "night-mode", "on")
        assert len(msgs) == 2
        dev1.set_night_mode.assert_awaited_once_with(True)
        dev2.set_night_mode.assert_awaited_once_with(True)

    asyncio.run(_run())


def test_set_device_property_with_device_filter():
    dev1 = _make_fake_device(uuid="uuid-1", name="Bedroom")
    dev1.set_fan_speed = AsyncMock()
    dev2 = _make_fake_device(uuid="uuid-2", name="Media Room")
    dev2.set_fan_speed = AsyncMock()
    fake_api = MagicMock()
    fake_api.cleanup_client_session = AsyncMock()
    managed = [("Bedroom", "uuid-1"), ("Media Room", "uuid-2")]

    async def _run():
        with patch(
            "climate.blueair.client.get_aws_devices",
            new_callable=AsyncMock,
            return_value=(fake_api, [dev1, dev2]),
        ):
            msgs = await set_device_property("u", "p", "us", managed, "fan-speed", "75", device_filter="Bedroom")
        assert len(msgs) == 1
        assert "Bedroom" in msgs[0]
        dev1.set_fan_speed.assert_awaited_once_with(75)
        dev2.set_fan_speed.assert_not_awaited()

    asyncio.run(_run())


def test_set_device_property_unknown_property():
    async def _run():
        with pytest.raises(ValueError, match="Unknown property"):
            await set_device_property("u", "p", "us", [], "turbo", "on")

    asyncio.run(_run())
