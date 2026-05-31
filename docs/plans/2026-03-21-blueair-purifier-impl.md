# BlueAir Purifier Integration: Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add read-only BlueAir air purifier CLI to `climate/blueair/`: auth, device discovery, and status display for the Blue Pure 411i Max.

**Architecture:** Mirrors the ecobee pattern: keychain auth, YAML device registry, async client wrapper, status formatter, argparse CLI. The `blueair-api` library handles all Gigya/AWS auth and API calls; we wrap it thinly.

**Tech Stack:** Python 3.12+, `blueair-api` (async/aiohttp), `keyring`, `pyyaml`, `argparse`, `asyncio`

**Design doc:** `docs/plans/2026-03-21-blueair-purifier-integration.md`

**Library source (local):** `~/github.com/technicalpickles/blueair_api/`

---

### Task 1: Add blueair-api dependency

**Files:**
- Modify: `pyproject.toml:12-17` (dependencies list)

**Step 1: Add dependency**

Add `"blueair-api>=1.48"` to the climate section of dependencies in `pyproject.toml`:

```toml
dependencies = [
    # climate
    "python-ecobee-api==0.3.2",
    "keyring>=24",
    "pyyaml>=6",
    "aioambient==2024.08.0",
    "blueair-api>=1.48",
    # network
    ...
]
```

**Step 2: Install**

Run: `uv sync`
Expected: resolves and installs `blueair-api` and its `aiohttp` dependency (aiohttp already present via aioambient)

**Step 3: Verify import**

Run: `uv run python -c "from blueair_api import get_aws_devices; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(climate): add blueair-api dependency for purifier integration"
```

---

### Task 2: Auth module: keychain credential storage

**Files:**
- Create: `climate/blueair/__init__.py`
- Create: `climate/blueair/auth.py`
- Test: `tests/climate/blueair/test_auth.py`

**Step 1: Create package init**

```python
# climate/blueair/__init__.py
```

(Empty file, just marks the package.)

**Step 2: Write the failing test**

