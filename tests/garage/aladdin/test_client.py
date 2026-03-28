import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from garage.aladdin.client import get_doors, open_door, close_door, connect


def test_get_doors_returns_door_list():
    fake_door = MagicMock()
    fake_door.name = "Garage Door"
    fake_door.status = "closed"
    fake_door.battery_level = 95
    fake_door.link_status = "connected"
    fake_door.device_id = "dev1"
    fake_door.door_number = 1

    mock_client = MagicMock()
    mock_client.get_doors = AsyncMock(return_value=[fake_door])

    async def _run():
        doors = await get_doors(mock_client)
        assert len(doors) == 1
        assert doors[0].name == "Garage Door"

    asyncio.run(_run())


def test_open_door_delegates_to_client():
    mock_client = MagicMock()
    mock_client.open_door = AsyncMock(return_value=True)

    async def _run():
        result = await open_door(mock_client, "dev1", 1)
        assert result is True
        mock_client.open_door.assert_awaited_once_with("dev1", 1)

    asyncio.run(_run())


def test_close_door_delegates_to_client():
    mock_client = MagicMock()
    mock_client.close_door = AsyncMock(return_value=True)

    async def _run():
        result = await close_door(mock_client, "dev1", 1)
        assert result is True
        mock_client.close_door.assert_awaited_once_with("dev1", 1)

    asyncio.run(_run())


def test_connect_exits_without_tokens(monkeypatch):
    monkeypatch.setattr("garage.aladdin.client.load_tokens", lambda: None)
    with pytest.raises(SystemExit):
        asyncio.run(connect())
