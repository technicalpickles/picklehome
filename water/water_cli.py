#!/usr/bin/env python3
"""water_cli.py -- Moen Flo smart shutoff valve CLI. Read-only.

Usage:
    uv run python water/water_cli.py status [--json]
    uv run python water/water_cli.py device --raw [--unredacted]
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from water.flo.auth import MoenFloConfigError
from water.flo.client import FloValve, MoenFloError, fetch_raw, parse_valve, with_api
from water.flo.scrub import scrub_payload


def _num(value, suffix: str, fmt: str = "{:.0f}") -> str:
    """Render a telemetry value, keeping 'no reading' distinct from a real zero."""
    return "no reading" if value is None else f"{fmt.format(value)} {suffix}"


def format_status(valve: FloValve) -> str:
    if valve.pending_alerts is None:
        alerts = "unknown"
    elif valve.pending_alerts == 0:
        alerts = "none"
    else:
        alerts = f"{valve.pending_alerts} pending"

    if valve.connected is None:
        link = _num(valve.rssi, "dBm")
    else:
        link = f"{_num(valve.rssi, 'dBm')} ({'connected' if valve.connected else 'disconnected'})"

    flow = _num(valve.gpm, "gpm", "{:.1f}")
    if valve.telemetry_updated:
        # The reading can be hours stale even while the device is connected
        # (see FloValve.telemetry_updated); surface the timestamp right next
        # to the numbers it belongs to rather than burying it in --json only.
        flow = f"{flow} (as of {valve.telemetry_updated})"

    lines = [
        f"Flo — {valve.name:<24} {valve.state}",
        f"  flow        {flow}",
        f"  pressure    {_num(valve.psi, 'psi')}",
        f"  temp        {_num(valve.temp_f, '°F')}",
        f"  mode        {valve.mode or 'unknown'}",
        f"  wifi        {link}",
        f"  alerts      {alerts}",
    ]
    return "\n".join(lines)


async def cmd_status(json_output: bool) -> None:
    async with with_api() as api:
        payload = await fetch_raw(api)

    valves = [parse_valve(device) for device in payload["devices"]]

    if json_output:
        print(json.dumps([asdict(v) for v in valves], indent=2))
        return

    if not valves:
        print("No Flo devices on this account.")
        return

    print("\n\n".join(format_status(v) for v in valves))


async def cmd_device(unredacted: bool) -> None:
    async with with_api() as api:
        payload = await fetch_raw(api)

    if unredacted:
        # Deliberately unredacted: printed to stderr so it can't be missed
        # even when stdout is redirected to a file, which is the whole point
        # of --raw in the first place.
        print(
            "warning: --unredacted output contains the account email, device "
            "MAC address, serial number, street address, and GPS coordinates. "
            "Do not paste this into an issue, chat, or agent session.",
            file=sys.stderr,
        )
    else:
        payload = scrub_payload(payload)

    print(json.dumps(payload, indent=2, default=str))


async def run(args: argparse.Namespace) -> None:
    if args.command == "status":
        await cmd_status(args.json)
    elif args.command == "device":
        await cmd_device(args.unredacted)


def main() -> None:
    parser = argparse.ArgumentParser(description="Moen Flo shutoff valve CLI (read-only)")
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser("status", help="Valve state, flow, pressure, alerts")
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")

    device_parser = sub.add_parser("device", help="Raw API dump")
    device_parser.add_argument(
        "--raw", action="store_true", help="Print the API JSON (redacted by default)"
    )
    device_parser.add_argument(
        "--unredacted",
        action="store_true",
        help="Skip redaction -- includes email, MAC, serial, address, and coordinates",
    )

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
