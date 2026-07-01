"""Smart Device Management API client: structures and devices.

SDM returns devices across every structure on the account in one flat list,
grouped only by a "parentRelations" pointer -- see nest/locations.py for how
that gets mapped onto our canonical picklehome locations.
"""

from dataclasses import dataclass

import aiohttp

from nest.sdm.auth import get_access_token, load_config

BASE_URL = "https://smartdevicemanagement.googleapis.com/v1"


class SDMError(Exception):
    """SDM API call failed for a diagnosable reason."""


@dataclass
class Structure:
    name: str  # full resource name: enterprises/{project}/structures/{id}
    custom_name: str  # sdm.structures.traits.Info.customName, or the raw id if unset

    @property
    def id(self) -> str:
        return self.name.rsplit("/", 1)[-1]


@dataclass
class NestDevice:
    name: str  # full resource name: enterprises/{project}/devices/{id}
    device_type: str  # "THERMOSTAT", "CAMERA", or "DOORBELL" (from sdm.devices.types.*)
    custom_name: str
    structure_id: str
    connectivity: str | None = None  # "ONLINE" / "OFFLINE"
    # Thermostat-specific (sdm.devices.traits.ThermostatMode / Temperature / ThermostatTemperatureSetpoint / Humidity)
    mode: str | None = None  # HEAT / COOL / HEATCOOL / OFF
    ambient_temperature_c: float | None = None
    setpoint_heat_c: float | None = None
    setpoint_cool_c: float | None = None
    humidity_percent: int | None = None
    # Camera/doorbell-specific -- a doorbell is a camera plus a chime trait, so
    # this is keyed off trait presence, not device_type.
    has_live_stream: bool = False

    @property
    def id(self) -> str:
        return self.name.rsplit("/", 1)[-1]


def _device_type(raw_type: str) -> str:
    # raw_type looks like "sdm.devices.types.THERMOSTAT"
    return raw_type.rsplit(".", 1)[-1]


def _structure_id_from_parent(parent_name: str) -> str:
    # parent_name looks like "enterprises/{project}/structures/{id}" or, when the
    # device is assigned to a room, "enterprises/{project}/structures/{id}/rooms/{id}"
    # -- the structure id is never the last segment, so pull it out by position.
    parts = parent_name.split("/")
    if "structures" in parts:
        idx = parts.index("structures")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def parse_structure(raw: dict) -> Structure:
    name = raw["name"]
    fallback = name.rsplit("/", 1)[-1]
    custom_name = raw.get("traits", {}).get("sdm.structures.traits.Info", {}).get("customName")
    return Structure(name=name, custom_name=custom_name or fallback)


def parse_device(raw: dict) -> NestDevice:
    traits = raw.get("traits", {})
    name = raw["name"]
    device_type = _device_type(raw.get("type", ""))

    structure_id = ""
    room_name = ""
    for parent in raw.get("parentRelations", []):
        structure_id = _structure_id_from_parent(parent.get("parent", ""))
        room_name = parent.get("displayName", "")
        if structure_id:
            break

    # Info.customName is often left empty (nobody renamed the device in the
    # Home app); the room it's assigned to is a much more useful fallback than
    # the opaque device id.
    custom_name = (
        traits.get("sdm.devices.traits.Info", {}).get("customName")
        or room_name
        or name.rsplit("/", 1)[-1]
    )

    device = NestDevice(
        name=name,
        device_type=device_type,
        custom_name=custom_name,
        structure_id=structure_id,
        connectivity=traits.get("sdm.devices.traits.Connectivity", {}).get("status"),
        has_live_stream="sdm.devices.traits.CameraLiveStream" in traits,
    )

    if device_type == "THERMOSTAT":
        device.mode = traits.get("sdm.devices.traits.ThermostatMode", {}).get("mode")
        device.ambient_temperature_c = traits.get("sdm.devices.traits.Temperature", {}).get(
            "ambientTemperatureCelsius"
        )
        setpoint = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})
        device.setpoint_heat_c = setpoint.get("heatCelsius")
        device.setpoint_cool_c = setpoint.get("coolCelsius")
        device.humidity_percent = traits.get("sdm.devices.traits.Humidity", {}).get(
            "ambientHumidityPercent"
        )

    return device


async def _get(path: str) -> dict:
    config = load_config()
    token = await get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/enterprises/{config.project_id}/{path}"
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.get(url, headers=headers) as resp:
            body = await resp.json()
            if resp.status != 200:
                raise SDMError(f"HTTP {resp.status} for {path}: {body}")
            return body


async def get_structures() -> list[Structure]:
    body = await _get("structures")
    return [parse_structure(s) for s in body.get("structures", [])]


async def get_devices() -> list[NestDevice]:
    body = await _get("devices")
    return [parse_device(d) for d in body.get("devices", [])]
