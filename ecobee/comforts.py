import sys
from pathlib import Path

import yaml
from pyecobee.const import ECOBEE_ENDPOINT_THERMOSTAT


def capture_all_thermostats(ecobee) -> list[tuple[str, str, list]]:
    """Fetch all thermostats from API. Returns list of (name, thermostat_id, climates)."""
    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        raise RuntimeError("Failed to fetch thermostat data from Ecobee.")
    results = []
    for t in ecobee.thermostats:
        climates = t.get("program", {}).get("climates", [])
        results.append((t["name"], t["identifier"], climates))
    return results


def climates_to_yaml_dict(climates: list) -> dict:
    """Convert API climates list to YAML-friendly dict (temps in whole °F).

    Includes 'name' for user-owned climates (climateRef is Ecobee-assigned e.g. 'smart1')
    so the YAML remains human-readable without looking up IDs.
    """
    result = {}
    for c in climates:
        entry: dict = {
            "cool_temp": c["coolTemp"] // 10,
            "heat_temp": c["heatTemp"] // 10,
        }
        if c.get("owner") == "user":
            entry["name"] = c["name"]
        result[c["climateRef"]] = entry
    return result


def load_comforts(path: str | Path) -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except OSError as e:
        print(f"Cannot read comforts file: {path}: {e}")
        sys.exit(1)
    if data is None or not isinstance(data, dict):
        print("comforts.yaml is empty or invalid")
        sys.exit(1)
    if "thermostats" not in data:
        print("comforts.yaml must have a top-level 'thermostats' key")
        sys.exit(1)
    return data


def iter_thermostat_entries(data: dict, name_filter: str | None = None):
    """Yield (name, thermostat_id, climates_dict) for each configured thermostat."""
    for name, entry in data["thermostats"].items():
        if name_filter and name != name_filter:
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"Thermostat '{name}' entry must be a mapping")
        thermostat_id = entry.get("thermostat_id")
        if not thermostat_id:
            raise ValueError(f"Thermostat '{name}' is missing 'thermostat_id'")
        climates_dict = entry.get("climates")
        if not isinstance(climates_dict, dict):
            raise ValueError(f"Thermostat '{name}' is missing 'climates'")
        yield name, thermostat_id, climates_dict


def apply_comforts_to_climates(comforts_dict: dict, current_climates: list) -> list:
    """Merge YAML comfort settings into the current API climates list.

    Matches by climateRef (YAML key). For user-owned climates that include a 'name'
    field, also validates the name matches the thermostat — warns if it doesn't,
    which indicates the climateRef was reassigned or the YAML is stale.

    Only updates cool_temp and heat_temp. All other API fields are preserved.
    Returns the full updated climates list suitable for an API push.
    """
    updated = []
    unknown_refs = set(comforts_dict.keys()) - {c["climateRef"] for c in current_climates}
    if unknown_refs:
        raise ValueError(
            f"Unknown climateRef(s) in comforts.yaml: {sorted(unknown_refs)}. "
            f"Valid refs: {sorted(c['climateRef'] for c in current_climates)}"
        )
    for climate in current_climates:
        ref = climate["climateRef"]
        overrides = comforts_dict.get(ref, {})
        c = dict(climate)
        if overrides:
            yaml_name = overrides.get("name")
            if yaml_name and climate.get("owner") == "user" and yaml_name != climate.get("name"):
                print(
                    f"  Warning: {ref} name mismatch — "
                    f"YAML has '{yaml_name}', thermostat has '{climate.get('name')}'. "
                    f"Re-run 'just ecobee-comforts-capture' to refresh."
                )
            if "cool_temp" in overrides:
                c["coolTemp"] = overrides["cool_temp"] * 10
            if "heat_temp" in overrides:
                c["heatTemp"] = overrides["heat_temp"] * 10
        updated.append(c)
    return updated


def push_comforts(ecobee, thermostat_id: str, updated_climates: list) -> None:
    body = {
        "selection": {
            "selectionType": "thermostats",
            "selectionMatch": thermostat_id,
        },
        "thermostat": {
            "program": {
                "climates": updated_climates,
            }
        },
    }
    response = ecobee._request_with_refresh(
        "POST", ECOBEE_ENDPOINT_THERMOSTAT, "push comforts", body=body
    )
    if response is None:
        raise RuntimeError("Failed to push comfort settings to Ecobee.")


def print_comforts(climates_dict: dict, current_climates: list, name: str = "") -> None:
    ref_to_display = {c["climateRef"]: c.get("name", c["climateRef"]) for c in current_climates}
    header = f"Comfort modes — {name}" if name else "Comfort modes"
    print(f"{header}:\n")
    for ref, settings in climates_dict.items():
        display = ref_to_display.get(ref, ref)
        cool = settings.get("cool_temp", "?")
        heat = settings.get("heat_temp", "?")
        print(f"  {display} ({ref}):  cool={cool}°F  heat={heat}°F")
