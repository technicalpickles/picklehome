#!/usr/bin/env python3
"""
birdfeeder_cli.py -- VicoHome (Harymor bird feeder / camera) CLI

Usage:
    uv run python birdfeeder/birdfeeder_cli.py status                                    # device state
    uv run python birdfeeder/birdfeeder_cli.py events [--days N] [--species TEXT] [--urls] [--json]
    uv run python birdfeeder/birdfeeder_cli.py species [--days N] [--json]                # species seen, with counts
    uv run python birdfeeder/birdfeeder_cli.py sync [--days N] [--no-videos]                 # mirror events, images, and videos locally
    uv run python birdfeeder/birdfeeder_cli.py skylight-sync [--limit N] [--include-unidentified]  # upload mirrored clips to Skylight
"""

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

import aiohttp

from birdfeeder.mirror import Mirror, download_image, download_video, mirror_dir, sync
from birdfeeder.skylight_sync import SkylightSync, SyncStopped, subprocess_runner
from birdfeeder.vicohome.auth import get_credentials
from birdfeeder.vicohome.client import (
    BirdEvent,
    SpeciesSummary,
    connect,
    filter_events_by_species,
    get_devices,
    get_events,
    summarize_species,
)


def _event_to_dict(event: BirdEvent) -> dict:
    return {
        "trace_id": event.trace_id,
        "timestamp": event.timestamp.isoformat(),
        "duration_seconds": event.duration_seconds,
        "device_name": event.device_name,
        "serial_number": event.serial_number,
        "species_name": event.species_name,
        "species_latin": event.species_latin,
        "confidence": event.confidence,
        "image_url": event.image_url,
        "video_url": event.video_url,
    }


def _species_to_dict(summary: SpeciesSummary) -> dict:
    return {
        "species_name": summary.species_name,
        "species_latin": summary.species_latin,
        "count": summary.count,
        "first_seen": summary.first_seen.isoformat(),
        "last_seen": summary.last_seen.isoformat(),
    }


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


async def _fetch_events(days: int) -> list[BirdEvent]:
    email, password, region = get_credentials()
    country_no = "US" if region == "us" else region.upper()
    session = await connect(email, password, region)
    try:
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=days)
        return await get_events(session, start=start, end=end, country_no=country_no)
    finally:
        await session.close()


async def cmd_events(days: int, species_query: str | None, show_urls: bool, json_output: bool):
    events = sorted(await _fetch_events(days), key=lambda e: e.timestamp, reverse=True)
    if species_query:
        events = filter_events_by_species(events, species_query)

    if json_output:
        print(json.dumps([_event_to_dict(e) for e in events], indent=2))
        return

    if not events:
        if species_query:
            print(f"No events matching species '{species_query}' in the last {days} day(s).")
        else:
            print(f"No events in the last {days} day(s).")
        return

    for event in events:
        local_time = event.timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        if event.species_name:
            species = f"{event.species_name} ({event.species_latin}, confidence {event.confidence})"
        else:
            species = "unidentified bird"
        print(f"{local_time}  {species}")
        if show_urls:
            print(f"  Image: {event.image_url}")
            print(f"  Video: {event.video_url}")


async def cmd_species(days: int, json_output: bool):
    events = await _fetch_events(days)
    summaries = summarize_species(events)

    if json_output:
        print(json.dumps([_species_to_dict(s) for s in summaries], indent=2))
        return

    if not summaries:
        print(f"No identified species in the last {days} day(s).")
        return

    for summary in summaries:
        first = summary.first_seen.astimezone().strftime("%Y-%m-%d %H:%M")
        last = summary.last_seen.astimezone().strftime("%Y-%m-%d %H:%M")
        print(f"{summary.species_name} ({summary.species_latin})")
        print(f"  Seen: {summary.count} time(s), {first} -> {last}")
        print(f'  Tip:  just birdfeeder events --days {days} --species "{summary.species_name}"')


