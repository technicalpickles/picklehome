#!/usr/bin/env python3
"""
birdfeeder_cli.py -- VicoHome (Harymor bird feeder / camera) CLI

Usage:
    uv run python birdfeeder/birdfeeder_cli.py status              # device state: battery, WiFi signal, online
    uv run python birdfeeder/birdfeeder_cli.py events [--days N]   # bird detection log (default: last 1 day)
"""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone

from birdfeeder.vicohome.auth import get_credentials
from birdfeeder.vicohome.client import connect, get_devices, get_events


async def cmd_status():
    email, password, region = get_credentials()
    session = await connect(email, password, region)
    try:
        devices = await get_devices(session)
        if not devices:
            print("No devices found.")
            return
        for device in devices:
            print(f"{device.device_name} ({device.location_name or device.home_name})")
            print(f"  Online:   {'yes' if device.online else 'no'}")
            print(f"  Battery:  {device.battery_level}%{' (charging)' if device.is_charging else ''}")
            print(f"  WiFi:     {device.signal_strength} dBm (channel {device.wifi_channel})")
            print(f"  IP:       {device.ip}")
            print(f"  MAC:      {device.mac_address}")
            print(f"  Model:    {device.model_no}")
            print(f"  Firmware: {device.firmware_id}")
            print(f"  Serial:   {device.serial_number}")
    finally:
        await session.close()


async def cmd_events(days: int):
    email, password, region = get_credentials()
    country_no = "US" if region == "us" else region.upper()
    session = await connect(email, password, region)
    try:
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=days)
        events = await get_events(session, start=start, end=end, country_no=country_no)
        if not events:
            print(f"No events in the last {days} day(s).")
            return
        for event in sorted(events, key=lambda e: e.timestamp, reverse=True):
            local_time = event.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            if event.species_name:
                species = f"{event.species_name} ({event.species_latin}, confidence {event.confidence})"
            else:
                species = "unidentified bird"
            print(f"{local_time}  {species}")
            print(f"  Image: {event.image_url}")
            print(f"  Video: {event.video_url}")
    finally:
        await session.close()


async def run(args):
    if args.command == "status":
        await cmd_status()
    elif args.command == "events":
        await cmd_events(args.days)


def main():
    parser = argparse.ArgumentParser(description="VicoHome (Harymor bird feeder / camera) CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Device state: battery, WiFi signal, online")
    events_parser = sub.add_parser("events", help="Bird detection log")
    events_parser.add_argument("--days", type=int, default=1, help="Look back this many days (default: 1)")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
