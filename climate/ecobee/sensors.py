from pyecobee.const import ECOBEE_ENDPOINT_THERMOSTAT


def get_thermostat_with_sensors(ecobee, thermostat_id: str) -> dict:
    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        raise RuntimeError("Failed to fetch thermostat data from Ecobee.")
    thermostat = next(
        (t for t in ecobee.thermostats if t["identifier"] == thermostat_id), None
    )
    if thermostat is None:
        raise LookupError(
            f"Thermostat {thermostat_id} not found. Re-run 'just climate-auth'."
        )
    return thermostat


def resolve_sensor_entries(remote_sensors: list[dict], names: list[str]) -> list[dict]:
    """Map sensor names to the {id, name} entries a climate's `sensors` array holds.

    The climate-side id is the sensor id plus ':1' (e.g. 'rs2:101' -> 'rs2:101:1',
    the thermostat's own sensor is 'ei:0:1'). Unknown names raise, so a typo or
    an unpaired sensor can never silently shrink a climate to fewer sensors.
    """
    by_name = {s["name"]: s for s in remote_sensors}
    missing = [n for n in names if n not in by_name]
    if missing:
        known = ", ".join(sorted(by_name))
        raise ValueError(f"Unknown sensor(s) {missing}; thermostat has: {known}")
    return [{"id": f"{by_name[n]['id']}:1", "name": n} for n in names]


def plan_enrollment(climates: list[dict], desired: list[dict]) -> list[tuple[str, list[str], list[str]]]:
    """Return (climateRef, current names, desired names) for climates that differ."""
    desired_names = [s["name"] for s in desired]
    changes = []
    for climate in climates:
        current = [s["name"] for s in climate.get("sensors", [])]
        if sorted(current) != sorted(desired_names):
            changes.append((climate["climateRef"], current, desired_names))
    return changes


def apply_enrollment(climates: list[dict], desired: list[dict]) -> list[dict]:
    """Return a copy of climates with every climate's sensors set to `desired`."""
    return [{**c, "sensors": [dict(s) for s in desired]} for c in climates]


def push_enrollment(ecobee, thermostat_id: str, schedule_array: list, climates: list) -> None:
    body = {
        "selection": {
            "selectionType": "thermostats",
            "selectionMatch": thermostat_id,
        },
        "thermostat": {
            "program": {
                "schedule": schedule_array,
                "climates": climates,
            }
        },
    }
    response = ecobee._request_with_refresh(
        "POST", ECOBEE_ENDPOINT_THERMOSTAT, "set climate sensors", body=body
    )
    if response is None:
        raise RuntimeError("Failed to set climate sensors on Ecobee.")
