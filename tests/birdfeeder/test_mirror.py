import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from birdfeeder.mirror import Mirror, sync
from birdfeeder.vicohome.client import BirdEvent

START = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _event(trace_id: str, when: datetime, species: str | None = None, image_url: str = "https://img.invalid/x") -> BirdEvent:
    return BirdEvent(
        trace_id=trace_id,
        timestamp=when,
        duration_seconds=9.5,
        device_name="Feeder",
        serial_number="0123456789abcdef0123456789abcdef",
        species_name=species,
        species_latin="Cyanocitta cristata" if species else None,
        confidence=80 if species else None,
        image_url=image_url,
        video_url="https://vid.invalid/x.m3u8",
    )


async def _write_download(url: str, dest) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"jpeg-bytes")


def _run_sync(mirror, events_by_call, download, start=START, end=START + timedelta(days=1), **kwargs):
    fetch = AsyncMock(side_effect=events_by_call)
    result = asyncio.run(sync(mirror, fetch, download, start, end, **kwargs))
    return result, fetch


def test_upsert_is_idempotent(tmp_path):
    mirror = Mirror(tmp_path)
    events = [_event("a1", START), _event("a2", START + timedelta(minutes=5))]

    assert mirror.upsert(events) == (2, 0)
    assert mirror.upsert(events) == (0, 0)
    assert mirror.count() == 2


def test_upsert_fills_in_species_identified_later(tmp_path):
    mirror = Mirror(tmp_path)
    mirror.upsert([_event("a1", START)])

    assert mirror.upsert([_event("a1", START, species="Blue Jay")]) == (0, 1)
    assert mirror.species("a1") == "Blue Jay"


def test_upsert_does_not_blank_a_known_species(tmp_path):
    mirror = Mirror(tmp_path)
    mirror.upsert([_event("a1", START, species="Blue Jay")])

    assert mirror.upsert([_event("a1", START)]) == (0, 0)
    assert mirror.species("a1") == "Blue Jay"


def test_rejects_trace_ids_that_are_unsafe_as_filenames(tmp_path):
    mirror = Mirror(tmp_path)
    with pytest.raises(ValueError, match="trace_id"):
        mirror.upsert([_event("../evil", START)])


def test_sync_downloads_images_under_date_dirs(tmp_path):
    mirror = Mirror(tmp_path)
    result, _ = _run_sync(mirror, [[_event("a1", START)]], _write_download)

    assert (result.new, result.images, result.failures) == (1, 1, [])
    assert (tmp_path / "images/2026/10/01/a1.jpg").read_bytes() == b"jpeg-bytes"
    assert mirror.image_relpath("a1") == "images/2026/10/01/a1.jpg"


def test_second_sync_does_not_redownload(tmp_path):
    mirror = Mirror(tmp_path)
    events = [_event("a1", START)]
    _run_sync(mirror, [events], _write_download)

    download = AsyncMock(side_effect=_write_download)
    result, _ = _run_sync(mirror, [events], download)

    assert (result.new, result.images) == (0, 0)
    download.assert_not_called()


def test_failed_download_keeps_the_event_and_is_retried(tmp_path):
    mirror = Mirror(tmp_path)
    events = [_event("a1", START)]
    failing = AsyncMock(side_effect=RuntimeError("HTTP 403"))

    result, _ = _run_sync(mirror, [events], failing)
    assert result.new == 1 and result.images == 0
    assert [(tid, str(exc)) for tid, exc in result.failures] == [("a1", "HTTP 403")]
    assert mirror.count() == 1
    assert mirror.image_relpath("a1") is None

    result, _ = _run_sync(mirror, [events], _write_download)
    assert (result.new, result.images, result.failures) == (0, 1, [])
    assert mirror.image_relpath("a1") == "images/2026/10/01/a1.jpg"


def test_one_failed_download_does_not_cancel_the_others(tmp_path):
    mirror = Mirror(tmp_path)
    events = [_event("bad", START, image_url="https://img.invalid/bad"), _event("good", START, image_url="https://img.invalid/good")]

    async def flaky(url, dest):
        if url.endswith("bad"):
            raise RuntimeError("HTTP 500")
        await _write_download(url, dest)

    result, _ = _run_sync(mirror, [events], flaky)

    assert result.images == 1
    assert [tid for tid, _ in result.failures] == ["bad"]
    assert mirror.image_relpath("good") is not None


