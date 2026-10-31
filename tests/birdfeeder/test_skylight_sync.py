import json
from datetime import datetime, timedelta, timezone

import pytest

from birdfeeder.mirror import Mirror
from birdfeeder.skylight_sync import RunResult, SkylightSync, SyncStopped, caption_for, classify
from birdfeeder.vicohome.client import BirdEvent

T0 = datetime(2026, 10, 27, 18, 57, 39, tzinfo=timezone.utc)  # 2:57pm in New York


def _event(trace_id: str, minutes: int = 0, species: str | None = "Blue Jay") -> BirdEvent:
    return BirdEvent(
        trace_id=trace_id,
        timestamp=T0 + timedelta(minutes=minutes),
        duration_seconds=9.0,
        device_name="Feeder",
        serial_number="0123456789abcdef0123456789abcdef",
        species_name=species,
        species_latin="Cyanocitta cristata" if species else None,
        confidence=80 if species else None,
        image_url="https://img.invalid/x",
        video_url="https://vid.invalid/x.m3u8",
    )


def make_mirror(root, events, with_video=True):
    mirror = Mirror(root)
    mirror.upsert(events)
    if with_video:
        for event in events:
            dest = mirror.video_dest(event)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"mp4")
            mirror.record_video(event.trace_id, dest)
    mirror.close()


def err(kind: str, message: str) -> RunResult:
    return RunResult(1, json.dumps({"ok": False, "error": message, "type": kind}), "")


RATE_LIMIT = err("SkylightRateLimitError", "Skylight rate limit hit (HTTP 429)")
SERVER_ERROR = err("SkylightAPIError", "POST /x failed with HTTP 502")
AUTH_ERROR = err("SkylightAuthError", "session expired")