async def cmd_sync(days: int, with_videos: bool) -> int:
    if with_videos and not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH (needed to assemble video clips). Install it, or pass --no-videos.")
    email, password, region = get_credentials()
    country_no = "US" if region == "us" else region.upper()
    mirror = Mirror(mirror_dir())
    # Image URLs are pre-signed, so they must not get the VicoHome Authorization header.
    # trust_env=True so the download session honors the sandbox proxy.
    async with aiohttp.ClientSession(trust_env=True) as http:
        session = await connect(email, password, region)
        try:

            async def fetch(start: datetime, end: datetime) -> list[BirdEvent]:
                return await get_events(session, start=start, end=end, country_no=country_no)

            def progress(window_start: datetime, fetched: int, new: int, images: int, videos: int) -> None:
                print(
                    f"{window_start.astimezone().date()}  {fetched} events, {new} new, {images} images, {videos} videos",
                    flush=True,
                )

            end = datetime.now(tz=timezone.utc)
            result = await sync(
                mirror,
                fetch,
                lambda url, dest: download_image(http, url, dest),
                start=end - timedelta(days=days),
                end=end,
                download_video=(lambda url, dest: download_video(http, url, dest)) if with_videos else None,
                on_window=progress,
            )
        finally:
            await session.close()

    print(f"\n{result.new} new, {result.updated} species updated, {result.images} images and {result.videos} videos downloaded; {mirror.count()} events in the mirror ({mirror.root})")
    for trace_id, error in result.failures:
        print(f"image failed for {trace_id}: {error}", file=sys.stderr)
    for trace_id, error in result.video_failures:
        print(f"video failed for {trace_id}: {error}", file=sys.stderr)
    mirror.close()
    return 1 if result.failures or result.video_failures else 0


def cmd_skylight_sync(limit: int | None, include_unidentified: bool) -> int:
    def log(message: str) -> None:
        print(f"{datetime.now().strftime('%H:%M:%S')} {message}", flush=True)

    skylight = SkylightSync(mirror_dir(), subprocess_runner(), frame_id=os.environ.get("SKYLIGHT_FRAME_ID"), log=log)
    try:
        summary = skylight.sync(limit=limit, include_unidentified=include_unidentified)
    except SyncStopped as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        print(f"progress is saved in {skylight.ledger_path}; rerun to resume", file=sys.stderr)
        return 1
    print(
        f"\n{summary.uploaded} uploaded, {summary.already_uploaded} already uploaded, {summary.adopted} adopted;"
        f" {summary.rate_limited} rate limits and {summary.transient} transient errors along the way"
    )
    return 0


async def run(args):
    if args.command == "status":
        await cmd_status()
    elif args.command == "events":
        await cmd_events(args.days, args.species, args.urls, args.json)
    elif args.command == "species":
        await cmd_species(args.days, args.json)
    elif args.command == "sync":
        return await cmd_sync(args.days, not args.no_videos)
    elif args.command == "skylight-sync":
        return cmd_skylight_sync(args.limit, args.include_unidentified)


def main():
    parser = argparse.ArgumentParser(description="VicoHome (Harymor bird feeder / camera) CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Device state: battery, WiFi signal, online")

    events_parser = sub.add_parser("events", help="Bird detection log")
    events_parser.add_argument("--days", type=int, default=1, help="Look back this many days (default: 1)")
    events_parser.add_argument(
        "--species", metavar="TEXT", help="Filter to events matching this species (case-insensitive substring)"
    )
    events_parser.add_argument(
        "--urls", action="store_true", help="Include image/video URLs in text output (omitted by default; noisy, long-lived ~48h)"
    )
    events_parser.add_argument("--json", action="store_true", help="Output as JSON (always includes image/video URLs)")

    species_parser = sub.add_parser("species", help="Species seen, with counts and a tip to filter events by species")
    species_parser.add_argument("--days", type=int, default=7, help="Look back this many days (default: 7)")
    species_parser.add_argument("--json", action="store_true", help="Output as JSON")

    sync_parser = sub.add_parser(
        "sync", help="Mirror events, images, and videos into the local store (idempotent; use a big --days to backfill)"
    )
    sync_parser.add_argument("--days", type=int, default=2, help="Look back this many days (default: 2)")
    sync_parser.add_argument("--no-videos", action="store_true", help="Skip video clips (they need ffmpeg and ~60MB/day)")

    skylight_parser = sub.add_parser(
        "skylight-sync",
        help="Upload mirrored clips to the Skylight 'Birds' album (resumable; needs `just skylight-login` once)",
    )
    skylight_parser.add_argument("--limit", type=int, help="Upload at most this many clips this run")
    skylight_parser.add_argument(
        "--include-unidentified", action="store_true", help="Also upload events with no species ID (default: identified only)"
    )

    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)) or 0)


if __name__ == "__main__":
    main()
