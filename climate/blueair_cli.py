import argparse
import asyncio
import getpass
import sys
from pathlib import Path

import yaml

from climate.blueair.auth import get_credentials, store_credentials
from climate.blueair.client import discover_devices, get_device_status
from climate.blueair.devices import DEFAULT_PURIFIERS_PATH, get_managed_purifiers, load_purifiers
from climate.blueair.status import format_status


def cmd_auth(args) -> None:
    email = input("BlueAir email: ")
    password = getpass.getpass("BlueAir password: ")
    region = input("Region [us]: ").strip() or "us"

    print("Validating credentials...")
    try:
        devices, api = asyncio.run(discover_devices(email, password, region))
    except Exception as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    asyncio.run(api.cleanup_client_session())

    store_credentials(email, password, region)
    print(f"Credentials stored. Found {len(devices)} device(s).")


def cmd_discover(args) -> None:
    username, password, region = get_credentials()

    devices, api = asyncio.run(discover_devices(username, password, region))

    print(f"Found {len(devices)} device(s):\n")
    for device in devices:
        print(f"  Name:  {device.name}")
        print(f"  UUID:  {device.uuid}")
        print(f"  Model: {device.model}")
        print(f"  SKU:   {device.sku}")
        print(f"  MAC:   {device.mac}")
        print()

    purifiers_path = args.purifiers
    if purifiers_path.exists():
        print(f"Registry exists, not overwriting: {purifiers_path}")
    else:
        registry = {"purifiers": {}}
        for device in devices:
            key = device.name.lower().replace(" ", "_")
            registry["purifiers"][key] = {
                "uuid": device.uuid,
                "model": str(device.model.value) if device.model else None,
                "sku": device.sku,
                "mac": device.mac,
                "managed": True,
            }
        purifiers_path.parent.mkdir(parents=True, exist_ok=True)
        with open(purifiers_path, "w") as f:
            yaml.dump(registry, f, default_flow_style=False, sort_keys=False)
        print(f"Purifier registry written to {purifiers_path}")

    asyncio.run(api.cleanup_client_session())


def cmd_status(args) -> None:
    username, password, region = get_credentials()

    data = load_purifiers(args.purifiers)
    managed = get_managed_purifiers(data)

    if not managed:
        print("No managed purifiers found. Run discover first.")
        sys.exit(1)

    statuses, api = asyncio.run(get_device_status(username, password, region, managed))

    if args.json:
        import json
        print(json.dumps({"purifiers": statuses}, indent=2, default=str))
    else:
        print(format_status(statuses))

    asyncio.run(api.cleanup_client_session())


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
