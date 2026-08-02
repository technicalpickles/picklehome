"""Async client for the VicoHome cloud API: device state and bird event log."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

from birdfeeder.vicohome.auth import API_BASE_URL_TEMPLATE, login as auth_login


@dataclass
class Device:
    serial_number: str
    device_name: str
    model_no: str
    location_name: str
    home_name: str
    ip: str
    mac_address: str
    battery_level: int
    is_charging: bool
    signal_strength: int
    wifi_channel: int
    online: bool
    firmware_id: str


@dataclass
class BirdEvent:
    trace_id: str
    timestamp: datetime
    duration_seconds: float
    device_name: str
    serial_number: str
    species_name: str | None
    species_latin: str | None
    confidence: int | None
    image_url: str
    video_url: str


async def connect(email: str, password: str, region: str) -> aiohttp.ClientSession:
    """Create an authenticated session for the VicoHome API.

    Caller must close the returned session.
    """
    base_url = API_BASE_URL_TEMPLATE.format(region=region)
    session = aiohttp.ClientSession(
        base_url=base_url,
        trust_env=True,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    token = await auth_login(session, email, password)
    session.headers["Authorization"] = token
    return session


def _parse_device(raw: dict) -> Device:
    return Device(
        serial_number=raw["serialNumber"],
        device_name=raw.get("deviceName") or "",
        model_no=raw.get("modelNo") or "",
        location_name=raw.get("locationName") or "",
        home_name=raw.get("homeName") or "",
        ip=raw.get("ip") or "",
        mac_address=raw.get("macAddress") or "",
        battery_level=raw.get("batteryLevel") or 0,
        is_charging=bool(raw.get("isCharging")),
        signal_strength=raw.get("signalStrength") or 0,
        wifi_channel=raw.get("wifiChannel") or 0,
        online=bool(raw.get("online")),
        firmware_id=raw.get("firmwareId") or "",
    )


async def get_devices(session: aiohttp.ClientSession) -> list[Device]:
    """Fetch all devices on the account: battery, WiFi signal, online state."""
    async with session.post("/device/listuserdevices", json={}) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    if data.get("result") != 0:
        raise RuntimeError(f"VicoHome device list failed: {data.get('msg', 'unknown error')}")
    return [_parse_device(d) for d in data.get("data", {}).get("list", [])]


def _parse_event(raw: dict) -> BirdEvent:
    # The top-level "birdName" field is actually the Latin/scientific name.
    # The common species name and per-event confidence live in subcategoryInfoList,
    # which is empty when the AI detected "a bird" but couldn't identify the species.
    subcategory = raw.get("subcategoryInfoList") or []
    species = subcategory[0] if subcategory else {}
    return BirdEvent(
        trace_id=raw["traceId"],
        timestamp=datetime.fromtimestamp(raw["timestamp"], tz=timezone.utc),
        duration_seconds=raw.get("period") or 0.0,
        device_name=raw.get("deviceName") or "",
        serial_number=raw.get("serialNumber") or "",
        species_name=species.get("objectName"),
        species_latin=species.get("birdStdName") or raw.get("birdName"),
        confidence=species.get("confidence"),
        image_url=raw.get("imageUrl") or "",
        video_url=raw.get("videoUrl") or "",
    )


async def get_events(
    session: aiohttp.ClientSession,
    start: datetime,
    end: datetime,
    country_no: str = "US",
    language: str = "en",
) -> list[BirdEvent]:
    """Fetch bird events in [start, end)."""
    payload = {
        "startTimestamp": str(int(start.timestamp())),
        "endTimestamp": str(int(end.timestamp())),
        "language": language,
        "countryNo": country_no,
    }
    async with session.post("/library/newselectlibrary", json=payload) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    if data.get("result") != 0:
        raise RuntimeError(f"VicoHome events fetch failed: {data.get('msg', 'unknown error')}")
    return [_parse_event(e) for e in data.get("data", {}).get("list", [])]
