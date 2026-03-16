import sys
from pathlib import Path

import yaml


def load_thermostats(path: str | Path) -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except OSError as e:
        print(f"Cannot read thermostats file: {path}: {e}")
        sys.exit(1)
    if data is None or "thermostats" not in data:
        print("thermostats.yaml is empty or missing 'thermostats' key")
        sys.exit(1)
    return data


def get_managed_thermostats(data: dict) -> list[tuple[str, str]]:
    """Return (name, thermostat_id) for all managed thermostats."""
    return [
        (name, entry["thermostat_id"])
        for name, entry in data["thermostats"].items()
        if entry.get("managed", False)
    ]


def get_thermostat_id(data: dict, name: str) -> str:
    """Return thermostat_id for the named thermostat. Raises KeyError if not found."""
    thermostats = data["thermostats"]
    if name not in thermostats:
        raise KeyError(f"Thermostat '{name}' not in thermostats.yaml")
    return thermostats[name]["thermostat_id"]
