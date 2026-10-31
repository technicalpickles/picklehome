"""Upload mirrored bird clips to a Skylight album, safe to leave running unattended.

A consumer of the local mirror (`birdfeeder/mirror.py`): it never touches the VicoHome API. It shells
out to `scripts/skylight` (pyskylight, pinned) because Skylight's API is unofficial and undocumented,
so failure handling matters more than speed:

- HTTP 429: exponential backoff (60s up to 30min), and the pause between uploads doubles for the rest
  of the run (it relaxes again after a long clean streak). pyskylight's CLI output drops the
  Retry-After header, so the server's requested delay can't be honored.
- 5xx, network errors, timeouts: exponential backoff (30s up to 10min), 8 attempts per call.
- An expired session (needs the emailed-code login), Plus-required, other 4xx: stop at once. Retrying
  can't fix them.
- A failed upload may still have created the message. Before retrying, look for it by caption and
  adopt it instead of uploading a duplicate.
- Skylight silently ignores an album add that lands before it finishes processing a new upload (the
  call succeeds, nothing is added), so adds are verified against the album and retried with growing
  waits. A clip that still hasn't landed is carried into the next batch rather than ending the run
  (the upload is already in the ledger); one that stays missing across three batches, or is still
  missing at the end, stops it. Verification reads `album-message-ids`, which returns only the newest
  100, so adds go in batches well under that.

The ledger (`skylight-uploads.jsonl` in the mirror directory) records each upload's message id the
moment it succeeds, which makes runs resumable and undoable (`skylight messages-delete --id ...`).
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

SKYLIGHT_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "skylight"
LEDGER_NAME = "skylight-uploads.jsonl"
DEFAULT_ALBUM_TITLE = "Birds"

CALL_TIMEOUT_SECONDS = 300
MAX_ATTEMPTS = 8
ALBUM_ADD_ATTEMPTS = 6
ALBUM_SETTLE_SECONDS = 3
MAX_ALBUM_SETTLE_SECONDS = 60
MAX_ALBUM_BATCH_MISSES = 3
MAX_PACE_SECONDS = 30.0
CLEAN_STREAK_TO_RELAX = 100
ORPHAN_CLOCK_SKEW = timedelta(seconds=30)


class RunResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], RunResult]


class SyncStopped(RuntimeError):
    """The run stopped for a reason retrying can't fix, or retrying ran out. Progress is saved."""


@dataclass
class SyncSummary:
    uploaded: int = 0
    already_uploaded: int = 0
    adopted: int = 0
    rate_limited: int = 0
    transient: int = 0


