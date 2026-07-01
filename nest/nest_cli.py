#!/usr/bin/env python3
"""
nest_cli.py -- Nest/Google SDM device CLI

Usage:
    uv run python nest/nest_cli.py auth              # authorize device access, save tokens
    uv run python nest/nest_cli.py status             # one-line summary per device, grouped by location
    uv run python nest/nest_cli.py status <name>       # detailed view for a device (substring match)
"""

import argparse
import asyncio
import sys

from nest.locations import group_devices
from nest.sdm.auth import NestAuthError, login
from nest.sdm.client import NestDevice, SDMError, get_devices, get_structures
from picklehome.locations import resolve_locations

USE_COLOR = sys.stdout.isatty()


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m" if USE_COLOR else s


def _celsius_to_f(c: float | None) -> float | None:
    return None if c is None else c * 9 / 5 + 32


def _format_temp(c: float | None) -> str:
    f = _celsius_to_f(c)
    return f"{f:.1f}°F" if f is not None else "--"


def _format_one_line(device: NestDevice, name_width: int) -> str:
    name = device.custom_name.ljust(name_width)
    status = (device.connectivity or "unknown").lower().ljust(8)
    if device.device_type == "THERMOSTAT":
        detail = f"{(device.mode or 'unknown').lower()}  temp {_format_temp(device.ambient_temperature_c)}"
        if device.setpoint_heat_c is not None:
            detail += f"  heat→{_format_temp(device.setpoint_heat_c)}"
        if device.setpoint_cool_c is not None:
            detail += f"  cool→{_format_temp(device.setpoint_cool_c)}"
    else:
        detail = device.device_type.lower() + (", live stream" if device.has_live_stream else "")
    return f"  {name}  {status}  {detail}"


def _print_group(label: str, devices: list[NestDevice]) -> None:
    print(_bold(label))
    print("═" * len(label))
    width = max((len(d.custom_name) for d in devices), default=4)
    for device in sorted(devices, key=lambda d: d.custom_name):
        print(_format_one_line(device, width))
    print()


async def cmd_auth() -> None:
    print("Authorizing Nest device access...")
    await login()
    print("Authorization successful! Tokens saved.")
    devices = await get_devices()
    print(f"\nFound {len(devices)} device(s):")
    for device in devices:
        print(f"  {device.custom_name} ({device.device_type.lower()})")


async def cmd_status(name_filter: str | None, location_slug: str | None) -> None:
    structures = await get_structures()
    structure_names_by_id = {s.id: s.custom_name for s in structures}
    devices = await get_devices()

    if not devices:
        print("No devices found.")
        return

    if name_filter:
        needle = name_filter.lower()
        matches = [d for d in devices if needle in d.custom_name.lower()]
        if not matches:
            print(f"No device matching {name_filter!r}.")
            print(f"Known devices: {', '.join(sorted(d.custom_name for d in devices))}")
            sys.exit(1)
        _print_group(name_filter, matches)
        return

    if location_slug:
        try:
            loc = resolve_locations(location_slug)[0]
        except RuntimeError as e:
            print(e)
            sys.exit(1)
        names = {s.strip().lower() for s in loc.nest_structures}
        matches = [
            d for d in devices
            if structure_names_by_id.get(d.structure_id, "").strip().lower() in names
        ]
        if not matches:
            # Valid slug, just no devices there -- not an error.
            print(f"No devices at {loc.label}.")
            return
        _print_group(loc.label, matches)
        return

    for group in group_devices(devices, structure_names_by_id):
        _print_group(group.label, group.devices)


async def run(args) -> None:
    if args.command == "auth":
        await cmd_auth()
    elif args.command == "status":
        await cmd_status(args.name, args.location)


def main() -> None:
    parser = argparse.ArgumentParser(description="Nest/Google SDM device CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Authorize device access and save tokens")
    status = sub.add_parser("status", help="Show device status")
    status.add_argument("name", nargs="?", help="Show detailed view for a device (substring match on name)")
    status.add_argument(
        "--location",
        metavar="SLUG",
        default=None,
        help="Limit to one location by slug (default: all locations, grouped)",
    )

    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (NestAuthError, SDMError) as e:
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
