#!/usr/bin/env python3
"""water_cli.py -- Moen Flo smart shutoff valve CLI. Read-only.

Usage:
    uv run python water/water_cli.py device --raw
"""

import argparse
import asyncio
import json
import sys

from water.flo.auth import MoenFloConfigError
from water.flo.client import MoenFloError, fetch_raw, with_api


async def cmd_device() -> None:
    async with with_api() as api:
        payload = await fetch_raw(api)
    print(json.dumps(payload, indent=2, default=str))


async def run(args: argparse.Namespace) -> None:
    if args.command == "device":
        await cmd_device()


def main() -> None:
    parser = argparse.ArgumentParser(description="Moen Flo shutoff valve CLI (read-only)")
    sub = parser.add_subparsers(dest="command", required=True)

    device_parser = sub.add_parser("device", help="Raw API dump")
    device_parser.add_argument("--raw", action="store_true", help="Print the unmassaged API JSON")

    args = parser.parse_args()
    if args.command == "device" and not args.raw:
        parser.error("water device currently supports only --raw")

    try:
        asyncio.run(run(args))
    except (MoenFloConfigError, MoenFloError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