def subprocess_runner(timeout: int = CALL_TIMEOUT_SECONDS) -> Runner:
    def run(args: list[str]) -> RunResult:
        try:
            proc = subprocess.run([str(SKYLIGHT_SCRIPT), *args], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return RunResult(124, "", f"timed out after {timeout}s")
        return RunResult(proc.returncode, proc.stdout, proc.stderr)

    return run


def _redact(text: str) -> str:
    return re.sub(r"https?://\S+", "<url>", text)


def classify(result: RunResult) -> tuple[str, str]:
    """Return (kind, detail), where kind is ok, ratelimit, transient, or fatal."""
    if result.returncode == 0:
        return "ok", ""
    payload = None
    for line in reversed(result.stdout.splitlines()):
        if line.strip().startswith("{"):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue
    if payload is None:
        # Not a Skylight error payload (crash, usage error, runner hiccup): retry a bit, then give up.
        return "transient", _redact(result.stderr or result.stdout)[-200:].strip() or f"exit {result.returncode}"
    kind, message = payload.get("type", ""), payload.get("error", "")
    if kind == "SkylightRateLimitError":
        return "ratelimit", message
    if kind in ("SkylightAuthError", "SkylightPlusRequiredError", "SkylightNotFoundError"):
        return "fatal", f"{kind}: {message}"
    status = re.search(r"HTTP (\d{3})", message)
    if status:
        code = int(status.group(1))
        return ("transient" if code >= 500 or code in (408, 425) else "fatal"), f"{kind}: {message}"
    # Network errors and other unclassified Skylight errors: transient, attempts are capped.
    return "transient", f"{kind}: {_redact(message)[:200]}"


def caption_for(species: str | None, timestamp: datetime, tz: tzinfo | None = None) -> str:
    local = timestamp.astimezone(tz)
    clock = f"{local:%-I:%M}{local:%p}".lower()
    return f"{species or 'Bird'}, {local:%a %b} {local.day} {clock}"


class SkylightSync:
    def __init__(
        self,
        root: Path,
        run: Runner,
        *,
        frame_id: str | None = None,
        album_title: str = DEFAULT_ALBUM_TITLE,
        pace: float = 2.0,
        album_batch: int = 20,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print,
    ):
        self.root = root
        self.ledger_path = root / LEDGER_NAME
        self._run = run
        self.frame_id = frame_id
        self.album_title = album_title
        self.base_pace = pace
        self.pace = pace
        self.album_batch = album_batch
        self._sleep = sleep
        self._log = log
        self._clean_streak = 0
        self._album_id: str | None = None
        self._tz: tzinfo | None = None
        self._carried: list[str] = []
        self._batch_misses: dict[str, int] = {}
        self.summary = SyncSummary()

    # -- calling the CLI with classified retries --------------------------------------------------

    def _call(self, args: list[str], recover: Callable[[], str | None] | None = None) -> str:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            result = self._run(args)
            kind, detail = classify(result)
            if kind == "ok":
                self._clean_streak += 1
                if self._clean_streak >= CLEAN_STREAK_TO_RELAX and self.pace > self.base_pace:
                    self.pace = max(self.base_pace, self.pace / 2)
                    self._clean_streak = 0
                    self._log(f"relaxing pace to {self.pace:.1f}s between uploads")
                return result.stdout
            self._clean_streak = 0
            if kind == "fatal":
                hint = " Run `just skylight-login` to sign in again." if "AuthError" in detail else ""
                raise SyncStopped(f"{args[0]} failed and retrying can't fix it: {detail}.{hint}")
            if kind == "ratelimit":
                self.summary.rate_limited += 1
                wait = min(60 * 2 ** (attempt - 1), 1800)
                self.pace = min(self.pace * 2, MAX_PACE_SECONDS)
                self._log(f"rate limited on {args[0]} (attempt {attempt}/{MAX_ATTEMPTS}); sleeping {wait}s, pace now {self.pace:.1f}s")
            else:
                self.summary.transient += 1
                wait = min(30 * 2 ** (attempt - 1), 600)
                self._log(f"{args[0]} failed (attempt {attempt}/{MAX_ATTEMPTS}): {detail}; sleeping {wait}s")
            self._sleep(wait)
            if recover:
                recovered = recover()
                if recovered is not None:
                    return recovered
        raise SyncStopped(f"{args[0]} still failing after {MAX_ATTEMPTS} attempts")

    # -- frame and album ------------------------------------------------------------------------------

    def _resolve_frame(self) -> str:
        if self.frame_id:
            return self.frame_id
        frames = json.loads(self._call(["frames"]))
        if len(frames) != 1:
            raise SyncStopped(f"found {len(frames)} Skylight frames; set SKYLIGHT_FRAME_ID to pick one")
        self.frame_id = frames[0]["id"]
        zone = frames[0].get("attributes", {}).get("timezone")
        self._tz = ZoneInfo(zone) if zone else None
        return self.frame_id

    def _resolve_album(self) -> str:
        if self._album_id:
            return self._album_id
        albums = json.loads(self._call(["albums", "--frame", self.frame_id]))["data"]
        for album in albums:
            if album["attributes"]["title"] == self.album_title:
                self._album_id = album["id"]
                return self._album_id
        created = json.loads(self._call(["album-add", "--title", self.album_title, "--frame", self.frame_id]))["data"]
        self._album_id = created["id"]
        self._log(f"created album {self.album_title!r}")
        return self._album_id

    def _album_members(self) -> set[str]:
        out = self._call(["album-message-ids", self._album_id, "--frame", self.frame_id])
        return {item["id"] for item in json.loads(out)["data"]}

    def _confirm_in_album(self, message_ids: list[str]) -> list[str]:
        """Add these to the album, retrying with growing waits. Returns the ids that never landed."""
        missing = [m for m in message_ids if m not in self._album_members()]
        for attempt in range(1, ALBUM_ADD_ATTEMPTS + 1):
            if not missing:
                break
            args = ["album-add-photos", "--album-id", self._album_id, "--frame", self.frame_id]
            for message_id in missing:
                args += ["--message-id", message_id]
            self._call(args)
            self._sleep(min(ALBUM_SETTLE_SECONDS * 2 ** (attempt - 1), MAX_ALBUM_SETTLE_SECONDS))
            present = self._album_members()
            missing = [m for m in missing if m not in present]
            if missing:
                self._log(f"  {len(missing)} not in album yet (attempt {attempt})")
        return missing

    def _add_to_album(self, message_ids: list[str], final: bool = False) -> None:
        """Add (plus anything carried over) in batches, recording only what's confirmed in the album.

        Unconfirmed ids are carried into the next call. They stop the run if they stay missing across
        MAX_ALBUM_BATCH_MISSES batches, or if `final` and anything is still missing: the uploads are in
        the ledger either way, and the next run finishes the add.
        """
        ids = list(dict.fromkeys(self._carried + message_ids))
        self._carried = []
        for start in range(0, len(ids), self.album_batch):
            batch = ids[start : start + self.album_batch]
            missing = self._confirm_in_album(batch)
            confirmed = [m for m in batch if m not in missing]
            if confirmed:
                self._append({"status": "in_album", "message_ids": confirmed})
                self._log(f"  album +{len(confirmed)} (confirmed)")
            for message_id in confirmed:
                self._batch_misses.pop(message_id, None)
            for message_id in missing:
                self._batch_misses[message_id] = self._batch_misses.get(message_id, 0) + 1
            stuck = [m for m in missing if self._batch_misses[m] >= MAX_ALBUM_BATCH_MISSES]
            if stuck or (final and missing):
                raise SyncStopped(
                    f"{len(missing)} message(s) never showed up in the album: {missing[:5]}"
                    " (the uploads are recorded; the next run will retry the add)"
                )
            if missing:
                self._log(f"  carrying {len(missing)} unconfirmed clip(s) into the next batch")
                self._carried.extend(missing)

    # -- uploading --------------------------------------------------------------------------------------

    def _find_message(self, known_ids: set[str], caption: str, since: datetime) -> str | None:
        """A message with this caption, created since `since`, that the ledger doesn't know about."""
        for message in json.loads(self._call(["messages", "--frame", self.frame_id]))["data"]:
            attrs = message["attributes"]
            created = datetime.fromisoformat(attrs["created_at"].replace("Z", "+00:00"))
            if message["id"] not in known_ids and attrs.get("caption") == caption and created >= since - ORPHAN_CLOCK_SKEW:
                return message["id"]
        return None

    def _upload(self, path: Path, caption: str, known_ids: set[str]) -> str:
        started = datetime.now(timezone.utc)

        def adopt() -> str | None:
            orphan = self._find_message(known_ids, caption, started)
            if orphan is None:
                return None
            self.summary.adopted += 1
            self._log(f"  adopting message {orphan}: Skylight created it though the call failed")
            return f"recipient_message_ids={orphan}"

        out = self._call(["photo-upload", "--file", str(path), "--caption", caption, "--frame", self.frame_id], recover=adopt)
        match = re.search(r"recipient_message_ids=(\d+)", out)
        if match:
            return match.group(1)
        # Succeeded but the output didn't carry the id: find the message instead.
        found = self._find_message(known_ids, caption, started)
        if found is None:
            raise SyncStopped(f"upload of {path.name} returned no message id and no matching message was found")
        return found

    # -- ledger and mirror ------------------------------------------------------------------------------

    def _read_ledger(self) -> tuple[dict[str, str], set[str]]:
        uploaded: dict[str, str] = {}
        in_album: set[str] = set()
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text().splitlines():
                record = json.loads(line)
                if record["status"] == "uploaded":
                    uploaded[record["trace_id"]] = record["message_id"]
                elif record["status"] == "in_album":
                    in_album.update(record["message_ids"])
        return uploaded, in_album

    def _append(self, record: dict) -> None:
        with self.ledger_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def _mirror_rows(self, include_unidentified: bool) -> list[tuple[str, str, str | None, str]]:
        db_path = self.root / "mirror.sqlite3"
        if not db_path.exists():
            raise SyncStopped(f"no mirror at {self.root}; run `just birdfeeder sync` first")
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            identified = "" if include_unidentified else " AND species_name IS NOT NULL"
            return db.execute(
                "SELECT trace_id, timestamp, species_name, video_path FROM events"
                f" WHERE video_path IS NOT NULL{identified} ORDER BY timestamp"
            ).fetchall()
        finally:
            db.close()

    # -- the sync -----------------------------------------------------------------------------------------

    def sync(self, limit: int | None = None, include_unidentified: bool = False) -> SyncSummary:
        self._resolve_frame()
        self._resolve_album()
        uploaded, in_album = self._read_ledger()

        # An interrupted run may have uploaded without finishing the album add.
        self._add_to_album([m for m in uploaded.values() if m not in in_album])
        if self._carried:
            self._add_to_album([])  # give the stragglers one more full retry window before new uploads

        rows = self._mirror_rows(include_unidentified)
        pending = [r for r in rows if r[0] not in uploaded]
        self.summary.already_uploaded = len(rows) - len(pending)
        if limit is not None:
            pending = pending[:limit]
        self._log(f"{len(rows)} eligible clips, {self.summary.already_uploaded} already uploaded, uploading {len(pending)}")

        known_ids = set(uploaded.values())
        batch: list[str] = []
        for i, (trace_id, timestamp, species, video_path) in enumerate(pending, 1):
            caption = caption_for(species, datetime.fromisoformat(timestamp), self._tz)
            message_id = self._upload(self.root / video_path, caption, known_ids)
            self._append({"status": "uploaded", "trace_id": trace_id, "message_id": message_id, "at": datetime.now(timezone.utc).isoformat()})
            known_ids.add(message_id)
            batch.append(message_id)
            self.summary.uploaded += 1
            self._log(f"[{i}/{len(pending)}] {caption} -> {message_id}")
            if len(batch) >= self.album_batch:
                self._add_to_album(batch)
                batch = []
            self._sleep(self.pace)
        self._add_to_album(batch, final=True)
        return self.summary
