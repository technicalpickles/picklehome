import asyncio
import os
from dataclasses import dataclass

from aiohttp import ClientSession, ClientTimeout

FETCH_TIMEOUT = 10  # seconds

BASE_URL = "https://pollen.googleapis.com/v1/forecast:lookup"

# UPI (Universal Pollen Index) 0-5 scale
UPI_CATEGORIES = {
    0: "None",
    1: "Very Low",
    2: "Low",
    3: "Moderate",
    4: "High",
    5: "Very High",
}


class PollenError(Exception):
    """Pollen fetch failed for a diagnosable reason."""


@dataclass
class PollenTypeReading:
    code: str        # TREE, GRASS, WEED
    display_name: str
    in_season: bool
    upi: int | None  # Universal Pollen Index 0-5, None if no data


@dataclass
class PollenReading:
    types: list[PollenTypeReading]


def upi_label(upi: int | None) -> str:
    if upi is None:
        return "Unknown"
    return UPI_CATEGORIES.get(upi, str(upi))


REFERER = "https://pickles.dev"


def get_api_key() -> str:
    key = os.environ.get("GOOGLE_POLLEN_API_KEY", "")
    if not key:
        raise PollenError(
            "GOOGLE_POLLEN_API_KEY not set. "
            "Enable the Pollen API in Google Cloud Console, "
            "store the key in 1Password as 'Google Air Quality API / api_key', "
            "then run 'just dotenv'."
        )
    return key


async def _fetch(lat: float, lon: float, api_key: str) -> PollenReading:
    params = {
        "key": api_key,
        "location.latitude": lat,
        "location.longitude": lon,
        "days": 1,
        # Suppress plant-level detail; type summary is sufficient for display
        "plantsDescription": 0,
    }
    headers = {"Referer": REFERER}
    timeout = ClientTimeout(total=FETCH_TIMEOUT)
    async with ClientSession(trust_env=True, timeout=timeout) as session:
        try:
            async with session.get(BASE_URL, params=params, headers=headers) as resp:
                if resp.status == 400:
                    body = await resp.json()
                    msg = body.get("error", {}).get("message", "bad request")
                    raise PollenError(f"API error: {msg}")
                if resp.status != 200:
                    body = await resp.text()
                    raise PollenError(f"HTTP {resp.status}: {body[:200]}")
                data = await resp.json()
        except asyncio.TimeoutError:
            raise PollenError(f"request timed out ({FETCH_TIMEOUT}s)")
        except OSError as e:
            raise PollenError(f"network error: {e}") from e

    daily = data.get("dailyInfo", [])
    if not daily:
        raise PollenError("response contained no daily forecast data")

    today = daily[0]
    types = []
    for pt in today.get("pollenTypeInfo", []):
        index_info = pt.get("indexInfo") or {}
        upi = index_info.get("value")
        types.append(PollenTypeReading(
            code=pt.get("code", ""),
            display_name=pt.get("displayName", pt.get("code", "")),
            in_season=pt.get("inSeason", False),
            upi=upi,
        ))

    return PollenReading(types=types)


def fetch_pollen(lat: float, lon: float) -> PollenReading:
    api_key = get_api_key()
    return asyncio.run(_fetch(lat, lon, api_key))


def format_pollen(reading: PollenReading) -> str:
    if not reading.types:
        return "Pollen:     (no data)"

    lines = ["Pollen:"]
    for t in reading.types:
        if not t.in_season:
            lines.append(f"  {t.display_name:<8}  (out of season)")
        else:
            upi_str = f"{t.upi}/5" if t.upi is not None else "?"
            label = upi_label(t.upi)
            lines.append(f"  {t.display_name:<8}  {upi_str}  {label}")

    return "\n".join(lines)
