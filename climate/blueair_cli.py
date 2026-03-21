import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

import yaml

from climate.blueair.auth import get_credentials, store_credentials
from climate.blueair.client import SETTABLE_PROPERTIES, discover_devices, get_device_status, set_device_property
from climate.blueair.devices import DEFAULT_PURIFIERS_PATH, get_managed_purifiers, load_purifiers
from climate.blueair.status import format_status


# Each command uses a single asyncio.run() calling one async helper.
# The blueair-api aiohttp session is bound to one event loop — splitting
# work across multiple asyncio.run() calls fails with "Event loop is closed".


async def _auth(email: str, password: str, region: str) -> int:
    """Validate credentials and return device count."""
    devices, api = await discover_devices(email, password, region)
    count = len(devices)
    await api.cleanup_client_session()
    return count


async def _discover(username: str, password: str, region: str):
    """Discover and refresh all devices. Returns list of refreshed devices."""
    devices, api = await discover_devices(username, password, region)
    for device in devices:
        await device.refresh()
    await api.cleanup_client_session()
    return devices


async def _status(username: str, password: str, region: str, managed):
    """Fetch status for managed devices."""
    statuses, api = await get_device_status(username, password, region, managed)
    await api.cleanup_client_session()
    return statuses


def cmd_auth(args) -> None:
    email = input("BlueAir email: ")
    password = getpass.getpass("BlueAir password: ")
    region = input("Region [us]: ").strip() or "us"

    print("Validating credentials...")
    try:
        count = asyncio.run(_auth(email, password, region))
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    store_credentials(email, password, region)
    print(f"Credentials stored. Found {count} device(s).")


def cmd_discover(args) -> None:
    username, password, region = get_credentials()

    print("Discovering devices...")
    devices = asyncio.run(_discover(username, password, region))

    print(f"Found {len(devices)} device(s):\n")
    for device in devices:
        name = device.name or device.name_api
        print(f"  {name}")
        print(f"    UUID:  {device.uuid}")
        print(f"    Model: {device.model}")
        print(f"    SKU:   {device.sku}")
        print()

    purifiers_path = args.purifiers
    if purifiers_path.exists():
        print(f"Registry exists at {purifiers_path} — not overwriting.")
        print("Edit it manually to add/remove devices.")
    else:
        registry = {"purifiers": {}}
        for device in devices:
            name = device.name or device.name_api or device.uuid
            registry["purifiers"][name] = {
                "uuid": device.uuid,
                "managed": True,
            }
        purifiers_path.parent.mkdir(parents=True, exist_ok=True)
        with open(purifiers_path, "w") as f:
            f.write("# climate/config/purifiers.yaml\n")
            f.write("# managed: true  — included in status and automation\n")
            f.write("# managed: false — registered but excluded\n\n")
            yaml.dump(registry, f, default_flow_style=False, sort_keys=False)
        print(f"Wrote device registry to {purifiers_path}")


def cmd_status(args) -> None:
    username, password, region = get_credentials()

    data = load_purifiers(args.purifiers)
    managed = get_managed_purifiers(data)

    if not managed:
        print("No managed purifiers found. Run 'just blueair discover' first.")
        sys.exit(1)

    statuses = asyncio.run(_status(username, password, region, managed))

    if not statuses:
        print("No status data returned. Check that device UUIDs are correct.")
        sys.exit(1)

    if args.json:
        print(json.dumps({"purifiers": statuses}, indent=2, default=str))
    else:
        print(format_status(statuses))


def cmd_set(args) -> None:
    username, password, region = get_credentials()

    data = load_purifiers(args.purifiers)
    managed = get_managed_purifiers(data)

    if not managed:
        print("No managed purifiers found. Run 'just blueair discover' first.")
        sys.exit(1)

    try:
        confirmations = asyncio.run(
            set_device_property(username, password, region, managed, args.property, args.value, args.device)
        )
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not confirmations:
        if args.device:
            print(f"No managed device named '{args.device}'.")
        else:
            print("No devices matched.")
        sys.exit(1)

    for msg in confirmations:
        print(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description="BlueAir purifier management")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("auth", help="Store BlueAir credentials and validate connectivity")

    discover_parser = subparsers.add_parser("discover", help="List devices and create purifiers.yaml")
    discover_parser.add_argument(
        "--purifiers",
        type=Path,
        default=DEFAULT_PURIFIERS_PATH,
        metavar="PATH",
        help=f"Path to purifiers YAML (default: {DEFAULT_PURIFIERS_PATH})",
    )

    status_parser = subparsers.add_parser("status", help="Show current purifier status")
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
        help=f"Path to purifiers YAML (default: {DEFAULT_PURIFIERS_PATH})",
    )

    prop_names = ", ".join(SETTABLE_PROPERTIES)
    set_parser = subparsers.add_parser(
        "set", help=f"Set a device property ({prop_names})"
    )
    set_parser.add_argument("property", choices=SETTABLE_PROPERTIES.keys(), metavar="property",
                            help=f"Property to set: {prop_names}")
    set_parser.add_argument("value", help="Value to set (integer or on/off)")
    set_parser.add_argument("--device", metavar="NAME", help="Target a specific device by name")
    set_parser.add_argument(
        "--purifiers",
        type=Path,
        default=DEFAULT_PURIFIERS_PATH,
        metavar="PATH",
        help=f"Path to purifiers YAML (default: {DEFAULT_PURIFIERS_PATH})",
    )

    subparsers.choices["auth"].set_defaults(func=cmd_auth)
    subparsers.choices["discover"].set_defaults(func=cmd_discover)
    subparsers.choices["status"].set_defaults(func=cmd_status)
    subparsers.choices["set"].set_defaults(func=cmd_set)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
