import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from aiohttp import ClientSession
from aioambient import OpenAPI
from aioambient.errors import RequestError

FETCH_TIMEOUT = 10        # seconds — HTTP request timeout
MAX_DATA_AGE_MINUTES = 30 # readings older than this are treated as stale
TEMP_MIN_PLAUSIBLE = -20.0  # °F
TEMP_MAX_PLAUSIBLE = 120.0  # °F

DEFAULT_WEATHER_PATH = Path(__file__).parent.parent / "config" / "weather.yaml"


class StationError(Exception):
    """A station fetch failed for a diagnosable reason."""
    def __init__(self, mac: str, reason: str):
        self.mac = mac
        self.reason = reason
        super().__init__(f"{mac}: {reason}")


def is_temp_plausible(temp: float) -> bool:
    """Return True if temp is within a physically reasonable range for this region."""
    return TEMP_MIN_PLAUSIBLE <= temp <= TEMP_MAX_PLAUSIBLE


def is_data_fresh(last_data: dict, max_age_minutes: int = MAX_DATA_AGE_MINUTES) -> bool:
    """Return True if lastData timestamp is recent enough to trust."""
    ts = last_data.get("dateutc")
    if ts is None:
        return False
    age_minutes = (time.time() - ts / 1000) / 60
    return age_minutes <= max_age_minutes


def get_data_age_minutes(last_data: dict) -> float | None:
    """Return age of lastData in minutes, or None if no timestamp."""
    ts = last_data.get("dateutc")
    if ts is None:
        return None
    return (time.time() - ts / 1000) / 60


async def _fetch_temp(mac: str) -> tuple[str, float, float]:
    """Fetch temp from a single station.

    Returns (mac, tempf, age_minutes) on success.
    Raises StationError with a diagnostic message on any failure.
    """
    # aiohttp defaults to trust_env=False, ignoring HTTP_PROXY/HTTPS_PROXY.
    # The Claude Code sandbox routes traffic through a local proxy for domain
    # allowlisting, so we must opt in for requests to reach external APIs.
    async with ClientSession(trust_env=True) as session:
        try:
            api = OpenAPI(session=session)
            data = await asyncio.wait_for(api.get_device_details(mac), timeout=FETCH_TIMEOUT)
        except asyncio.TimeoutError:
            raise StationError(mac, f"request timed out ({FETCH_TIMEOUT}s)")
        except (RequestError, OSError) as e:
            raise StationError(mac, f"network error: {e}") from e

    last_data = data.get("lastData", {})
    temp = last_data.get("tempf")
    if temp is None:
        raise StationError(mac, "no temperature in response")
    if not is_temp_plausible(temp):
        raise StationError(mac, f"implausible reading {temp}°F")
    age = get_data_age_minutes(last_data)
    if age is None:
        raise StationError(mac, "no timestamp in response")
    if not is_data_fresh(last_data):
        raise StationError(mac, f"data is {age:.0f} min stale (max {MAX_DATA_AGE_MINUTES})")
    return (mac, temp, age)


async def _fetch_all_temps(macs: list[str]) -> list[tuple[str, float, float] | StationError]:
    """Fetch temps from all stations concurrently.

    Uses return_exceptions=True so one station's failure doesn't cancel the others.
    Each result is either a success tuple or a StationError.
    """
    return await asyncio.gather(*[_fetch_temp(mac) for mac in macs], return_exceptions=True)


def get_outdoor_temp_from_stations(macs: list[str]) -> tuple[str, float, float] | None:
    """Return (mac, tempf, age_minutes) from first valid station, or None.

    Prints per-station diagnostics to stderr when stations fail,
    so the caller's summary message has context.
    """
    if not macs:
        return None
    results = asyncio.run(_fetch_all_temps(macs))

    for r in results:
        if isinstance(r, tuple):
            return r

    # All stations failed — print why for each one
    for r in results:
        if isinstance(r, StationError):
            print(f"  {r.mac}: {r.reason}", file=sys.stderr)
        elif isinstance(r, Exception):
            # Unexpected exception type — don't swallow it
            print(f"  unexpected error: {r}", file=sys.stderr)
    return None


async def _discover(lat: float, lon: float, radius_miles: float) -> list[dict[str, Any]]:
    async with ClientSession(trust_env=True) as session:
        try:
            api = OpenAPI(session=session)
            stations = await asyncio.wait_for(
                api.get_devices_by_location(lat, lon, radius=radius_miles),
                timeout=FETCH_TIMEOUT,
            )
            return [s for s in stations if not s.get("info", {}).get("indoor", False)]
        except (RequestError, asyncio.TimeoutError) as e:
            raise RuntimeError(f"Failed to discover stations: {e}") from e


def discover_stations_sync(lat: float, lon: float, radius_miles: float = 1.0) -> list[dict[str, Any]]:
    return asyncio.run(_discover(lat, lon, radius_miles))


def load_weather_config(path: Path = DEFAULT_WEATHER_PATH) -> dict:
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except OSError as e:
        print(f"Cannot read weather config: {path}: {e}")
        sys.exit(1)


def get_configured_macs(config: dict) -> list[str]:
    env_macs = os.environ.get("AMBIENT_STATION_MACS", "")
    if env_macs:
        return [m.strip() for m in env_macs.split(",") if m.strip()]
    return [s["mac"] for s in config.get("stations", []) if "mac" in s]
