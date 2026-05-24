#!/usr/bin/env python3
"""
locks_cli.py -- Yale Access lock CLI

Usage:
    uv run python locks/locks_cli.py auth            # login and save tokens
    uv run python locks/locks_cli.py status          # one-line summary per lock
    uv run python locks/locks_cli.py status <name>   # detailed view for a lock
"""

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timezone

from locks.yale.auth import get_credentials, login
from locks.yale.client import HealthSeverity, YaleLock, get_locks
from yalexs.lock import LockDoorStatus, LockStatus


USE_COLOR = sys.stdout.isatty()


def _gray(s: str) -> str:
    return f"\033[90m{s}\033[0m" if USE_COLOR else s


def _red(s: str) -> str:
    return f"\033[31m{s}\033[0m" if USE_COLOR else s


def _yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m" if USE_COLOR else s


def _green(s: str) -> str:
    return f"\033[32m{s}\033[0m" if USE_COLOR else s


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m" if USE_COLOR else s


def _health_glyph(lock: YaleLock) -> str:
    status = lock.health_status
    if status == "healthy":
        return _green("✓")
    if status == "warning":
        return _yellow("⚠")
    return _red("✗")


def _issue_glyph(severity: HealthSeverity) -> str:
    if severity == "warning":
        return _yellow("⚠")
    return _red("✗")


