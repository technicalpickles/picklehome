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
    """Convert the NotImplemented sentinel to None.

    The blueair-api library uses Python's NotImplemented singleton (not None)
    for sensors/controls a device doesn't support. For example, the 411i Max
    returns NotImplemented for PM1, PM10, VOC, temperature, and humidity since
    it only has a PM2.5 sensor. We normalize to None for clean downstream use.
    """
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


# Maps CLI property names to (DeviceAws method name, value type).
# "bool" expects True/False, "int" expects an integer.
SETTABLE_PROPERTIES = {
    "fan-speed": ("set_fan_speed", "int"),
    "auto-mode": ("set_fan_auto_mode", "bool"),
    "night-mode": ("set_night_mode", "bool"),
    "standby": ("set_standby", "bool"),
    "brightness": ("set_brightness", "int"),
    "child-lock": ("set_child_lock", "bool"),
}


def parse_set_value(value_str: str, value_type: str):
    """Parse a CLI value string into the correct Python type."""
    if value_type == "bool":
        if value_str.lower() in ("on", "true", "1"):
            return True
        if value_str.lower() in ("off", "false", "0"):
            return False
        raise ValueError(f"Expected on/off, got: {value_str}")
    if value_type == "int":
        return int(value_str)
    return value_str


async def set_device_property(
    username: str,
    password: str,
    region: str,
    managed_devices: list[tuple[str, str]],
    prop: str,
    value_str: str,
    device_filter: str | None = None,
) -> list[str]:
    """Set a property on managed devices. Returns list of confirmation messages."""
    if prop not in SETTABLE_PROPERTIES:
        raise ValueError(f"Unknown property: {prop}. Valid: {', '.join(SETTABLE_PROPERTIES)}")

    method_name, value_type = SETTABLE_PROPERTIES[prop]
    value = parse_set_value(value_str, value_type)

    devices, api = await discover_devices(username, password, region)
    managed_uuids = {uuid for _, uuid in managed_devices}

    confirmations = []
    for device in devices:
        if device.uuid not in managed_uuids:
            continue
        # Refresh to get device name
        await device.refresh()
        name = device.name or device.name_api
        if device_filter and name != device_filter:
            continue
        method = getattr(device, method_name)
        await method(value)
        confirmations.append(f"{name}: {prop} → {value_str}")

    await api.cleanup_client_session()
    return confirmations
