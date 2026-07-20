"""CLI for Hisense ductless HVAC via ConnectLife.

    just hisense status [name] [--json]
    just hisense set <name> [--power on/off] [--mode MODE] [--temp F] [--fan SPEED]

`name` is a case-insensitive substring matched against unit name and room, so
`set Bedroom --temp 72` targets every head with "Bedroom" in its name/room.

Each command uses a single asyncio.run(); the ConnectLife client re-authenticates
per invocation (tokens are held in memory only, never persisted).
"""

import argparse
import asyncio
import json
import sys

from climate.hisense.auth import get_credentials
from climate.hisense.client import (
    FAN_CHOICES,
    MODE_CHOICES,
    HisenseError,
    build_control_properties,
    get_units,
    set_unit,
)
from climate.hisense.status import format_status


def _matches(units, name: str):
    q = name.lower()
    return [u for u in units if q in u.name.lower() or q in u.room.lower()]


async def _status(username: str, password: str):
    return await get_units(username, password)


async def _set(username: str, password: str, name: str, properties: dict):
    units = await get_units(username, password)
    matches = _matches(units, name)
    for unit in matches:
        await set_unit(username, password, unit.puid, properties)
    return matches


def cmd_status(args) -> None:
    username, password = get_credentials()
    try:
        units = asyncio.run(_status(username, password))
    except HisenseError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.name:
        units = _matches(units, args.name)

    if args.json:
        print(json.dumps({"units": [u.to_dict() for u in units]}, indent=2, default=str))
    else:
        print(format_status(units))


def cmd_set(args) -> None:
    username, password = get_credentials()

    power = None
    if args.power is not None:
        power = args.power == "on"

    try:
        properties = build_control_properties(
            power=power, mode=args.mode, temp=args.temp, fan=args.fan
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        matches = asyncio.run(_set(username, password, args.name, properties))
    except HisenseError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not matches:
        print(f"No unit matched '{args.name}'.", file=sys.stderr)
        sys.exit(1)

    changes = ", ".join(f"{k}={v}" for k, v in properties.items())
    for unit in matches:
        print(f"{unit.name}: set {changes}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hisense ductless HVAC (ConnectLife)")
    subparsers = parser.add_subparsers(dest="command")

    status_parser = subparsers.add_parser("status", help="Show unit status")
    status_parser.add_argument("name", nargs="?", help="Filter by name/room substring")
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")

    set_parser = subparsers.add_parser("set", help="Control one or more units")
    set_parser.add_argument("name", help="Unit name/room substring to target")
    set_parser.add_argument("--power", choices=["on", "off"], help="Power on/off")
    set_parser.add_argument("--mode", choices=MODE_CHOICES, metavar="MODE",
                            help=f"HVAC mode: {', '.join(MODE_CHOICES)}")
    set_parser.add_argument("--temp", type=int, metavar="F", help="Target temp in Fahrenheit (61-90)")
    set_parser.add_argument("--fan", choices=FAN_CHOICES, metavar="SPEED",
                            help=f"Fan speed: {', '.join(FAN_CHOICES)}")

    subparsers.choices["status"].set_defaults(func=cmd_status)
    subparsers.choices["set"].set_defaults(func=cmd_set)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