```python
# tests/climate/blueair/test_auth.py
from unittest.mock import patch

from climate.blueair.auth import (
    KEYCHAIN_SERVICE,
    get_credentials,
    store_credentials,
)


def test_keychain_service_name():
    assert KEYCHAIN_SERVICE == "picklehome-blueair"


@patch("climate.blueair.auth.keyring")
def test_store_credentials(mock_keyring):
    store_credentials("user@example.com", "secret", "us")
    assert mock_keyring.set_password.call_count == 3
    mock_keyring.set_password.assert_any_call(KEYCHAIN_SERVICE, "username", "user@example.com")
    mock_keyring.set_password.assert_any_call(KEYCHAIN_SERVICE, "password", "secret")
    mock_keyring.set_password.assert_any_call(KEYCHAIN_SERVICE, "region", "us")


@patch("climate.blueair.auth.keyring")
def test_get_credentials_success(mock_keyring):
    mock_keyring.get_password.side_effect = lambda svc, key: {
        "username": "user@example.com",
        "password": "secret",
        "region": "us",
    }[key]
    username, password, region = get_credentials()
    assert username == "user@example.com"
    assert password == "secret"
    assert region == "us"


@patch("climate.blueair.auth.keyring")
def test_get_credentials_missing_raises(mock_keyring):
    mock_keyring.get_password.return_value = None
    try:
        get_credentials()
        assert False, "Should have raised SystemExit"
    except SystemExit:
        pass
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/climate/blueair/test_auth.py -v`
Expected: FAIL (ImportError, module doesn't exist yet)

**Step 4: Write implementation**

```python
# climate/blueair/auth.py
import sys

import keyring

KEYCHAIN_SERVICE = "picklehome-blueair"


def store_credentials(username: str, password: str, region: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, "username", username)
    keyring.set_password(KEYCHAIN_SERVICE, "password", password)
    keyring.set_password(KEYCHAIN_SERVICE, "region", region)


def get_credentials() -> tuple[str, str, str]:
    username = keyring.get_password(KEYCHAIN_SERVICE, "username")
    password = keyring.get_password(KEYCHAIN_SERVICE, "password")
    region = keyring.get_password(KEYCHAIN_SERVICE, "region")
    if not username or not password:
        print("BlueAir credentials not found. Run 'just blueair-auth' to set up.")
        sys.exit(1)
    return username, password, region or "us"
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/climate/blueair/test_auth.py -v`
Expected: 4 passed

**Step 6: Commit**

```bash
git add climate/blueair/__init__.py climate/blueair/auth.py tests/climate/blueair/test_auth.py
git commit -m "feat(blueair): auth module with keychain credential storage"
```

---

### Task 3: Device registry: YAML loader

**Files:**
- Create: `climate/blueair/devices.py`
- Test: `tests/climate/blueair/test_devices.py`

**Step 1: Write the failing test**

```python
# tests/climate/blueair/test_devices.py
import pytest
from climate.blueair.devices import load_purifiers, get_managed_purifiers, DEFAULT_PURIFIERS_PATH


def test_default_path_points_to_config():
    assert "climate/config/purifiers.yaml" in str(DEFAULT_PURIFIERS_PATH)


def test_load_purifiers(tmp_path):
    yaml_file = tmp_path / "purifiers.yaml"
    yaml_file.write_text(
        "purifiers:\n"
        "  Living Room:\n"
        '    uuid: "abc123"\n'
        "    managed: true\n"
        "  Bedroom:\n"
        '    uuid: "def456"\n'
        "    managed: false\n"
    )
    data = load_purifiers(yaml_file)
    assert "Living Room" in data["purifiers"]
    assert "Bedroom" in data["purifiers"]


def test_get_managed_purifiers(tmp_path):
    yaml_file = tmp_path / "purifiers.yaml"
    yaml_file.write_text(
        "purifiers:\n"
        "  Living Room:\n"
        '    uuid: "abc123"\n'
        "    managed: true\n"
        "  Bedroom:\n"
        '    uuid: "def456"\n'
        "    managed: false\n"
    )
    data = load_purifiers(yaml_file)
    managed = get_managed_purifiers(data)
    assert managed == [("Living Room", "abc123")]


def test_load_purifiers_missing_file(tmp_path):
    with pytest.raises(SystemExit):
        load_purifiers(tmp_path / "nope.yaml")


def test_load_purifiers_empty_file(tmp_path):
    yaml_file = tmp_path / "purifiers.yaml"
    yaml_file.write_text("")
    with pytest.raises(SystemExit):
        load_purifiers(yaml_file)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/blueair/test_devices.py -v`
Expected: FAIL (ImportError)

**Step 3: Write implementation**

```python
# climate/blueair/devices.py
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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/climate/blueair/test_devices.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add climate/blueair/devices.py tests/climate/blueair/test_devices.py
git commit -m "feat(blueair): device registry YAML loader"
```

---

### Task 4: Client wrapper: async API interaction

**Files:**
- Create: `climate/blueair/client.py`
- Test: `tests/climate/blueair/test_client.py`

**Step 1: Write the failing test**

```python
# tests/climate/blueair/test_client.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from climate.blueair.client import discover_devices, get_device_status


@patch("climate.blueair.client.get_aws_devices")
def test_discover_devices(mock_get):
    mock_api = MagicMock()
    mock_api.cleanup_client_session = AsyncMock()

    mock_device = MagicMock()
    mock_device.uuid = "abc123"
    mock_device.name_api = "Living Room"
    mock_device.mac = "AA:BB:CC:DD:EE:FF"
    mock_device.type_name = "purifier"
    mock_device.sku = "110031"
    mock_device.model = "Blueair Blue Pure 411i Max"
    mock_device.refresh = AsyncMock()

    mock_get.return_value = (mock_api, [mock_device])

    devices, api = asyncio.run(discover_devices("user", "pass", "us"))
    assert len(devices) == 1
    assert devices[0].uuid == "abc123"
    mock_get.assert_called_once_with(username="user", password="pass", region="us")


@patch("climate.blueair.client.get_aws_devices")
def test_get_device_status(mock_get):
    mock_api = MagicMock()
    mock_api.cleanup_client_session = AsyncMock()

    mock_device = MagicMock()
    mock_device.uuid = "abc123"
    mock_device.name = "Living Room"
    mock_device.name_api = "Living Room"
    mock_device.mac = "AA:BB:CC:DD:EE:FF"
    mock_device.type_name = "purifier"
    mock_device.refresh = AsyncMock()
    mock_device.model = "Blueair Blue Pure 411i Max"
    mock_device.sku = "110031"
    mock_device.pm1 = 5
    mock_device.pm2_5 = 8
    mock_device.pm10 = 12
    mock_device.total_voc = 120
    mock_device.voc = NotImplemented
    mock_device.temperature = 22
    mock_device.humidity = 45
    mock_device.fan_speed = 42
    mock_device.fan_auto_mode = True
    mock_device.standby = False
    mock_device.night_mode = False
    mock_device.germ_shield = NotImplemented
    mock_device.brightness = 0
    mock_device.child_lock = False
    mock_device.filter_usage_percentage = 78
    mock_device.wifi_working = True

    mock_get.return_value = (mock_api, [mock_device])

    results, api = asyncio.run(
        get_device_status("user", "pass", "us", [("Living Room", "abc123")])
    )
    assert len(results) == 1
    status = results[0]
    assert status["name"] == "Living Room"
    assert status["pm2_5"] == 8
    assert status["fan_speed"] == 42
    assert status["fan_auto_mode"] is True
    assert status["filter_usage_percentage"] == 78
    # NotImplemented fields should be None in output
    assert status["voc"] is None
    assert status["germ_shield"] is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/blueair/test_client.py -v`
Expected: FAIL (ImportError)

**Step 3: Write implementation**

```python
# climate/blueair/client.py
from blueair_api import get_aws_devices
from blueair_api.device_aws import DeviceAws
from blueair_api.http_aws_blueair import HttpAwsBlueair


async def discover_devices(
    username: str, password: str, region: str
) -> tuple[list[DeviceAws], HttpAwsBlueair]:
    api, devices = await get_aws_devices(
        username=username, password=password, region=region
    )
    # refresh each device to populate sku/model
    for device in devices:
        await device.refresh()
    return devices, api


def _clean_value(value):
    """Convert NotImplemented sentinel to None for clean output."""
    if value is NotImplemented:
        return None
    return value


def extract_device_status(device: DeviceAws) -> dict:
    """Extract a flat status dict from a refreshed DeviceAws."""
    return {
        "name": device.name or device.name_api,
        "uuid": device.uuid,
        "model": str(device.model),
        "sku": _clean_value(device.sku),
        "firmware": _clean_value(device.firmware),
        # Sensors
        "pm1": _clean_value(device.pm1),
        "pm2_5": _clean_value(device.pm2_5),
        "pm10": _clean_value(device.pm10),
        "total_voc": _clean_value(device.total_voc),
        "voc": _clean_value(device.voc),
        "temperature": _clean_value(device.temperature),
        "humidity": _clean_value(device.humidity),
        # State
        "fan_speed": _clean_value(device.fan_speed),
        "fan_auto_mode": _clean_value(device.fan_auto_mode),
        "standby": _clean_value(device.standby),
        "night_mode": _clean_value(device.night_mode),
        "germ_shield": _clean_value(device.germ_shield),
        "brightness": _clean_value(device.brightness),
        "child_lock": _clean_value(device.child_lock),
        "filter_usage_percentage": _clean_value(device.filter_usage_percentage),
        "wifi_working": _clean_value(device.wifi_working),
    }


async def get_device_status(
    username: str,
    password: str,
    region: str,
    managed_devices: list[tuple[str, str]],
) -> tuple[list[dict], HttpAwsBlueair]:
    """Fetch status for managed devices. Returns (statuses, api). Caller should clean up api."""
    api, all_devices = await get_aws_devices(
        username=username, password=password, region=region
    )
    managed_uuids = {uuid for _, uuid in managed_devices}
    results = []
    for device in all_devices:
        if device.uuid in managed_uuids:
            await device.refresh()
            results.append(extract_device_status(device))
    return results, api
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/climate/blueair/test_client.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add climate/blueair/client.py tests/climate/blueair/test_client.py
git commit -m "feat(blueair): async client wrapper for device discovery and status"
```

---

### Task 5: Status formatter: human-readable output

**Files:**
- Create: `climate/blueair/status.py`
- Test: `tests/climate/blueair/test_status.py`

**Step 1: Write the failing test**

```python
# tests/climate/blueair/test_status.py
from climate.blueair.status import format_status


def test_format_status_basic():
    statuses = [
        {
            "name": "Living Room",
            "model": "Blueair Blue Pure 411i Max",
            "pm1": 5,
            "pm2_5": 8,
            "pm10": 12,
            "total_voc": 120,
            "voc": None,
            "temperature": 22,
            "humidity": 45,
            "fan_speed": 42,
            "fan_auto_mode": True,
            "standby": False,
            "night_mode": False,
            "germ_shield": None,
            "brightness": 0,
            "child_lock": False,
            "filter_usage_percentage": 78,
            "wifi_working": True,
        }
    ]
    output = format_status(statuses)
    assert "Living Room" in output
    assert "411i Max" in output
    assert "PM2.5 8" in output
    assert "VOC 120" in output
    assert "72°F" in output  # 22°C -> 72°F
    assert "45%" in output
    assert "Auto" in output
    assert "42%" in output
    assert "78%" in output


def test_format_status_standby():
    statuses = [
        {
            "name": "Bedroom",
            "model": "Blueair Blue Pure 411i Max",
            "pm1": None,
            "pm2_5": None,
            "pm10": None,
            "total_voc": None,
            "voc": None,
            "temperature": None,
            "humidity": None,
            "fan_speed": 0,
            "fan_auto_mode": False,
            "standby": True,
            "night_mode": False,
            "germ_shield": None,
            "brightness": 0,
            "child_lock": False,
            "filter_usage_percentage": 50,
            "wifi_working": True,
        }
    ]
    output = format_status(statuses)
    assert "Bedroom" in output
    assert "Standby" in output


def test_format_status_none_sensors_omitted():
    """Sensors that are None should not appear in output."""
    statuses = [
        {
            "name": "Test",
            "model": "Blueair Blue Pure 411i Max",
            "pm1": None,
            "pm2_5": 5,
            "pm10": None,
            "total_voc": None,
            "voc": None,
            "temperature": None,
            "humidity": None,
            "fan_speed": 50,
            "fan_auto_mode": False,
            "standby": False,
            "night_mode": False,
            "germ_shield": None,
            "brightness": 3,
            "child_lock": False,
            "filter_usage_percentage": 90,
            "wifi_working": True,
        }
    ]
    output = format_status(statuses)
    assert "PM2.5 5" in output
    assert "PM1" not in output
    assert "PM10" not in output
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/blueair/test_status.py -v`
Expected: FAIL (ImportError)

**Step 3: Write implementation**

```python
# climate/blueair/status.py


def _c_to_f(celsius: int | None) -> float | None:
    """Convert Celsius to Fahrenheit. BlueAir API returns Celsius integers."""
    if celsius is None:
        return None
    return round(celsius * 9 / 5 + 32)


def format_status(statuses: list[dict]) -> str:
    lines = []

    for s in statuses:
        name = s["name"]
        # Shorten model name for display
        model = s["model"].replace("Blueair ", "")
        lines.append(f"{name} ({model})")

        if s.get("standby"):
            lines.append("  Standby")
            if s["filter_usage_percentage"] is not None:
                lines.append(f"  Filter: {s['filter_usage_percentage']}% remaining")
            lines.append("")
            continue

        # Air quality
        aq_parts = []
        if s["pm2_5"] is not None:
            aq_parts.append(f"PM2.5 {s['pm2_5']}")
        if s["pm1"] is not None:
            aq_parts.append(f"PM1 {s['pm1']}")
        if s["pm10"] is not None:
            aq_parts.append(f"PM10 {s['pm10']}")
        if s["total_voc"] is not None:
            aq_parts.append(f"VOC {s['total_voc']}")
        elif s["voc"] is not None:
            aq_parts.append(f"VOC {s['voc']}")
        if aq_parts:
            lines.append(f"  Air Quality: {', '.join(aq_parts)}")

        # Environment
        env_parts = []
        temp_f = _c_to_f(s["temperature"])
        if temp_f is not None:
            env_parts.append(f"{temp_f}°F")
        if s["humidity"] is not None:
            env_parts.append(f"{s['humidity']}% humidity")
        if env_parts:
            lines.append(f"  Environment: {', '.join(env_parts)}")

        # Fan
        fan_mode = "Auto" if s["fan_auto_mode"] else "Manual"
        if s["night_mode"]:
            fan_mode = "Night"
        fan_speed = s["fan_speed"]
        lines.append(f"  Fan: {fan_mode}, speed {fan_speed}%")

        # Filter
        if s["filter_usage_percentage"] is not None:
            lines.append(f"  Filter: {s['filter_usage_percentage']}% remaining")

        # Settings
        settings_parts = []
        brightness = s.get("brightness")
        if brightness is not None:
            settings_parts.append(f"LED: {'off' if brightness == 0 else brightness}")
        if s.get("child_lock"):
            settings_parts.append("Child Lock: on")
        if s.get("germ_shield"):
            settings_parts.append("Germ Shield: on")
        if settings_parts:
            lines.append(f"  {', '.join(settings_parts)}")

        lines.append("")

    return "\n".join(lines).rstrip()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/climate/blueair/test_status.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add climate/blueair/status.py tests/climate/blueair/test_status.py
git commit -m "feat(blueair): status formatter for human-readable purifier output"
```

---

### Task 6: CLI entry point

**Files:**
- Create: `climate/blueair_cli.py`
- Create: `climate/blueair/__main__.py` (for `python -m climate.blueair_cli` isn't a package, we use `climate/blueair_cli.py` directly, but also support `-m`)

**Step 1: Write CLI**

```python
# climate/blueair_cli.py
import argparse
import asyncio
import json
import sys
from pathlib import Path

from climate.blueair import auth
from climate.blueair.client import discover_devices, get_device_status
from climate.blueair.devices import (
    DEFAULT_PURIFIERS_PATH,
    get_managed_purifiers,
    load_purifiers,
)
from climate.blueair.status import format_status

import yaml


def cmd_auth(args) -> None:
    username = input("BlueAir account email: ").strip()
    if not username:
        print("Email is required.")
        sys.exit(1)

    password = input("BlueAir account password: ").strip()
    if not password:
        print("Password is required.")
        sys.exit(1)

    region = input("Region (us/eu/cn/au) [us]: ").strip() or "us"
    if region not in ("us", "eu", "cn", "au"):
        print(f"Invalid region: {region}")
        sys.exit(1)

    print("Validating credentials...")
    try:
        devices, api = asyncio.run(discover_devices(username, password, region))
        asyncio.run(api.cleanup_client_session())
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    auth.store_credentials(username, password, region)
    print(f"Credentials saved to Keychain. Found {len(devices)} device(s).")


def cmd_discover(args) -> None:
    username, password, region = auth.get_credentials()

    print("Discovering devices...")
    devices, api = asyncio.run(discover_devices(username, password, region))
    asyncio.run(api.cleanup_client_session())

    if not devices:
        print("No devices found on this account.")
        return

    print(f"\nFound {len(devices)} device(s):\n")
    purifiers_data = {"purifiers": {}}
    for device in devices:
        name = device.name or device.name_api
        print(f"  {name}")
        print(f"    UUID: {device.uuid}")
        print(f"    Model: {device.model}")
        print(f"    SKU: {device.sku}")
        print(f"    MAC: {device.mac}")
        print()
        purifiers_data["purifiers"][name] = {
            "uuid": device.uuid,
            "managed": True,
        }

    purifiers_path = Path(args.purifiers)
    if purifiers_path.exists():
        print(f"Registry exists at {purifiers_path}. Not overwriting.")
        print("Edit it manually to add/remove devices.")
    else:
        with open(purifiers_path, "w") as f:
            f.write("# climate/config/purifiers.yaml\n")
            f.write("# managed: true  = included in status and automation\n")
            f.write("# managed: false = registered but excluded\n\n")
            yaml.dump(purifiers_data, f, default_flow_style=False, sort_keys=False)
        print(f"Wrote device registry to {purifiers_path}")


def cmd_status(args) -> None:
    username, password, region = auth.get_credentials()
    data = load_purifiers(args.purifiers)
    managed = get_managed_purifiers(data)

    if not managed:
        print("No managed purifiers in purifiers.yaml.")
        sys.exit(1)

    statuses, api = asyncio.run(
        get_device_status(username, password, region, managed)
    )
    asyncio.run(api.cleanup_client_session())

    if not statuses:
        print("No status data returned. Check that device UUIDs are correct.")
        sys.exit(1)

    if args.json:
        print(json.dumps(statuses, indent=2))
    else:
        print(format_status(statuses))


def main():
    parser = argparse.ArgumentParser(
        prog="climate-blueair",
        description="BlueAir air purifier management",
    )
    subparsers = parser.add_subparsers(dest="command")

    # auth
    subparsers.add_parser("auth", help="Store BlueAir credentials in Keychain")

    # discover
    discover_parser = subparsers.add_parser(
        "discover", help="List devices and create purifiers.yaml"
    )
    discover_parser.add_argument(
        "--purifiers",
        type=Path,
        default=DEFAULT_PURIFIERS_PATH,
        metavar="PATH",
        help="Path to purifiers YAML",
    )

    # status
    status_parser = subparsers.add_parser(
        "status", help="Show purifier sensor data and state"
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    status_parser.add_argument(
        "--purifiers",
        type=Path,
        default=DEFAULT_PURIFIERS_PATH,
        metavar="PATH",
        help="Path to purifiers YAML",
    )

    subparsers.choices["auth"].set_defaults(func=cmd_auth)
    subparsers.choices["discover"].set_defaults(func=cmd_discover)
    subparsers.choices["status"].set_defaults(func=cmd_status)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
```

**Step 2: Verify CLI help works**

Run: `uv run python climate/blueair_cli.py --help`
Expected: Shows usage with auth, discover, status subcommands

Run: `uv run python climate/blueair_cli.py status --help`
Expected: Shows --json and --purifiers options

**Step 3: Commit**

```bash
git add climate/blueair_cli.py
git commit -m "feat(blueair): CLI entry point with auth, discover, status commands"
```

---

### Task 7: Justfile tasks + test __init__ files

**Files:**
- Modify: `Justfile`
- Create: `tests/climate/__init__.py` (if missing)
- Create: `tests/climate/blueair/__init__.py` (if missing)

**Step 1: Add `__init__.py` files for test packages if needed**

Create empty `tests/climate/__init__.py` and `tests/climate/blueair/__init__.py` if they don't exist. (Needed for pytest to find the test modules.)

**Step 2: Add Justfile tasks**

Append to `Justfile`:

```just
# Store BlueAir credentials in Keychain
blueair-auth:
    uv run python climate/blueair_cli.py auth

# Discover BlueAir devices and create purifiers.yaml
blueair-discover *ARGS:
    uv run python climate/blueair_cli.py discover {{ARGS}}

# Show purifier status (sensor data, fan, filter life)
blueair-status *ARGS:
    uv run python climate/blueair_cli.py status {{ARGS}}
```

**Step 3: Verify just tasks list**

Run: `just --list`
Expected: `blueair-auth`, `blueair-discover`, `blueair-status` appear in the list

**Step 4: Run all tests**

Run: `uv run pytest tests/climate/blueair/ -v`
Expected: All tests pass (9 total across auth, devices, client, status)

**Step 5: Commit**

```bash
git add Justfile tests/climate/__init__.py tests/climate/blueair/__init__.py
git commit -m "feat(blueair): Justfile tasks and test package init"
```

---

### Task 8: Manual smoke test: auth + discover + status

This is the live validation. Requires real BlueAir credentials.

**Step 1: Authenticate**

Run: `just blueair-auth`
Expected: Prompts for email/password/region, validates, saves to Keychain

**Step 2: Discover devices**

Run: `just blueair-discover`
Expected: Lists your 411i Max with UUID/model/SKU, creates `climate/config/purifiers.yaml`

**Step 3: Check status**

Run: `just blueair-status`
Expected: Shows air quality, fan state, filter life for managed purifiers

Run: `just blueair-status --json`
Expected: Raw JSON with all fields (useful to see which sensors the 411i Max actually reports)

**Step 4: Commit the registry**

```bash
git add climate/config/purifiers.yaml
git commit -m "feat(blueair): add purifier device registry"
```
