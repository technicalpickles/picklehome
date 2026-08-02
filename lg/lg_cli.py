#!/usr/bin/env python3
"""
lg_cli.py -- LG ThinQ (washer, dryer, refrigerator) CLI. Read-only.

Usage:
    uv run python lg/lg_cli.py status              # one line per device
    uv run python lg/lg_cli.py laundry [--json]    # washer + dryer detail
    uv run python lg/lg_cli.py fridge [--json]     # refrigerator detail
    uv run python lg/lg_cli.py devices [--raw] [--json]  # inventory, or an unmassaged API dump
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from lg.thinq import auth
from lg.thinq.client import (
    DEVICE_TYPE_DRYER,
    DEVICE_TYPE_REFRIGERATOR,
    DEVICE_TYPE_WASHER,
    DeviceRef,
    Laundry,
    LGThinQAuthError,
    LGThinQError,
    LGThinQRateLimitError,
    Refrigerator,
    get_appliances,
    get_raw_dump,
    list_devices,
)
from lg.thinq.auth import LGThinQConfigError
from lg.thinq.observations import append_observation, find_counter_increment, read_observations

LOG_PATH = Path.home() / ".local" / "state" / "picklehome" / "lg-observations.jsonl"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _fmt_clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def _state_label(state: str) -> str:
    if state == "POWER_OFF":
        return "off"
    if state == "UNKNOWN":
        return "unknown"
    return state.lower()


def _describe_failure(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    if isinstance(exc, LGThinQAuthError):
        return "auth error"
    if isinstance(exc, LGThinQRateLimitError):
        return "rate limited"
    return str(exc)


# ---------------------------------------------------------------------------
# Observation logging
# ---------------------------------------------------------------------------


def _log_result(device: DeviceRef, result: Laundry | Refrigerator | BaseException) -> None:
    """Append what we just observed. Warns (stderr) but never fails the command.

    Both field extraction and the write itself are inside the try/except --
    not just the write -- so a shape mismatch on `result` (e.g. Refrigerator
    has no `.state`, which used to crash every fridge command) degrades to a
    stderr warning like any other logging failure, rather than propagating
    out of the command.
    """
    if isinstance(result, BaseException):
        return

    try:
        fields: dict = {}
        if isinstance(result, Laundry):
            fields["state"] = result.state
            fields["active"] = result.active
            if result.cycle_count is not None:
                fields["cycle_count"] = result.cycle_count
        elif isinstance(result, Refrigerator):
            # No completion-detection use for the fridge today (no counter,
            # no watcher), but door_state is a cheap, honest thing to record
            # for whatever reads this log next.
            fields["door_state"] = result.door_state

        append_observation(LOG_PATH, device.device_id, datetime.now().astimezone(), fields)
    except Exception as e:
        print(f"warning: failed to write observation log ({LOG_PATH}): {e}", file=sys.stderr)


def _last_cycle_line(device: DeviceRef, laundry: Laundry) -> str | None:
    """'Last cycle: finished N ago' for an idle washer, honoring the degradation rules.

    Dryer never gets this line -- it has no cycle counter (module docstring /
    design doc "Completion detection" section). Washer only gets it while
    idle (a currently-running washer doesn't need "when did it last finish"),
    and PAUSE is excluded even though PAUSE is not "active": a paused washer
    mid-load showing "Last cycle: finished ..." directly under "State: pause"
    reads as if the *current* load just ended, when it refers to the
    previous one.
    """
    if (
        laundry.appliance != "washer"
        or laundry.active
        or laundry.state == "PAUSE"
        or laundry.cycle_count is None
    ):
        return None

    try:
        records = read_observations(LOG_PATH)
    except OSError as e:
        print(f"warning: failed to read observation log ({LOG_PATH}): {e}", file=sys.stderr)
        return None

    estimate = find_counter_increment(
        records,
        device.device_id,
        "cycle_count",
        laundry.cycle_count,
        now=datetime.now().astimezone(),
    )
    if estimate is None:
        return None
    return estimate.describe()


# ---------------------------------------------------------------------------
# Fetch + gather
# ---------------------------------------------------------------------------


async def _fetch(device_types: set[str]) -> list[tuple[DeviceRef, Laundry | Refrigerator | BaseException]]:
    api, session = await auth.connect()
    try:
        devices = await list_devices(api)
        relevant = [d for d in devices if d.device_type in device_types]
        results = await get_appliances(api, relevant)
    finally:
        await session.close()

    for device, result in results:
        _log_result(device, result)
    return results


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _status_dict(device: DeviceRef, result: Laundry | Refrigerator | BaseException) -> dict:
    if isinstance(result, BaseException):
        return {"device_id": device.device_id, "name": device.alias, "error": _describe_failure(result)}
    return asdict(result)


def _print_status_line(device: DeviceRef, result: Laundry | Refrigerator | BaseException) -> None:
    if isinstance(result, BaseException):
        print(f"{device.alias:<16} unavailable ({_describe_failure(result)})")
        return

    if isinstance(result, Laundry):
        if not result.active:
            print(f"{device.alias:<16} {_state_label(result.state)}")
            return
        extra = f"{_fmt_minutes(result.remain_minutes)} left" if result.remain_minutes is not None else "calculating"
        print(f"{device.alias:<16} {_state_label(result.state):<10} {extra}")
        return

    # Refrigerator
    print(f"{device.alias:<16} {'ok':<10} door {result.door_state}")


async def cmd_status(json_output: bool) -> None:
    results = await _fetch({DEVICE_TYPE_WASHER, DEVICE_TYPE_DRYER, DEVICE_TYPE_REFRIGERATOR})
    if not results:
        print("No devices found.")
        return
    if json_output:
        print(json.dumps([_status_dict(d, r) for d, r in results], indent=2, default=str))
        return
    for device, result in results:
        _print_status_line(device, result)


# ---------------------------------------------------------------------------
# laundry
# ---------------------------------------------------------------------------


def _print_laundry_detail(device: DeviceRef, result: Laundry | BaseException) -> None:
    print(f"{device.alias} ({device.model})")
    if isinstance(result, BaseException):
        print(f"  unavailable ({_describe_failure(result)})")
        print()
        return

    print(f"  State:      {_state_label(result.state)}")
    if result.active:
        if result.remain_minutes is not None:
            remaining = _fmt_minutes(result.remain_minutes)
            total = f"  (of {_fmt_minutes(result.total_minutes)})" if result.total_minutes else ""
            print(f"  Remaining:  {remaining}{total}")
            ends = datetime.now().astimezone() + timedelta(minutes=result.remain_minutes)
            print(f"  Ends:       ~{_fmt_clock(ends)}")
        else:
            print("  Remaining:  calculating...")
        print(f"  Remote:     {'available now' if result.remote_available else 'not available now'}")
    else:
        last_cycle = _last_cycle_line(device, result)
        if last_cycle:
            print(f"  Last cycle: {last_cycle}")

    if result.cycle_count is not None:
        print(f"  Cycles:     {result.cycle_count}")
    print()


async def cmd_laundry(json_output: bool) -> None:
    results = await _fetch({DEVICE_TYPE_WASHER, DEVICE_TYPE_DRYER})
    if not results:
        print("No washer or dryer found.")
        return
    if json_output:
        print(json.dumps([_status_dict(d, r) for d, r in results], indent=2, default=str))
        return
    for device, result in results:
        _print_laundry_detail(device, result)


# ---------------------------------------------------------------------------
# fridge
# ---------------------------------------------------------------------------


def _print_fridge_detail(device: DeviceRef, result: Refrigerator | BaseException) -> None:
    print(f"{device.alias} ({device.model})")
    if isinstance(result, BaseException):
        print(f"  unavailable ({_describe_failure(result)})")
        return

    # Both are setpoints (targetTemperature), never a measured air
    # temperature -- the label is not optional. See client.py module
    # docstring point 7. The unit comes from the payload itself (not
    # hardcoded) -- the profile declares Celsius ranges even though this
    # account's status has always reported Fahrenheit so far.
    fridge = (
        f"{result.fridge_setpoint} {result.fridge_setpoint_unit}  (setpoint)"
        if result.fridge_setpoint is not None
        else "unknown"
    )
    freezer = (
        f"{result.freezer_setpoint} {result.freezer_setpoint_unit}  (setpoint)"
        if result.freezer_setpoint is not None
        else "unknown"
    )
    print(f"  Fridge:   {fridge}")
    print(f"  Freezer:  {freezer}")
    print(f"  Door:     {result.door_state}")
    modes = f"power save {'on' if result.power_save else 'off'}, express freeze {'on' if result.express_mode else 'off'}"
    print(f"  Modes:    {modes}")


async def cmd_fridge(json_output: bool) -> None:
    results = await _fetch({DEVICE_TYPE_REFRIGERATOR})
    if not results:
        print("No refrigerator found.")
        return
    if json_output:
        print(json.dumps([_status_dict(d, r) for d, r in results], indent=2, default=str))
        return
    for device, result in results:
        _print_fridge_detail(device, result)


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------


async def cmd_devices(raw: bool, json_output: bool) -> None:
    api, session = await auth.connect()
    try:
        devices = await list_devices(api)
        if not devices:
            print("No devices found.")
            return

        if raw:
            dumps = await asyncio.gather(*(get_raw_dump(api, d) for d in devices), return_exceptions=True)
            output = []
            for device, dump in zip(devices, dumps):
                if isinstance(dump, BaseException):
                    output.append({"device_id": device.device_id, "alias": device.alias, "error": str(dump)})
                else:
                    output.append(dump)
            print(json.dumps(output, indent=2, default=str))
            return

        if json_output:
            print(json.dumps([asdict(d) for d in devices], indent=2))
            return

        for device in devices:
            print(f"{device.alias:<20} {device.device_type:<22} {device.model}")
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# argparse + main
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> None:
    if args.command == "status":
        await cmd_status(args.json)
    elif args.command == "laundry":
        await cmd_laundry(args.json)
    elif args.command == "fridge":
        await cmd_fridge(args.json)
    elif args.command == "devices":
        await cmd_devices(args.raw, args.json)


def main() -> None:
    parser = argparse.ArgumentParser(description="LG ThinQ (washer, dryer, refrigerator) CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser("status", help="One line per device: state, time remaining")
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")

    laundry_parser = sub.add_parser("laundry", help="Washer + dryer detail")
    laundry_parser.add_argument("--json", action="store_true", help="Output as JSON")

    fridge_parser = sub.add_parser("fridge", help="Refrigerator detail: setpoints, door, modes")
    fridge_parser.add_argument("--json", action="store_true", help="Output as JSON")

    devices_parser = sub.add_parser("devices", help="Device inventory, or the raw API dump")
    devices_parser.add_argument("--raw", action="store_true", help="Print unmassaged profile + status JSON per device")
    devices_parser.add_argument("--json", action="store_true", help="Output inventory as JSON (ignored with --raw)")

    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (LGThinQConfigError, LGThinQError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
