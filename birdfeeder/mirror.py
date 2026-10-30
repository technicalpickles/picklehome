"""Local mirror of the VicoHome event log: SQLite rows plus downloaded images.

VicoHome's image URLs are pre-signed and expire after ~48 hours, so anything not copied
down soon after the event is gone. The mirror is the durable copy; consumers (Skylight sync,
species logs) read from it instead of the API.

Videos are HLS playlists of short .ts segments; they're fetched, joined, and remuxed (not re-encoded)
into one mp4 per event with ffmpeg.

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
from urllib.parse import urljoin

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
    image_path       TEXT,
    video_path       TEXT
)
"""

FetchEvents = Callable[[datetime, datetime], Awaitable[list[BirdEvent]]]
DownloadImage = Callable[[str, Path], Awaitable[None]]
DownloadVideo = Callable[[str, Path], Awaitable[None]]


def mirror_dir() -> Path:
    override = os.environ.get("BIRDFEEDER_MIRROR_DIR")
    return Path(override).expanduser() if override else DEFAULT_MIRROR_DIR


class Mirror:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(root / "mirror.sqlite3")
        self._db.execute(_SCHEMA)
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(events)")}
        if "video_path" not in columns:  # mirrors created before video support
            self._db.execute("ALTER TABLE events ADD COLUMN video_path TEXT")
            self._db.commit()

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

    def video_relpath(self, trace_id: str) -> str | None:
        row = self._db.execute("SELECT video_path FROM events WHERE trace_id = ?", (trace_id,)).fetchone()
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

    def video_dest(self, event: BirdEvent) -> Path:
        _check_trace_id(event.trace_id)
        return self.root / f"videos/{event.timestamp:%Y/%m/%d}/{event.trace_id}.mp4"

    def record_video(self, trace_id: str, dest: Path) -> None:
        self._db.execute("UPDATE events SET video_path = ? WHERE trace_id = ?", (str(dest.relative_to(self.root)), trace_id))
        self._db.commit()


def _check_trace_id(trace_id: str) -> None:
    if not _SAFE_TRACE_ID.match(trace_id):
        raise ValueError(f"unsafe trace_id {trace_id!r}: refusing to use it as a filename")


async def _get_bytes(http: aiohttp.ClientSession, url: str, what: str) -> bytes:
    """GET a pre-signed URL. aiohttp's own error messages embed the full signed URL, so failures
    are re-raised without it. (These URLs are signed for GET only: HEAD gets a 403.)"""
    try:
        async with http.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()
    except aiohttp.ClientResponseError as exc:
        raise RuntimeError(f"{what} download failed: HTTP {exc.status}") from None
    except aiohttp.ClientError as exc:
        raise RuntimeError(f"{what} download failed: {type(exc).__name__}") from None
    except asyncio.TimeoutError:
        raise RuntimeError(f"{what} download failed: timed out") from None


async def download_image(http: aiohttp.ClientSession, url: str, dest: Path) -> None:
    """Fetch a pre-signed image URL to `dest`, atomically."""
    data = await _get_bytes(http, url, "image")
    if not data:
        raise RuntimeError("image download failed: empty body")
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(dest)


async def download_video(
    http: aiohttp.ClientSession,
    playlist_url: str,
    dest: Path,
    ffmpeg: str = "ffmpeg",
    segment_concurrency: int = 5,
) -> None:
    """Fetch an HLS playlist's segments and remux them into one mp4 at `dest`, atomically.

    The segments are plain unencrypted .ts, so `-c copy` repackages them without re-encoding.
    """
    playlist = (await _get_bytes(http, playlist_url, "playlist")).decode(errors="replace")
    segment_urls = [urljoin(playlist_url, line.strip()) for line in playlist.splitlines() if line.strip() and not line.startswith("#")]
    if not segment_urls:
        raise RuntimeError("video playlist has no segments")

    gate = asyncio.Semaphore(segment_concurrency)

    async def segment(url: str) -> bytes:
        async with gate:
            return await _get_bytes(http, url, "segment")

    parts = await asyncio.gather(*(segment(u) for u in segment_urls), return_exceptions=True)
    for part in parts:
        if isinstance(part, BaseException):
            raise part

    dest.parent.mkdir(parents=True, exist_ok=True)
    joined = dest.with_suffix(".ts.part")
    partial = dest.with_suffix(".part.mp4")
    try:
        joined.write_bytes(b"".join(parts))
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg, "-v", "error", "-y", "-i", str(joined), "-c", "copy", "-movflags", "+faststart", str(partial),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            raise RuntimeError(f"{ffmpeg} not found on PATH") from None
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {stderr.decode(errors='replace').strip()[-300:]}")
        partial.replace(dest)
    finally:
        joined.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)


@dataclass
class SyncResult:
    windows: int = 0
    new: int = 0
    updated: int = 0
    images: int = 0
    videos: int = 0
    failures: list[tuple[str, BaseException]] = field(default_factory=list)
    video_failures: list[tuple[str, BaseException]] = field(default_factory=list)


async def sync(
    mirror: Mirror,
    fetch: FetchEvents,
    download: DownloadImage,
    start: datetime,
    end: datetime,
    window: timedelta = timedelta(days=1),
    concurrency: int = 8,
    download_video: DownloadVideo | None = None,
    video_concurrency: int = 4,
    on_window: Callable[[datetime, int, int, int, int], None] | None = None,
) -> SyncResult:
    """Mirror events in [start, end) one window at a time.

    A failed event fetch raises (naming the window) after earlier windows are already saved.
    A failed image or video download is recorded in `result.failures` / `result.video_failures`
    and retried by the next sync that covers the event, since the row is kept without a path.
    Videos are only fetched when `download_video` is given.
    """
    result = SyncResult()
    gate = asyncio.Semaphore(concurrency)
    video_gate = asyncio.Semaphore(video_concurrency)

    async def fetch_image(event: BirdEvent) -> None:
        async with gate:
            dest = mirror.image_dest(event)
            await download(event.image_url, dest)
            mirror.record_image(event.trace_id, dest)

    async def fetch_video(event: BirdEvent) -> None:
        async with video_gate:
            dest = mirror.video_dest(event)
            await download_video(event.video_url, dest)
            mirror.record_video(event.trace_id, dest)

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

        videos_downloaded = 0
        if download_video:
            video_wanted = [e for e in events if e.video_url and mirror.video_relpath(e.trace_id) is None]
            video_outcomes = await asyncio.gather(*(fetch_video(e) for e in video_wanted), return_exceptions=True)
            for event, outcome in zip(video_wanted, video_outcomes):
                if isinstance(outcome, BaseException):
                    result.video_failures.append((event.trace_id, outcome))
                else:
                    videos_downloaded += 1

        result.windows += 1
        result.new += new
        result.updated += updated
        result.images += downloaded
        result.videos += videos_downloaded
        if on_window:
            on_window(cursor, len(events), new, downloaded, videos_downloaded)
        cursor = upper
    return result
