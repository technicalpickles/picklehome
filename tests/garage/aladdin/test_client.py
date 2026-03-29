import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from garage.aladdin.client import (
    GarageDoor,
    DOOR_STATUS,
    LINK_STATUS,
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
    )
    assert door.device_id == "dev1"
    assert door.door_index == 0
    assert door.name == "Garage"
    assert door.status == "closed"
    assert door.link_status == "connected"
    assert door.battery_level == 95


def test_door_status_mapping():
    assert DOOR_STATUS[1] == "open"
    assert DOOR_STATUS[4] == "closed"
    assert DOOR_STATUS[0] == "unknown"
    assert DOOR_STATUS[7] == "not_configured"


def test_link_status_mapping():
    assert LINK_STATUS[0] == "unknown"
    assert LINK_STATUS[3] == "connected"
    assert LINK_STATUS[2] == "paired"


def test_connect_exits_without_tokens(monkeypatch):
    monkeypatch.setattr("garage.aladdin.client.load_tokens", lambda: None)
    with pytest.raises(SystemExit):
        asyncio.run(connect())


def test_get_doors_parses_response():
    api_response = {
        "devices": [
            {
                "id": "device123",
                "name": "My Opener",
                "doors": [
                    {
                        "door_index": 0,
                        "name": "Main Garage",
                        "status": 4,
                        "link_status": 3,
                        "battery_level": 88,
                    },
                    {
                        "door_index": 1,
                        "status": 1,
                        "link_status": 2,
                        "battery_level": 50,
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

        assert doors[0].device_id == "device123"
        assert doors[0].door_index == 0
        assert doors[0].name == "Main Garage"
        assert doors[0].status == "closed"
        assert doors[0].link_status == "connected"
        assert doors[0].battery_level == 88

        # Second door has no name, should fall back to device name
        assert doors[1].name == "My Opener"
        assert doors[1].status == "open"
        assert doors[1].link_status == "paired"

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
