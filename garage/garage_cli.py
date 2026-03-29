#!/usr/bin/env python3
"""
garage_cli.py -- Aladdin Connect garage door CLI

Usage:
    uv run python garage/garage_cli.py auth      # login and save tokens
    uv run python garage/garage_cli.py status     # door state, battery, signal
    uv run python garage/garage_cli.py open       # open the door
    uv run python garage/garage_cli.py close      # close the door
"""

import argparse
import asyncio
from datetime import datetime, timezone

from garage.aladdin.auth import get_credentials, login
from garage.aladdin.client import connect, get_doors, open_door, close_door


def _format_since(updated_at: str) -> str:
    """Format updated_at as a timestamp and human-readable duration."""
    try:
        ts = int(updated_at)
    except (ValueError, TypeError):
        return "unknown"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    now = datetime.now(tz=timezone.utc)
    delta = now - datetime.fromtimestamp(ts, tz=timezone.utc)

    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return f"{dt.strftime('%Y-%m-%d %H:%M %Z')} (in the future?)"
    if total_seconds < 60:
        ago = f"{total_seconds}s ago"
    elif total_seconds < 3600:
        ago = f"{total_seconds // 60}m ago"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        ago = f"{hours}h {minutes}m ago"
    else:
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        ago = f"{days}d {hours}h ago"

    return f"{dt.strftime('%Y-%m-%d %H:%M %Z')} ({ago})"


async def cmd_auth():
    email, password = get_credentials()
    print(f"Logging in as {email}...")
    await login(email, password)
    print("Authentication successful! Tokens saved.")

    session, _token = await connect()
    try:
        doors = await get_doors(session)
        if doors:
            print(f"\nFound {len(doors)} door(s):")
            for door in doors:
                print(f"  {door.name}: {door.status} (battery: {door.battery_level}%)")
        else:
            print("\nNo doors found on this account.")
    finally:
        await session.close()


async def cmd_status():
    session, _token = await connect()
    try:
        doors = await get_doors(session)
        if not doors:
            print("No doors found.")
            return
        for door in doors:
            print(f"{door.name}")
            print(f"  State:    {door.status}")
            print(f"  Since:    {_format_since(door.updated_at)}")
            if door.fault != "none":
                print(f"  Fault:    {door.fault}")
            if not door.is_enabled:
                print(f"  Enabled:  no (operate manually)")
            print(f"  Link:     {door.link_status}")
            print(f"  WiFi:     {door.rssi} dBm")
            print(f"  BLE:      {door.ble_strength}")
            print(f"  Battery:  {door.battery_level}%")
            print(f"  MAC:      {door.mac}")
            print(f"  SSID:     {door.ssid}")
            print(f"  Device:   {door.device_status}")
            print(f"  Firmware: {door.software_version}")
    finally:
        await session.close()


async def cmd_open():
    session, _token = await connect()
    try:
        doors = await get_doors(session)
        if not doors:
            print("No doors found.")
            return
        door = doors[0]
        print(f"Opening {door.name}...")
        success = await open_door(session, door.device_id, door.door_index)
        print("Sent." if success else "Failed to send open command.")
    finally:
        await session.close()


async def cmd_close():
    session, _token = await connect()
    try:
        doors = await get_doors(session)
        if not doors:
            print("No doors found.")
            return
        door = doors[0]
        print(f"Closing {door.name}...")
        success = await close_door(session, door.device_id, door.door_index)
        print("Sent." if success else "Failed to send close command.")
    finally:
        await session.close()


async def run(args):
    if args.command == "auth":
        await cmd_auth()
    elif args.command == "status":
        await cmd_status()
    elif args.command == "open":
        await cmd_open()
    elif args.command == "close":
        await cmd_close()


def main():
    parser = argparse.ArgumentParser(description="Aladdin Connect garage door CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="Login and save OAuth tokens")
    sub.add_parser("status", help="Show door state, battery, signal")
    sub.add_parser("open", help="Open the garage door")
    sub.add_parser("close", help="Close the garage door")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
