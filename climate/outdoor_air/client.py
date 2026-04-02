import asyncio
import os
from dataclasses import dataclass, field

from aiohttp import ClientSession, ClientTimeout

FETCH_TIMEOUT = 10  # seconds

BASE_URL = "https://airquality.googleapis.com/v1/currentConditions:lookup"
REFERER = "https://pickles.dev"

# Pollutant codes returned by Google Air Quality API → display names
POLLUTANT_NAMES = {
    "pm25":  "PM2.5",
    "pm10":  "PM10",
    "o3":    "Ozone",
    "no2":   "NO₂",
    "so2":   "SO₂",
    "co":    "CO",
    "nh3":   "NH₃",
}


class AirQualityError(Exception):
    """Fetch failed for a diagnosable reason."""


@dataclass
class PollutantReading:
    code: str
    display_name: str
    value: float
    units: str  # e.g. MICROGRAMS_PER_CUBIC_METER, PARTS_PER_BILLION


@dataclass
class AirQualityReading:
    us_aqi: int | None
    us_aqi_category: str | None
    dominant_pollutant_code: str | None
    pollutants: list[PollutantReading] = field(default_factory=list)
    # Only populated when AQI > 50
    health_recommendation: str | None = None


def dominant_pollutant_name(code: str | None) -> str | None:
    if code is None:
        return None
    return POLLUTANT_NAMES.get(code, code)


def get_api_key() -> str:
    key = os.environ.get("GOOGLE_POLLEN_API_KEY", "")
    if not key:
        raise AirQualityError(
            "GOOGLE_POLLEN_API_KEY not set. "
            "Store the key in 1Password as 'Google Air Quality API / api_key', "
            "then run 'just dotenv'."
        )
    return key


async def _fetch(lat: float, lon: float) -> AirQualityReading:
    api_key = get_api_key()

    body = {
        "location": {"latitude": lat, "longitude": lon},
        "extraComputations": [
            "DOMINANT_POLLUTANT_CONCENTRATION",
            "POLLUTANT_CONCENTRATION",
            "HEALTH_RECOMMENDATIONS",
        ],
        "universalAqi": True,
    }

    params = {"key": api_key}
    headers = {"Referer": REFERER}
    timeout = ClientTimeout(total=FETCH_TIMEOUT)

    async with ClientSession(trust_env=True, timeout=timeout) as session:
        try:
            async with session.post(BASE_URL, json=body, params=params, headers=headers) as resp:
                if resp.status != 200:
                    body_text = await resp.text()
                    raise AirQualityError(f"HTTP {resp.status}: {body_text[:200]}")
                data = await resp.json()
        except asyncio.TimeoutError:
            raise AirQualityError(f"request timed out ({FETCH_TIMEOUT}s)")
        except OSError as e:
            raise AirQualityError(f"network error: {e}") from e

    # Extract UAQI index (Universal AQI — what Google reliably returns for all locations)
    us_aqi = None
    us_aqi_category = None
    dominant_code = None
    for idx in data.get("indexes", []):
        if idx.get("code") == "uaqi":
            us_aqi = idx.get("aqi")
            us_aqi_category = idx.get("category")
            dominant_code = idx.get("dominantPollutant")
            break

    # Extract individual pollutant concentrations
    pollutants = []
    for p in data.get("pollutants", []):
        conc = p.get("concentration", {})
        value = conc.get("value")
        if value is None:
            continue
        code = p.get("code", "")
        pollutants.append(PollutantReading(
            code=code,
            display_name=POLLUTANT_NAMES.get(code, p.get("displayName", code)),
            value=value,
            units=conc.get("units", ""),
        ))

    health_rec = data.get("healthRecommendations", {}).get("generalPopulation")

    return AirQualityReading(
        us_aqi=us_aqi,
        us_aqi_category=us_aqi_category,
        dominant_pollutant_code=dominant_code,
        pollutants=pollutants,
        health_recommendation=health_rec,
    )


def fetch_air_quality(lat: float, lon: float) -> AirQualityReading:
    return asyncio.run(_fetch(lat, lon))


def format_air_quality(reading: AirQualityReading) -> str:
    lines = []

    if reading.us_aqi is not None:
        category = reading.us_aqi_category or ""
        dominant = dominant_pollutant_name(reading.dominant_pollutant_code)
        dominant_str = f"  (main: {dominant})" if dominant else ""
        lines.append(f"AQI:        {reading.us_aqi}  {category}{dominant_str}")

    for p in reading.pollutants:
        # Abbreviate units for display
        if "CUBIC_METER" in p.units:
            unit_str = "μg/m³"
        elif "BILLION" in p.units:
            unit_str = "ppb"
        else:
            unit_str = p.units.lower()
        lines.append(f"{p.display_name:<10}  {p.value:.1f} {unit_str}")

    # Show health recommendation only when the category indicates a real concern.
    # "Good" and "Excellent" categories get the benign "enjoy the outdoors" message which is noise.
    good_categories = {"good air quality", "excellent air quality"}
    is_concerning = (
        reading.us_aqi_category is not None
        and reading.us_aqi_category.lower() not in good_categories
    )
    if reading.health_recommendation and is_concerning:
        lines.append(f"\nHealth: {reading.health_recommendation}")

    return "\n".join(lines) if lines else "(no data)"
