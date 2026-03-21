#!/usr/bin/env python3
"""
lutron_cli.py — Lutron Caseta CLI

Usage:
    uv run lighting/lutron_cli.py devices         # list all devices with state
    uv run lighting/lutron_cli.py status           # quick on/off overview
    uv run lighting/lutron_cli.py on <device>      # turn on (name or ID)
    uv run lighting/lutron_cli.py off <device>     # turn off
    uv run lighting/lutron_cli.py set <device> <value>  # dimmer 0-100 or fan speed
"""

import argparse
import asyncio
import sys

from lighting import connect
from lighting.caseta import cmd_devices, cmd_status, cmd_on, cmd_off, cmd_set


async def run(args):
    bridge = await connect()
    try:
        if args.command == "devices":
            await cmd_devices(bridge)
        elif args.command == "status":
            await cmd_status(bridge)
        elif args.command == "on":
            await cmd_on(bridge, args.device)
        elif args.command == "off":
            await cmd_off(bridge, args.device)
        elif args.command == "set":
            await cmd_set(bridge, args.device, args.value)
    finally:
        await bridge.close()


def main():
    parser = argparse.ArgumentParser(description="Lutron Caseta CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="List all devices with current state")
    sub.add_parser("status", help="Quick on/off status overview")

    p_on = sub.add_parser("on", help="Turn on a device")
    p_on.add_argument("device", help="Device name (partial match) or ID")

    p_off = sub.add_parser("off", help="Turn off a device")
    p_off.add_argument("device", help="Device name (partial match) or ID")

    p_set = sub.add_parser("set", help="Set dimmer level (0-100) or fan speed")
    p_set.add_argument("device", help="Device name (partial match) or ID")
    p_set.add_argument("value", help="0-100 for dimmers, off/low/medium/high for fans")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
