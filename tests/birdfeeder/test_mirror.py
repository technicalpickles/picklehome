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
