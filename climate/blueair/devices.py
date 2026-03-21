import sys
from pathlib import Path

import yaml

DEFAULT_PURIFIERS_PATH = Path(__file__).parent.parent / "config" / "purifiers.yaml"


def load_purifiers(path: str | Path) -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except OSError as e:
        print(f"Cannot read purifiers file: {path}: {e}")
        sys.exit(1)
    if data is None or "purifiers" not in data:
        print("purifiers.yaml is empty or missing 'purifiers' key")
        sys.exit(1)
    return data


def get_managed_purifiers(data: dict) -> list[tuple[str, str]]:
    """Return (name, uuid) for all managed purifiers."""
    return [
        (name, entry["uuid"])
        for name, entry in data["purifiers"].items()
        if entry.get("managed", False)
    ]