def test_event_without_image_url_is_stored_and_skipped(tmp_path):
    mirror = Mirror(tmp_path)
    download = AsyncMock(side_effect=_write_download)

    result, _ = _run_sync(mirror, [[_event("a1", START, image_url="")]], download)

    assert (result.new, result.images, result.failures) == (1, 0, [])
    download.assert_not_called()


def test_sync_fetches_one_window_per_day(tmp_path):
    mirror = Mirror(tmp_path)
    end = START + timedelta(days=2, hours=6)

    result, fetch = _run_sync(mirror, [[], [], []], _write_download, end=end)

    windows = [(call.args[0], call.args[1]) for call in fetch.await_args_list]
    assert windows == [
        (START, START + timedelta(days=1)),
        (START + timedelta(days=1), START + timedelta(days=2)),
        (START + timedelta(days=2), end),
    ]
    assert result.windows == 3


def test_fetch_failure_names_the_window_and_keeps_earlier_progress(tmp_path):
    mirror = Mirror(tmp_path)
    end = START + timedelta(days=2)
    day_one = [_event("a1", START)]

    with pytest.raises(RuntimeError, match="2026-10-02"):
        _run_sync(mirror, [day_one, ConnectionError("boom")], _write_download, end=end)

    assert mirror.count() == 1
    assert mirror.image_relpath("a1") is not None


# --- videos ---------------------------------------------------------------------------------


async def _write_video(url: str, dest) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"mp4-bytes")


def _run_sync_videos(mirror, events_by_call, download_video, download=_write_download, **kwargs):
    fetch = AsyncMock(side_effect=events_by_call)
    return asyncio.run(
        sync(mirror, fetch, download, START, START + timedelta(days=1), download_video=download_video, **kwargs)
    )


def test_sync_downloads_videos_under_date_dirs(tmp_path):
    mirror = Mirror(tmp_path)
    result = _run_sync_videos(mirror, [[_event("a1", START)]], _write_video)

    assert (result.videos, result.video_failures) == (1, [])
    assert (tmp_path / "videos/2026/10/01/a1.mp4").read_bytes() == b"mp4-bytes"
    assert mirror.video_relpath("a1") == "videos/2026/10/01/a1.mp4"


def test_videos_are_skipped_unless_a_downloader_is_given(tmp_path):
    mirror = Mirror(tmp_path)
    result, _ = _run_sync(mirror, [[_event("a1", START)]], _write_download)

    assert result.videos == 0
    assert mirror.video_relpath("a1") is None


def test_second_sync_does_not_redownload_videos(tmp_path):
    mirror = Mirror(tmp_path)
    events = [_event("a1", START)]
    _run_sync_videos(mirror, [events], _write_video)

    download_video = AsyncMock(side_effect=_write_video)
    result = _run_sync_videos(mirror, [events], download_video)

    assert result.videos == 0
    download_video.assert_not_called()


def test_sync_backfills_videos_for_events_that_already_have_images(tmp_path):
    mirror = Mirror(tmp_path)
    events = [_event("a1", START)]
    _run_sync(mirror, [events], _write_download)

    download = AsyncMock(side_effect=_write_download)
    result = _run_sync_videos(mirror, [events], _write_video, download=download)

    assert (result.images, result.videos) == (0, 1)
    download.assert_not_called()


def test_failed_video_is_recorded_separately_and_retried(tmp_path):
    mirror = Mirror(tmp_path)
    events = [_event("a1", START)]
    failing = AsyncMock(side_effect=RuntimeError("ffmpeg exploded"))

    result = _run_sync_videos(mirror, [events], failing)
    assert (result.images, result.videos, result.failures) == (1, 0, [])
    assert [(tid, str(exc)) for tid, exc in result.video_failures] == [("a1", "ffmpeg exploded")]
    assert mirror.video_relpath("a1") is None

    result = _run_sync_videos(mirror, [events], _write_video)
    assert (result.videos, result.video_failures) == (1, [])


def test_event_without_video_url_is_skipped(tmp_path):
    mirror = Mirror(tmp_path)
    event = _event("a1", START)
    event.video_url = ""
    download_video = AsyncMock(side_effect=_write_video)

    result = _run_sync_videos(mirror, [[event]], download_video)

    assert (result.videos, result.video_failures) == (0, [])
    download_video.assert_not_called()


