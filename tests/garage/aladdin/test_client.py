import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from garage.aladdin.client import (
    GarageDoor,
    DOOR_STATUS,
    LINK_STATUS,
    DEVICE_STATUS,
    FAULT_STATUS,
    _format_mac,
    connect,
    get_doors,
    open_door,
    close_door,
)


def test_garage_door_dataclass():
    door = GarageDoor(
        device_id="dev1",
        door_index=0,
        name="Garage",
        status="closed",
        link_status="connected",
        battery_level=95,
        fault="none",
        ble_strength=0,
        is_enabled=True,
        updated_at="123456",
        mac="F0:AD:4E:17:08:5C",
        rssi=-65,
        device_status="connected",
        software_version="6.20.00",
        model="GENIE",
        ssid="picklehome-iot",
    )
    assert door.device_id == "dev1"
    assert door.name == "Garage"
    assert door.status == "closed"
    assert door.fault == "none"
    assert door.rssi == -65
    assert door.mac == "F0:AD:4E:17:08:5C"
    assert door.ssid == "picklehome-iot"


def test_door_status_mapping():
    assert DOOR_STATUS[1] == "open"
    assert DOOR_STATUS[4] == "closed"
    assert DOOR_STATUS[0] == "unknown"
    assert DOOR_STATUS[7] == "not_configured"


def test_link_status_mapping():
    assert LINK_STATUS[0] == "unknown"
    assert LINK_STATUS[3] == "connected"
    assert LINK_STATUS[2] == "paired"


def test_device_status_mapping():
    assert DEVICE_STATUS[0] == "offline"
    assert DEVICE_STATUS[1] == "connected"


def test_format_mac_valid():
    assert _format_mac("F0AD4E17085C") == "F0:AD:4E:17:08:5C"
    assert _format_mac("aabbccddeeff") == "AA:BB:CC:DD:EE:FF"


def test_format_mac_passthrough():
    assert _format_mac("not-a-mac") == "not-a-mac"
    assert _format_mac("short") == "short"


def test_fault_status_mapping():
    assert FAULT_STATUS[0] == "none"
    assert FAULT_STATUS[1] == "ul_lockout"
    assert FAULT_STATUS[4] == "will_not_move"


def test_connect_exits_without_tokens(monkeypatch):
    monkeypatch.setattr("garage.aladdin.client.load_tokens", lambda: None)
    with pytest.raises(SystemExit):
        asyncio.run(connect())


def test_get_doors_parses_response():
    api_response = {
        "devices": [
            {
                "id": "AABBCCDDEEFF",
                "name": "My Opener",
                "status": 1,
                "rssi": -55,
                "ssid": "my-iot-network",
                "software_version": "6.20.00",
                "vendor": "GENIE",
                "doors": [
                    {
                        "door_index": 0,
                        "name": "Main Garage",
                        "status": 4,
                        "link_status": 3,
                        "battery_level": 88,
                        "fault": 0,
                        "ble_strength": 10,
                        "is_enabled": True,
                        "updated_at": "123456",
                    },
                    {
                        "door_index": 1,
                        "status": 1,
                        "link_status": 2,
                        "battery_level": 50,
                        "fault": 1,
                        "ble_strength": 0,
                        "is_enabled": False,
                        "updated_at": "789012",
                    },
                ],
            }
        ]
    }

    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = AsyncMock(return_value=api_response)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)

    async def _run():
        doors = await get_doors(mock_session)
        assert len(doors) == 2

        assert doors[0].device_id == "AABBCCDDEEFF"
        assert doors[0].door_index == 0
        assert doors[0].name == "Main Garage"
        assert doors[0].status == "closed"
        assert doors[0].link_status == "connected"
        assert doors[0].battery_level == 88
        assert doors[0].fault == "none"
        assert doors[0].mac == "AA:BB:CC:DD:EE:FF"
        assert doors[0].rssi == -55
        assert doors[0].ssid == "my-iot-network"
        assert doors[0].device_status == "connected"
        assert doors[0].is_enabled is True

        # Second door has no name, should fall back to device name
        assert doors[1].name == "My Opener"
        assert doors[1].status == "open"
        assert doors[1].link_status == "paired"
        assert doors[1].fault == "ul_lockout"
        assert doors[1].is_enabled is False

    asyncio.run(_run())


def test_get_doors_empty_response():
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = AsyncMock(return_value={"devices": []})
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)

    async def _run():
        doors = await get_doors(mock_session)
        assert doors == []

    asyncio.run(_run())


def test_open_door_returns_success():
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)

    async def _run():
        result = await open_door(mock_session, "dev1", 0)
        assert result is True

    asyncio.run(_run())


def test_close_door_returns_success():
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)

    async def _run():
        result = await close_door(mock_session, "dev1", 0)
        assert result is True

    asyncio.run(_run())
