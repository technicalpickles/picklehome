"""Local mirror of the VicoHome event log: SQLite rows plus downloaded images.

VicoHome's image URLs are pre-signed and expire after ~48 hours, so anything not copied
down soon after the event is gone. The mirror is the durable copy; consumers (Skylight sync,
species logs) read from it instead of the API.

Writes are idempotent, keyed by `trace_id`. `sync` walks the range one day at a time and
commits after every window, so an interrupted backfill resumes where it stopped.
"""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp

from birdfeeder.vicohome.client import BirdEvent

DEFAULT_MIRROR_DIR = Path.home() / ".local" / "state" / "picklehome" / "birdfeeder"

# trace_id becomes a filename, so refuse anything that could escape the images directory.
_SAFE_TRACE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    trace_id         TEXT PRIMARY KEY,
    timestamp        TEXT NOT NULL,
    duration_seconds REAL,
    device_name      TEXT,
    serial_number    TEXT,
    species_name     TEXT,
    species_latin    TEXT,
    confidence       INTEGER,
    image_path       TEXT
)
"""

FetchEvents = Callable[[datetime, datetime], Awaitable[list[BirdEvent]]]
DownloadImage = Callable[[str, Path], Awaitable[None]]


def mirror_dir() -> Path:
    override = os.environ.get("BIRDFEEDER_MIRROR_DIR")
    return Path(override).expanduser() if override else DEFAULT_MIRROR_DIR


class Mirror:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(root / "mirror.sqlite3")
        self._db.execute(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def count(self) -> int:
        return self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def species(self, trace_id: str) -> str | None:
        row = self._db.execute("SELECT species_name FROM events WHERE trace_id = ?", (trace_id,)).fetchone()
        return row[0] if row else None

    def image_relpath(self, trace_id: str) -> str | None:
        row = self._db.execute("SELECT image_path FROM events WHERE trace_id = ?", (trace_id,)).fetchone()
        return row[0] if row else None

    def upsert(self, events: Iterable[BirdEvent]) -> tuple[int, int]:
        """Insert unseen events and fill in species identified after the first fetch.

        Returns (new, updated). A later fetch that lacks a species never blanks a known one.
        """
        new = updated = 0
        for event in events:
            _check_trace_id(event.trace_id)
            row = self._db.execute("SELECT species_name FROM events WHERE trace_id = ?", (event.trace_id,)).fetchone()
            if row is None:
                self._db.execute(
                    "INSERT INTO events (trace_id, timestamp, duration_seconds, device_name, serial_number,"
                    " species_name, species_latin, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.trace_id,
                        event.timestamp.isoformat(),
                        event.duration_seconds,
                        event.device_name,
                        event.serial_number,
                        event.species_name,
                        event.species_latin,
                        event.confidence,
                    ),
                )
                new += 1
            elif event.species_name and row[0] != event.species_name:
                self._db.execute(
                    "UPDATE events SET species_name = ?, species_latin = ?, confidence = ? WHERE trace_id = ?",
                    (event.species_name, event.species_latin, event.confidence, event.trace_id),
                )
                updated += 1
        self._db.commit()
        return new, updated

    def image_dest(self, event: BirdEvent) -> Path:
        _check_trace_id(event.trace_id)
        return self.root / f"images/{event.timestamp:%Y/%m/%d}/{event.trace_id}.jpg"

    def record_image(self, trace_id: str, dest: Path) -> None:
        self._db.execute("UPDATE events SET image_path = ? WHERE trace_id = ?", (str(dest.relative_to(self.root)), trace_id))
        self._db.commit()


def _check_trace_id(trace_id: str) -> None:
    if not _SAFE_TRACE_ID.match(trace_id):
        raise ValueError(f"unsafe trace_id {trace_id!r}: refusing to use it as a filename")


async def download_image(http: aiohttp.ClientSession, url: str, dest: Path) -> None:
    """Fetch a pre-signed image URL to `dest`, atomically.

    aiohttp's own error messages embed the full signed URL, so failures are re-raised without it.
    """
    try:
        async with http.get(url) as resp:
            resp.raise_for_status()
            data = await resp.read()
    except aiohttp.ClientResponseError as exc:
        raise RuntimeError(f"image download failed: HTTP {exc.status}") from None
    except aiohttp.ClientError as exc:
        raise RuntimeError(f"image download failed: {type(exc).__name__}") from None
    if not data:
        raise RuntimeError("image download failed: empty body")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(dest)


@dataclass
class SyncResult:
    windows: int = 0
    new: int = 0
    updated: int = 0
    images: int = 0
    failures: list[tuple[str, BaseException]] = field(default_factory=list)


async def sync(
    mirror: Mirror,
    fetch: FetchEvents,
    download: DownloadImage,
    start: datetime,
    end: datetime,
    window: timedelta = timedelta(days=1),
    concurrency: int = 8,
    on_window: Callable[[datetime, int, int, int], None] | None = None,
) -> SyncResult:
    """Mirror events in [start, end) one window at a time.

    A failed event fetch raises (naming the window) after earlier windows are already saved.
    A failed image download is recorded in `result.failures` and retried by the next sync that
    covers the event, since the row is kept without an image path.
    """
    result = SyncResult()
    gate = asyncio.Semaphore(concurrency)

    async def fetch_image(event: BirdEvent) -> None:
        async with gate:
            dest = mirror.image_dest(event)
            await download(event.image_url, dest)
            mirror.record_image(event.trace_id, dest)

    cursor = start
    while cursor < end:
        upper = min(cursor + window, end)
        try:
            events = await fetch(cursor, upper)
        except Exception as exc:
            raise RuntimeError(f"fetching events for {cursor.isoformat()} to {upper.isoformat()} failed: {exc}") from exc

        new, updated = mirror.upsert(events)
        wanted = [e for e in events if e.image_url and mirror.image_relpath(e.trace_id) is None]
        outcomes = await asyncio.gather(*(fetch_image(e) for e in wanted), return_exceptions=True)
        downloaded = 0
        for event, outcome in zip(wanted, outcomes):
            if isinstance(outcome, BaseException):
                result.failures.append((event.trace_id, outcome))
            else:
                downloaded += 1

        result.windows += 1
        result.new += new
        result.updated += updated
        result.images += downloaded
        if on_window:
            on_window(cursor, len(events), new, downloaded)
        cursor = upper
    return result
