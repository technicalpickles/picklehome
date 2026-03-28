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

from garage.aladdin.auth import get_credentials, login
from garage.aladdin.client import connect, get_doors, open_door, close_door


async def cmd_auth():
    email, password = get_credentials()
    print(f"Logging in as {email}...")
    await login(email, password)
    print("Authentication successful! Tokens saved.")

    session, client = await connect()
    try:
        doors = await get_doors(client)
        if doors:
            print(f"\nFound {len(doors)} door(s):")
            for door in doors:
                print(f"  {door.name}: {door.status} (battery: {door.battery_level}%)")
        else:
            print("\nNo doors found on this account.")
    finally:
        await session.close()


async def cmd_status():
    session, client = await connect()
    try:
        doors = await get_doors(client)
        if not doors:
            print("No doors found.")
            return
        for door in doors:
            print(f"{door.name}")
            print(f"  State:   {door.status}")
            print(f"  Battery: {door.battery_level}%")
            print(f"  Link:    {door.link_status}")
    finally:
        await session.close()


async def cmd_open():
    session, client = await connect()
    try:
        doors = await get_doors(client)
        if not doors:
            print("No doors found.")
            return
        door = doors[0]
        print(f"Opening {door.name}...")
        success = await open_door(client, door.device_id, door.door_number)
        print("Sent." if success else "Failed to send open command.")
    finally:
        await session.close()


async def cmd_close():
    session, client = await connect()
    try:
        doors = await get_doors(client)
        if not doors:
            print("No doors found.")
            return
        door = doors[0]
        print(f"Closing {door.name}...")
        success = await close_door(client, door.device_id, door.door_number)
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