def _format_ago_short(dt: datetime | None) -> str:
    """Compact duration: '24m', '11d', '?'."""
    if dt is None:
        return "?"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((datetime.now(tz=timezone.utc) - dt).total_seconds())
    if secs < 0:
        return "future"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _format_ts(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"{dt.astimezone().strftime('%Y-%m-%d %H:%M %Z')} ({_format_ago_short(dt)} ago)"


def _lock_state_str(lock: YaleLock) -> str:
    if lock.lock_status == LockStatus.LOCKED:
        return "locked"
    if lock.lock_status == LockStatus.UNLOCKED:
        return "unlocked"
    return "unknown"


def _door_state_str(lock: YaleLock) -> str:
    if not lock.doorsense:
        return "n/a"
    if lock.door_state == LockDoorStatus.CLOSED:
        return "closed"
    if lock.door_state == LockDoorStatus.OPEN:
        return "open"
    return "unknown"


def _battery_str(lock: YaleLock) -> str:
    return f"{lock.battery_level}%" if lock.battery_valid else "--"


# Terse cell labels for the bridge column. When offline, encode the
# disambiguated reason so a glance tells you whether the lock or the bridge
# is the broken party. Keep these short -- column width is sized off them.
_BRIDGE_CELL_OFFLINE = {
    "bridge_down":    "bridge?",
    "battery_likely": "battery?",
    "unknown":        "OFFLINE",
}
_BRIDGE_CELL_LABELS = ("no bridge", "online", *_BRIDGE_CELL_OFFLINE.values())


def _bridge_cell(lock: YaleLock) -> tuple[str, str]:
    """Return (label, duration-since) for the bridge column."""
    bridge = lock.bridge
    if bridge is None:
        return ("no bridge", "")
    if bridge.connectivity == "online":
        return ("online", _format_ago_short(bridge.last_online))
    reason = lock.bridge_offline_reason or "unknown"
    return (_BRIDGE_CELL_OFFLINE[reason], _format_ago_short(bridge.last_online))


def _color_bridge_cell(lock: YaleLock, text: str) -> str:
    if lock.bridge is None:
        return _yellow(text)
    if lock.bridge.connectivity == "online":
        return _green(text)
    return _red(text)


def _format_one_line(lock: YaleLock, widths: dict) -> str:
    glyph = _health_glyph(lock)
    name = lock.name.ljust(widths["name"])
    state = _lock_state_str(lock).ljust(widths["state"])
    door = _door_state_str(lock).ljust(widths["door"])
    battery = _battery_str(lock).rjust(widths["battery"])
    bridge_lbl, since = _bridge_cell(lock)
    bridge_cell = _color_bridge_cell(lock, bridge_lbl.ljust(widths["bridge"]))

    # Dim only the fields that actually went stale (lock state, door, battery)
    # -- the glyph, name, bridge cell, and time-since are current truth about
    # the situation and should stay readable.
    if lock.is_stale:
        stale_fields = _gray(f"{state}  {door}  {battery}")
        return f"  {glyph}  {name}  {stale_fields}  {bridge_cell}  {since}"
    return f"  {glyph}  {name}  {state}  {door}  {battery}  {bridge_cell}  {since}"


def _compute_widths(locks: list[YaleLock]) -> dict:
    return {
        "name": max((len(l.name) for l in locks), default=4),
        "state": max(len("unknown"), len("unlocked")),
        "door": max(len("unknown"), len("closed"), len("n/a")),
        "battery": 4,  # "100%" or "--"
        "bridge": max(len(s) for s in _BRIDGE_CELL_LABELS),
    }


def _print_summary(locks: list[YaleLock]) -> None:
    homes = {l.house_id for l in locks}
    online = sum(1 for l in locks if l.bridge and l.bridge.connectivity == "online")
    offline = sum(1 for l in locks if l.bridge and l.bridge.connectivity == "offline")
    unbridged = sum(1 for l in locks if l.bridge is None)
    batt_ok = sum(1 for l in locks if l.battery_valid and not l.is_stale)

    healthy = sum(1 for l in locks if l.health_status == "healthy")
    warning = sum(1 for l in locks if l.health_status == "warning")
    unhealthy = sum(1 for l in locks if l.health_status == "unhealthy")

    print(_bold(f"Yale locks: {len(locks)} across {len(homes)} homes"))
    print(f"  Health:    {_green(str(healthy)+' healthy')}, "
          f"{_yellow(str(warning)+' warning')}, "
          f"{_red(str(unhealthy)+' unhealthy')}")
    print(f"  Bridges:   {_green(str(online)+' online')}, "
          f"{_red(str(offline)+' offline')}, "
          f"{_yellow(str(unbridged)+' none')}")
    print(f"  Batteries: {batt_ok}/{len(locks)} reporting (rest stale or unknown)")
    print()


def _print_home_section(home_name: str, locks: list[YaleLock]) -> None:
    print(_bold(home_name))
    print("═" * len(home_name))
    widths = _compute_widths(locks)
    for lock in sorted(locks, key=lambda l: l.name):
        print(_format_one_line(lock, widths))
    print()


def _print_detail(lock: YaleLock) -> None:
    print(_bold(f"{lock.house_name} > {lock.name}"))

    status = lock.health_status
    if status == "healthy":
        print(f"  Health:    {_green('healthy')}")
    else:
        label = _yellow("WARNING") if status == "warning" else _red("UNHEALTHY")
        print(f"  Health:    {label}")
        for issue in lock.health_issues:
            print(f"    {_issue_glyph(issue.severity)} {issue.message}")

    state = _lock_state_str(lock)
    if lock.is_stale:
        state += " (stale)"
    print(f"  Locked:    {state}")
    if lock.doorsense:
        door = _door_state_str(lock)
        if lock.is_stale:
            door += " (stale)"
        print(f"  Door:      {door}")
    print(f"  Battery:   {_battery_str(lock)}" + (" (stale)" if lock.is_stale and lock.battery_valid else ""))
    print(f"  Lock seen: {_format_ts(lock.status_datetime)}")
    if lock.mac_address:
        print(f"  MAC:       {lock.mac_address}")
    if lock.model:
        print(f"  Model:     {lock.model}")
    print(f"  Firmware:  {lock.firmware_version}")
    print(f"  Serial:    {lock.serial_number}")

    if lock.bridge is None:
        print(f"  Bridge:    {_yellow('none (unbridged lock)')}")
    else:
        b = lock.bridge
        colored = _green("online") if b.connectivity == "online" else _red("offline")
        print(f"  Bridge:")
        print(f"    Status:    {colored}")
        print(f"    Model:     {b.model or 'unknown'}")
        print(f"    Firmware:  {b.firmware or 'unknown'}")
        print(f"    Mfg ID:    {b.mfg_id or 'unknown'}")
        print(f"    Last online:  {_format_ts(b.last_online)}")
        print(f"    Last offline: {_format_ts(b.last_offline)}")
        if b.wifi_issue_at is not None:
            print(f"    WiFi issue:   {_format_ts(b.wifi_issue_at)}")
    print()


async def cmd_auth() -> None:
    email, password = get_credentials()
    print(f"Logging in as {email}...")
    await login(email, password)
    print("Authentication successful! Tokens saved.")

    locks = await get_locks()
    if locks:
        print(f"\nFound {len(locks)} lock(s):")
        for lock in locks:
            print(f"  {lock.name}: {lock.lock_status.value} (battery: {lock.battery_level}%)")
    else:
        print("\nNo locks found on this account.")


async def cmd_status(name_filter: str | None) -> None:
    locks = await get_locks()
    if not locks:
        print("No locks found.")
        return

    if name_filter:
        needle = name_filter.lower()
        matches = [l for l in locks if needle in l.name.lower()]
        if not matches:
            print(f"No lock matching {name_filter!r}.")
            print(f"Known locks: {', '.join(sorted(set(l.name for l in locks)))}")
            sys.exit(1)
        for lock in matches:
            _print_detail(lock)
        return

    _print_summary(locks)

    by_home: dict[str, list[YaleLock]] = defaultdict(list)
    for lock in locks:
        by_home[lock.house_name].append(lock)
    for home_name in sorted(by_home.keys()):
        _print_home_section(home_name, by_home[home_name])


async def run(args) -> None:
    if args.command == "auth":
        await cmd_auth()
    elif args.command == "status":
        await cmd_status(args.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Yale Access lock CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Login and save tokens")
    status = sub.add_parser("status", help="Show lock status")
    status.add_argument("name", nargs="?", help="Show detailed view for a lock (substring match on name)")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