def test_existing_database_without_a_video_column_is_migrated(tmp_path):
    import sqlite3

    db = sqlite3.connect(tmp_path / "mirror.sqlite3")
    db.execute(
        "CREATE TABLE events (trace_id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, duration_seconds REAL,"
        " device_name TEXT, serial_number TEXT, species_name TEXT, species_latin TEXT, confidence INTEGER, image_path TEXT)"
    )
    db.execute("INSERT INTO events (trace_id, timestamp, image_path) VALUES ('old1', '2026-09-10T00:00:00+00:00', 'images/x.jpg')")
    db.commit()
    db.close()

    mirror = Mirror(tmp_path)

    assert mirror.count() == 1
    assert mirror.video_relpath("old1") is None
    mirror.record_video("old1", tmp_path / "videos/2026/09/10/old1.mp4")
    assert mirror.video_relpath("old1") == "videos/2026/09/10/old1.mp4"
    assert mirror.image_relpath("old1") == "images/x.jpg"


# download_video against a real local HTTP server and a real ffmpeg remux.

import shutil
import subprocess

import aiohttp
from aiohttp import web

from birdfeeder.mirror import download_video

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
SECRET = "sekrit-token"


def _make_ts_segments(directory, count=2):
    paths = []
    for i in range(count):
        path = directory / f"seg{i}.ts"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
             "-c:v", "mpeg2video", "-f", "mpegts", str(path)],
            check=True,
        )
        paths.append(path)
    return paths


async def _serve(routes):
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


@needs_ffmpeg
def test_download_video_remuxes_segments_to_mp4(tmp_path):
    segments = _make_ts_segments(tmp_path)
    playlist = "#EXTM3U\n#EXT-X-TARGETDURATION:1\n" + "".join(f"#EXTINF:1.0,\nseg{i}.ts?sig={SECRET}\n" for i in range(len(segments))) + "#EXT-X-ENDLIST\n"

    async def run():
        async def serve_playlist(request):
            return web.Response(text=playlist)

        async def serve_segment(request):
            return web.FileResponse(tmp_path / request.match_info["name"])

        runner, base = await _serve([web.get("/p.m3u8", serve_playlist), web.get("/{name}", serve_segment)])
        try:
            dest = tmp_path / "out" / "clip.mp4"
            async with aiohttp.ClientSession() as http:
                await download_video(http, f"{base}/p.m3u8?token=t", dest)
            return dest
        finally:
            await runner.cleanup()

    dest = asyncio.run(run())

    assert dest.read_bytes()[4:8] == b"ftyp"
    assert not list(dest.parent.glob("*.part*")) and not list(dest.parent.glob("*.ts"))


def test_download_video_failure_does_not_leak_the_signed_url(tmp_path):
    async def run():
        async def serve_playlist(request):
            return web.Response(text=f"#EXTM3U\n#EXTINF:1.0,\n/seg.ts?sig={SECRET}\n#EXT-X-ENDLIST\n")

        async def forbidden(request):
            return web.Response(status=403)

        runner, base = await _serve([web.get("/p.m3u8", serve_playlist), web.get("/seg.ts", forbidden)])
        try:
            async with aiohttp.ClientSession() as http:
                await download_video(http, f"{base}/p.m3u8?token=t", tmp_path / "clip.mp4")
        finally:
            await runner.cleanup()

    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(run())

    message = str(excinfo.value)
    assert "HTTP 403" in message and "segment" in message
    assert SECRET not in message and "127.0.0.1" not in message
    assert not (tmp_path / "clip.mp4").exists()


def test_download_video_rejects_a_playlist_with_no_segments(tmp_path):
    async def run():
        async def serve_playlist(request):
            return web.Response(text="#EXTM3U\n#EXT-X-ENDLIST\n")

        runner, base = await _serve([web.get("/p.m3u8", serve_playlist)])
        try:
            async with aiohttp.ClientSession() as http:
                await download_video(http, f"{base}/p.m3u8", tmp_path / "clip.mp4")
        finally:
            await runner.cleanup()

    with pytest.raises(RuntimeError, match="no segments"):
        asyncio.run(run())
