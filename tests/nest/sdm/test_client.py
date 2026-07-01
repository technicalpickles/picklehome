"""Tests for nest.sdm.client trait parsing (pure logic, no network)."""

from nest.sdm.client import parse_device, parse_structure


def test_parse_structure_uses_custom_name():
    raw = {
        "name": "enterprises/proj/structures/abc123",
        "traits": {"sdm.structures.traits.Info": {"customName": "Atlanta"}},
    }
    structure = parse_structure(raw)
    assert structure.custom_name == "Atlanta"
    assert structure.id == "abc123"


def test_parse_structure_falls_back_to_id_when_unnamed():
    raw = {"name": "enterprises/proj/structures/abc123", "traits": {}}
    assert parse_structure(raw).custom_name == "abc123"


def test_parse_thermostat_device():
    raw = {
        "name": "enterprises/proj/devices/dev1",
        "type": "sdm.devices.types.THERMOSTAT",
        "parentRelations": [{"parent": "enterprises/proj/structures/s1", "displayName": "Atlanta"}],
        "traits": {
            "sdm.devices.traits.Info": {"customName": "Upstairs"},
            "sdm.devices.traits.Connectivity": {"status": "ONLINE"},
            "sdm.devices.traits.ThermostatMode": {"mode": "HEAT"},
            "sdm.devices.traits.Temperature": {"ambientTemperatureCelsius": 21.5},
            "sdm.devices.traits.ThermostatTemperatureSetpoint": {"heatCelsius": 22.0},
            "sdm.devices.traits.Humidity": {"ambientHumidityPercent": 40},
        },
    }
    device = parse_device(raw)
    assert device.device_type == "THERMOSTAT"
    assert device.custom_name == "Upstairs"
    assert device.structure_id == "s1"
    assert device.connectivity == "ONLINE"
    assert device.mode == "HEAT"
    assert device.ambient_temperature_c == 21.5
    assert device.setpoint_heat_c == 22.0
    assert device.setpoint_cool_c is None
    assert device.humidity_percent == 40
    assert device.has_live_stream is False


def test_parse_camera_device():
    raw = {
        "name": "enterprises/proj/devices/dev2",
        "type": "sdm.devices.types.CAMERA",
        "parentRelations": [{"parent": "enterprises/proj/structures/s2"}],
        "traits": {
            "sdm.devices.traits.Info": {"customName": "Front Door"},
            "sdm.devices.traits.CameraLiveStream": {},
        },
    }
    device = parse_device(raw)
    assert device.device_type == "CAMERA"
    assert device.structure_id == "s2"
    assert device.has_live_stream is True
    assert device.mode is None


def test_parse_device_without_custom_name_falls_back_to_id():
    raw = {
        "name": "enterprises/proj/devices/dev3",
        "type": "sdm.devices.types.CAMERA",
        "parentRelations": [],
        "traits": {},
    }
    device = parse_device(raw)
    assert device.custom_name == "dev3"
    assert device.structure_id == ""


def test_parse_device_room_parented_structure_id():
    """Real SDM responses parent devices through a room, not the structure directly:
    enterprises/{p}/structures/{sid}/rooms/{rid} -- the structure id is not the last
    path segment. Regression test for a bug where rsplit grabbed the room id instead."""
    raw = {
        "name": "enterprises/proj/devices/dev4",
        "type": "sdm.devices.types.CAMERA",
        "parentRelations": [
            {"parent": "enterprises/proj/structures/s4/rooms/r4", "displayName": "Garage"}
        ],
        "traits": {"sdm.devices.traits.Info": {"customName": ""}},
    }
    device = parse_device(raw)
    assert device.structure_id == "s4"


def test_parse_device_empty_custom_name_falls_back_to_room_name():
    raw = {
        "name": "enterprises/proj/devices/dev5",
        "type": "sdm.devices.types.CAMERA",
        "parentRelations": [
            {"parent": "enterprises/proj/structures/s5/rooms/r5", "displayName": "Front Door"}
        ],
        "traits": {"sdm.devices.traits.Info": {"customName": ""}},
    }
    device = parse_device(raw)
    assert device.custom_name == "Front Door"


def test_parse_doorbell_device_has_live_stream():
    """DOORBELL is a distinct SDM type from CAMERA but carries the same
    CameraLiveStream trait plus DoorbellChime -- has_live_stream must key off
    trait presence, not device_type, or doorbells silently show no stream."""
    raw = {
        "name": "enterprises/proj/devices/dev6",
        "type": "sdm.devices.types.DOORBELL",
        "parentRelations": [
            {"parent": "enterprises/proj/structures/s6/rooms/r6", "displayName": "Front Door"}
        ],
        "traits": {
            "sdm.devices.traits.CameraLiveStream": {},
            "sdm.devices.traits.DoorbellChime": {},
        },
    }
    device = parse_device(raw)
    assert device.device_type == "DOORBELL"
    assert device.has_live_stream is True