class FakeSkylight:
    """Stands in for scripts/skylight: a frame with messages and one album."""

    def __init__(self, frames=None, albums=None):
        self.frames = frames if frames is not None else [{"id": "F1", "attributes": {"timezone": "America/New_York"}}]
        self.albums = albums if albums is not None else [{"id": "A1", "attributes": {"title": "Birds"}}]
        self.messages: list[dict] = []
        self.album: list[str] = []
        self.calls: list[list[str]] = []
        self.failures: dict[str, list[RunResult]] = {}
        self.upload_creates_message_despite_failure = False
        self.ignore_album_adds = 0
        self.upload_output = '{"data": {"url": "https://s3.invalid/x?x-amz-meta-recipient_message_ids={id}&sig=z"}}'
        self._next_id = 1000

    def names(self):
        return [c[0] for c in self.calls]

    def __call__(self, args: list[str]) -> RunResult:
        self.calls.append(args)
        name = args[0]
        queued = self.failures.get(name)
        if queued:
            failure = queued.pop(0)
            if name == "photo-upload" and self.upload_creates_message_despite_failure:
                self._create_message(args)
            return failure
        if name == "frames":
            return RunResult(0, json.dumps(self.frames), "")
        if name == "albums":
            return RunResult(0, json.dumps({"data": self.albums}), "")
        if name == "album-add":
            self.albums.append({"id": "A1", "attributes": {"title": args[args.index("--title") + 1]}})
            return RunResult(0, json.dumps({"data": self.albums[-1]}), "")
        if name == "photo-upload":
            message_id = self._create_message(args)
            return RunResult(0, self.upload_output.replace("{id}", message_id), "")
        if name == "album-add-photos":
            if self.ignore_album_adds > 0:
                self.ignore_album_adds -= 1
            else:
                ids = [args[i + 1] for i, a in enumerate(args) if a == "--message-id"]
                self.album.extend(i for i in ids if i not in self.album)
            return RunResult(0, "{}", "")
        if name == "album-message-ids":
            newest = list(reversed(self.album))[:100]
            return RunResult(0, json.dumps({"data": [{"id": i, "type": "id"} for i in newest]}), "")
        if name == "messages":
            data = [
                {"id": m["id"], "attributes": {"caption": m["caption"], "created_at": m["created_at"]}}
                for m in reversed(self.messages)
            ]
            return RunResult(0, json.dumps({"data": data}), "")
        raise AssertionError(f"unexpected command {args}")

    def _create_message(self, args):
        self._next_id += 1
        message_id = str(self._next_id)
        self.messages.append(
            {
                "id": message_id,
                "caption": args[args.index("--caption") + 1],
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
        return message_id


def make_sync(tmp_path, fake, **kwargs):
    sleeps: list[float] = []
    sync = SkylightSync(tmp_path, fake, sleep=sleeps.append, log=lambda m: None, **kwargs)
    return sync, sleeps


def ledger(tmp_path):
    path = tmp_path / "skylight-uploads.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# --- classification -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "result, kind",
    [
        (RunResult(0, "fine", ""), "ok"),
        (RATE_LIMIT, "ratelimit"),
        (SERVER_ERROR, "transient"),
        (err("SkylightAPIError", "POST /x failed with HTTP 422"), "fatal"),
        (AUTH_ERROR, "fatal"),
        (err("SkylightPlusRequiredError", "needs plus"), "fatal"),
        (err("SkylightNotFoundError", "gone"), "fatal"),
        (err("SkylightError", "Network error during request: ReadTimeout"), "transient"),
        (RunResult(2, "", "Traceback: boom"), "transient"),
    ],
)
def test_classify(result, kind):
    assert classify(result)[0] == kind


def test_caption_uses_the_given_timezone_and_names_unidentified_birds():
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    assert caption_for("Blue Jay", T0, ny) == "Blue Jay, Tue Oct 27 2:57pm"
    assert caption_for(None, T0, ny) == "Bird, Tue Oct 27 2:57pm"


# --- the happy path -------------------------------------------------------------------------


def test_uploads_identified_events_oldest_first_and_confirms_the_album(tmp_path):
    make_mirror(tmp_path, [_event("b", 5, "Northern Cardinal"), _event("a", 0, "Blue Jay")])
    fake = FakeSkylight()
    sync, _ = make_sync(tmp_path, fake)

    summary = sync.sync()

    assert summary.uploaded == 2
    assert [m["caption"] for m in fake.messages] == ["Blue Jay, Tue Oct 27 2:57pm", "Northern Cardinal, Tue Oct 27 3:02pm"]
    assert fake.album == [m["id"] for m in fake.messages]
    assert [r["status"] for r in ledger(tmp_path)] == ["uploaded", "uploaded", "in_album"]
    assert ledger(tmp_path)[0]["trace_id"] == "a"


def test_second_run_uploads_nothing(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    make_sync(tmp_path, fake)[0].sync()
    uploads_before = fake.names().count("photo-upload")

    summary = make_sync(tmp_path, fake)[0].sync()

    assert summary.uploaded == 0
    assert fake.names().count("photo-upload") == uploads_before


def test_unidentified_events_are_excluded_unless_asked_for(tmp_path):
    make_mirror(tmp_path, [_event("a", 0, "Blue Jay"), _event("u", 1, None)])
    fake = FakeSkylight()

    make_sync(tmp_path, fake)[0].sync()
    assert [m["caption"] for m in fake.messages] == ["Blue Jay, Tue Oct 27 2:57pm"]

    make_sync(tmp_path, fake)[0].sync(include_unidentified=True)
    assert [m["caption"] for m in fake.messages][-1] == "Bird, Tue Oct 27 2:58pm"


def test_events_without_a_mirrored_video_are_skipped(tmp_path):
    make_mirror(tmp_path, [_event("a")], with_video=False)
    fake = FakeSkylight()

    assert make_sync(tmp_path, fake)[0].sync().uploaded == 0
    assert "photo-upload" not in fake.names()


def test_limit_caps_the_uploads(tmp_path):
    make_mirror(tmp_path, [_event("a", 0), _event("b", 1), _event("c", 2)])
    fake = FakeSkylight()

    assert make_sync(tmp_path, fake)[0].sync(limit=2).uploaded == 2
    assert len(fake.messages) == 2


def test_resumes_an_interrupted_run_without_reuploading(tmp_path):
    make_mirror(tmp_path, [_event("a", 0), _event("b", 1)])
    (tmp_path / "skylight-uploads.jsonl").write_text(
        json.dumps({"status": "uploaded", "trace_id": "a", "message_id": "55"}) + "\n"
    )
    fake = FakeSkylight()
    fake.messages.append({"id": "55", "caption": "x", "created_at": "2026-10-27T00:00:00Z"})
    sync, _ = make_sync(tmp_path, fake)

    summary = sync.sync()

    assert summary.uploaded == 1
    assert fake.names().count("photo-upload") == 1  # only "b"
    assert "55" in fake.album  # the interrupted one was finished


def test_ledger_entries_already_in_the_album_are_left_alone(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    (tmp_path / "skylight-uploads.jsonl").write_text(
        json.dumps({"status": "uploaded", "trace_id": "a", "message_id": "55"})
        + "\n"
        + json.dumps({"status": "in_album", "message_ids": ["55"]})
        + "\n"
    )
    fake = FakeSkylight()

    make_sync(tmp_path, fake)[0].sync()

    assert "album-add-photos" not in fake.names()
    assert "photo-upload" not in fake.names()


# --- frame and album resolution ---------------------------------------------------------------


def test_a_single_frame_is_used_automatically(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    make_sync(tmp_path, fake)[0].sync()

    upload = next(c for c in fake.calls if c[0] == "photo-upload")
    assert upload[upload.index("--frame") + 1] == "F1"


def test_multiple_frames_require_an_explicit_choice(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight(frames=[{"id": "F1"}, {"id": "F2"}])

    with pytest.raises(SyncStopped, match="SKYLIGHT_FRAME_ID"):
        make_sync(tmp_path, fake)[0].sync()


def test_an_explicit_frame_skips_the_lookup(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight(frames=[{"id": "F1"}, {"id": "F2"}])
    make_sync(tmp_path, fake, frame_id="F2")[0].sync()

    assert "frames" not in fake.names()
    assert all(c[c.index("--frame") + 1] == "F2" for c in fake.calls if "--frame" in c)


def test_the_album_is_created_when_missing(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight(albums=[])

    make_sync(tmp_path, fake)[0].sync()

    assert "album-add" in fake.names()
    assert fake.album == [fake.messages[0]["id"]]


# --- album adds Skylight silently ignores --------------------------------------------------------


def test_album_adds_that_are_silently_ignored_are_retried_until_they_show_up(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.ignore_album_adds = 2
    sync, sleeps = make_sync(tmp_path, fake)

    sync.sync()

    assert fake.album == [fake.messages[0]["id"]]
    assert fake.names().count("album-add-photos") == 3
    assert sleeps  # waited between attempts


def test_an_album_add_that_never_lands_stops_the_run(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.ignore_album_adds = 99

    with pytest.raises(SyncStopped, match="never showed up in the album"):
        make_sync(tmp_path, fake)[0].sync()

    assert [r["status"] for r in ledger(tmp_path)] == ["uploaded"]  # upload is kept, no false in_album


# --- rate limits and failures ---------------------------------------------------------------------


def test_rate_limit_backs_off_exponentially_and_slows_the_pace(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.failures["photo-upload"] = [RATE_LIMIT, RATE_LIMIT]
    sync, sleeps = make_sync(tmp_path, fake, pace=2.0)

    summary = sync.sync()

    assert summary.uploaded == 1 and summary.rate_limited == 2
    assert sleeps[:2] == [60, 120]
    assert sync.pace == 8.0


def test_server_errors_and_timeouts_are_retried(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.failures["photo-upload"] = [SERVER_ERROR, RunResult(124, "", "timed out")]
    sync, sleeps = make_sync(tmp_path, fake)

    summary = sync.sync()

    assert summary.uploaded == 1 and summary.transient == 2
    assert sleeps[:2] == [30, 60]


def test_persistent_server_errors_give_up_after_eight_attempts(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.failures["photo-upload"] = [SERVER_ERROR] * 20

    with pytest.raises(SyncStopped, match="8 attempts"):
        make_sync(tmp_path, fake)[0].sync()

    assert fake.names().count("photo-upload") == 8


def test_an_expired_session_stops_immediately_and_says_how_to_fix_it(tmp_path):
    make_mirror(tmp_path, [_event("a"), _event("b", 1)])
    fake = FakeSkylight()
    sleeps: list[float] = []
    uploads = {"count": 0}

    def session_dies_on_the_second_upload(args):
        if args[0] == "photo-upload":
            uploads["count"] += 1
            if uploads["count"] == 2:
                return AUTH_ERROR
        return fake(args)

    sync = SkylightSync(tmp_path, session_dies_on_the_second_upload, sleep=sleeps.append, log=lambda m: None)

    with pytest.raises(SyncStopped, match="skylight-login"):
        sync.sync()

    assert sleeps == [2.0]  # just the normal pause after the first upload, no backoff
    assert [r["trace_id"] for r in ledger(tmp_path) if r["status"] == "uploaded"] == ["a"]


def test_client_errors_are_not_retried(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.failures["photo-upload"] = [err("SkylightAPIError", "POST /x failed with HTTP 422")]

    with pytest.raises(SyncStopped, match="422"):
        make_sync(tmp_path, fake)[0].sync()

    assert fake.names().count("photo-upload") == 1


# --- duplicate protection ---------------------------------------------------------------------------


def test_an_upload_that_failed_after_skylight_created_it_is_adopted_not_repeated(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.failures["photo-upload"] = [SERVER_ERROR]
    fake.upload_creates_message_despite_failure = True
    sync, _ = make_sync(tmp_path, fake)

    summary = sync.sync()

    assert summary.uploaded == 1 and summary.adopted == 1
    assert len(fake.messages) == 1
    assert fake.names().count("photo-upload") == 1
    assert fake.album == [fake.messages[0]["id"]]


def test_a_successful_upload_with_no_message_id_in_the_output_is_found_by_caption(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.upload_output = "{}"

    summary = make_sync(tmp_path, fake)[0].sync()

    assert summary.uploaded == 1
    assert fake.album == [fake.messages[0]["id"]]


def test_a_message_that_cannot_be_found_stops_the_run(tmp_path):
    make_mirror(tmp_path, [_event("a")])
    fake = FakeSkylight()
    fake.upload_output = "{}"
    original = fake.__call__

    def vanishing(args):
        result = original(args)
        if args[0] == "photo-upload":
            fake.messages.clear()
        return result

    with pytest.raises(SyncStopped, match="no message id"):
        SkylightSync(tmp_path, vanishing, sleep=lambda s: None, log=lambda m: None).sync()
