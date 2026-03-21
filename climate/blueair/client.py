"""Async client wrapper for BlueAir device discovery and status."""

from __future__ import annotations

from blueair_api import DeviceAws, HttpAwsBlueair, get_aws_devices


async def discover_devices(
    username: str,
    password: str,
    region: str = "us",
) -> tuple[list[DeviceAws], HttpAwsBlueair]:
    """Discover all BlueAir AWS devices and return (devices, api).

    Each device is created but NOT refreshed yet — the caller decides
    when to call device.refresh().
    """
    api, devices = await get_aws_devices(username, password, region)
    return devices, api


def _clean_value(value):
    """Convert the NotImplemented sentinel to None."""
    if value is NotImplemented:
        return None
    return value


# Fields to extract from a refreshed DeviceAws into the flat status dict.
_STATUS_FIELDS = (
    "name",
    "uuid",
    "sku",
    "firmware",
    "pm1",
    "pm2_5",
    "pm10",
    "total_voc",
    "voc",
    "temperature",
    "humidity",
    "fan_speed",
    "fan_auto_mode",
    "standby",
    "night_mode",
    "germ_shield",
    "brightness",
    "child_lock",
    "filter_usage_percentage",
    "wifi_working",
)


def extract_device_status(device: DeviceAws) -> dict:
    """Extract a flat status dict from a refreshed DeviceAws.

    All values pass through _clean_value so NotImplemented becomes None.
    The ``model`` key uses the device's model property (an enum) and is
    stored as its string value.
    """
    status: dict = {}
    for field in _STATUS_FIELDS:
        status[field] = _clean_value(getattr(device, field))
    status["model"] = str(device.model.value) if device.model else None
    return status


async def get_device_status(
    username: str,
    password: str,
    region: str,
    managed_devices: list[tuple[str, str]],
) -> tuple[list[dict], HttpAwsBlueair]:
    """Fetch status for managed devices only.

    Parameters
    ----------
    managed_devices:
        List of (name, uuid) tuples identifying which purifiers to query.

    Returns
    -------
    (statuses, api) where statuses is a list of flat dicts (one per
    managed device) and api is the authenticated HttpAwsBlueair session.
    """
    devices, api = await discover_devices(username, password, region)
    managed_uuids = {uuid for _, uuid in managed_devices}

    statuses: list[dict] = []
    for device in devices:
        if device.uuid in managed_uuids:
            await device.refresh()
            statuses.append(extract_device_status(device))

    return statuses, api
