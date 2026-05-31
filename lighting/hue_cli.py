#!/usr/bin/env python3
"""
hue_cli.py: Philips Hue CLI

Usage:
    uv run lighting/hue_cli.py pair [<host>]      # one-time bridge pairing
    uv run lighting/hue_cli.py lights              # list all lights with state
    uv run lighting/hue_cli.py sensors             # motion sensors with status
    uv run lighting/hue_cli.py buttons             # tap buttons with last event
    uv run lighting/hue_cli.py scenes              # scenes by room
    uv run lighting/hue_cli.py groups              # rooms/zones with members
    uv run lighting/hue_cli.py on <light>          # turn on (partial match)
    uv run lighting/hue_cli.py off <light>         # turn off
    uv run lighting/hue_cli.py set <light> <bri>   # brightness 0-100%
    uv run lighting/hue_cli.py scene <scene>       # activate a scene
    uv run lighting/hue_cli.py status              # overview
"""

import argparse
import asyncio

from lighting.hue import cmd_pair


async def run(args):
    if args.command == "pair":
        await cmd_pair(args.host)
        return

    # All other commands need a connected bridge
    from lighting.hue import connect
    bridge = await connect()
    try:
        from lighting import hue as hue_cmds
        if args.command == "lights":
            await hue_cmds.cmd_lights(bridge)
        elif args.command == "sensors":
            await hue_cmds.cmd_sensors(bridge)
        elif args.command == "buttons":
            await hue_cmds.cmd_buttons(bridge)
        elif args.command == "scenes":
            await hue_cmds.cmd_scenes(bridge)
        elif args.command == "groups":
            await hue_cmds.cmd_groups(bridge)
        elif args.command == "on":
            await hue_cmds.cmd_on(bridge, args.light)
        elif args.command == "off":
            await hue_cmds.cmd_off(bridge, args.light)
        elif args.command == "set":
            await hue_cmds.cmd_set(bridge, args.light, args.brightness)
        elif args.command == "scene":
            await hue_cmds.cmd_scene(bridge, args.scene)
        elif args.command == "status":
            await hue_cmds.cmd_status(bridge)
    finally:
        await bridge.close()


def main():
    parser = argparse.ArgumentParser(description="Philips Hue CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pair = sub.add_parser("pair", help="One-time bridge pairing")
    p_pair.add_argument("host", nargs="?", help="Bridge IP (or use HUE_BRIDGE_IP)")

    sub.add_parser("lights", help="List all lights with state")
    sub.add_parser("sensors", help="List motion sensors with status")
    sub.add_parser("buttons", help="List tap buttons with last event")
    sub.add_parser("scenes", help="List scenes by room")
    sub.add_parser("groups", help="List rooms/zones with members")
    sub.add_parser("status", help="Overview: lights, scenes, motion")

    p_on = sub.add_parser("on", help="Turn on a light")
    p_on.add_argument("light", help="Light name (partial match) or ID")

    p_off = sub.add_parser("off", help="Turn off a light")
    p_off.add_argument("light", help="Light name (partial match) or ID")

    p_set = sub.add_parser("set", help="Set brightness (0-100)")
    p_set.add_argument("light", help="Light name (partial match) or ID")
    p_set.add_argument("brightness", help="0-100")

    p_scene = sub.add_parser("scene", help="Activate a scene")
    p_scene.add_argument("scene", help="Scene name (partial match)")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
