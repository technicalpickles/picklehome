import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from birdfeeder.vicohome.client import (
    Device,
    BirdEvent,
    get_devices,
    get_events,
)


def _mock_session(response_body: dict):
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = AsyncMock(return_value=response_body)
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_response)
    return mock_session


# Trimmed but structurally faithful to a real /device/listuserdevices response.
DEVICE_LIST_RESPONSE = {
    "result": 0,
    "msg": "Success",
    "data": {
        "list": [
            {
                "serialNumber": "e543324f7e596ac176836c8781177558",
                "deviceName": "Smart Camera",
                "modelNo": "CG625-BD2-ST1BQJ",
                "locationName": "Front door",
                "homeName": "My House",
                "ip": "192.168.1.86",
                "macAddress": "14:92:f9:93:fe:78",
                "batteryLevel": 55,
                "isCharging": 1,
                "signalStrength": -65,
                "wifiChannel": 6,
                "online": 1,
                "firmwareId": "1.18.40",
            }
        ],
        "total": None,
        "page": None,
    },
}

# Trimmed but structurally faithful to a real /library/newselectlibrary response.
EVENTS_RESPONSE = {
    "result": 0,
    "msg": "Success",
    "data": {
        "list": [
            {
                "traceId": "056692651785676269pvftb1eSek4",
                "timestamp": 1785676267,
                "period": 10.037,
                "deviceName": "Smart Camera",
                "serialNumber": "e543324f7e596ac176836c8781177558",
                "birdName": "Cardinalis cardinalis",
                "imageUrl": "https://example.com/image.jpg",
                "videoUrl": "https://example.com/video.m3u8",
                "deviceAiEventList": ["bird"],
                "subcategoryInfoList": [
                    {
                        "objectType": "bird",
                        "objectName": "Northern Cardinal",
                        "birdStdName": "Cardinalis cardinalis",
                        "confidence": 87,
                    }
                ],
            },
            {
                "traceId": "0566926517856823541THZWRoIguT",
                "timestamp": 1785682352,
                "period": 10.037,
                "deviceName": "Smart Camera",
                "serialNumber": "e543324f7e596ac176836c8781177558",
                "birdName": None,
                "imageUrl": "https://example.com/image2.jpg",
                "videoUrl": "https://example.com/video2.m3u8",
                "deviceAiEventList": ["bird"],
                "subcategoryInfoList": [],
            },
        ],
        "total": None,
        "page": None,
    },
}


def test_get_devices_parses_response():
    session = _mock_session(DEVICE_LIST_RESPONSE)

    async def _run():
        devices = await get_devices(session)
        assert len(devices) == 1
        device = devices[0]
        assert device == Device(
            serial_number="e543324f7e596ac176836c8781177558",
            device_name="Smart Camera",
            model_no="CG625-BD2-ST1BQJ",
            location_name="Front door",
            home_name="My House",
            ip="192.168.1.86",
            mac_address="14:92:f9:93:fe:78",
            battery_level=55,
            is_charging=True,
            signal_strength=-65,
            wifi_channel=6,
            online=True,
            firmware_id="1.18.40",
        )

    asyncio.run(_run())


def test_get_devices_raises_on_failure():
    session = _mock_session({"result": -1, "msg": "token expired", "data": None})

    async def _run():
        with pytest.raises(RuntimeError, match="token expired"):
            await get_devices(session)

    asyncio.run(_run())


def test_get_events_parses_identified_bird():
    session = _mock_session(EVENTS_RESPONSE)

    async def _run():
        events = await get_events(
            session,
            start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        assert len(events) == 2

        identified = events[0]
        assert identified == BirdEvent(
            trace_id="056692651785676269pvftb1eSek4",
            timestamp=datetime.fromtimestamp(1785676267, tz=timezone.utc),
            duration_seconds=10.037,
            device_name="Smart Camera",
            serial_number="e543324f7e596ac176836c8781177558",
            species_name="Northern Cardinal",
            species_latin="Cardinalis cardinalis",
            confidence=87,
            image_url="https://example.com/image.jpg",
            video_url="https://example.com/video.m3u8",
        )

    asyncio.run(_run())


def test_get_events_parses_unidentified_bird():
    session = _mock_session(EVENTS_RESPONSE)

    async def _run():
        events = await get_events(
            session,
            start=datetime(2026, 8, 1, tzinfo=timezone.utc),
            end=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        unidentified = events[1]
        assert unidentified.species_name is None
        assert unidentified.species_latin is None
        assert unidentified.confidence is None

    asyncio.run(_run())


def test_get_events_sends_epoch_timestamps():
    session = _mock_session(EVENTS_RESPONSE)
    start = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)

    async def _run():
        await get_events(session, start=start, end=end, country_no="US", language="en")
        session.post.assert_called_once_with(
            "/library/newselectlibrary",
            json={
                "startTimestamp": str(int(start.timestamp())),
                "endTimestamp": str(int(end.timestamp())),
                "language": "en",
                "countryNo": "US",
            },
        )

    asyncio.run(_run())


def test_get_events_raises_on_failure():
    session = _mock_session({"result": -1, "msg": "token expired", "data": None})

    async def _run():
        with pytest.raises(RuntimeError, match="token expired"):
            await get_events(
                session,
                start=datetime(2026, 8, 1, tzinfo=timezone.utc),
                end=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )

    asyncio.run(_run())
