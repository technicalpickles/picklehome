import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

LAST_STATE_FILE = "last-state.json"
RUN_LOG_FILE = "run-log.jsonl"


def get_data_dir() -> Path:
    env_path = os.environ.get("CLIMATE_DATA_DIR")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "state" / "picklehome"


def read_last_state(data_dir: Path) -> dict | None:
    path = data_dir / LAST_STATE_FILE
    if not path.exists():
        return None
    # A power loss between open(path, "w") and the completed json.dump in
    # write_last_state leaves a torn/partial file. This value is purely
    # informational (previous_mode gates no behavior, it only appears in log
    # entries), so a corrupt file must degrade to "unknown" rather than
    # raising -- an unguarded JSONDecodeError here would crash before any
    # write happens, permanently bricking the unattended timer since the
    # file is never repaired and nothing alerts on it.
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def write_last_state(data_dir: Path, state: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / LAST_STATE_FILE
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def append_run_log(data_dir: Path, entry: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / RUN_LOG_FILE
    with open(path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


LOCAL_TZ = ZoneInfo("America/New_York")


def now_iso() -> str:
    return datetime.now(LOCAL_TZ).isoformat()


def read_recent_outdoor_temps(
    data_dir: Path,
    hours: int = 24,
    now: datetime | None = None,
    tail_bytes: int = 262144,
) -> list[float]:
    """Outdoor temps logged within the last `hours`, oldest first.

    Only the tail of the log is read. At roughly 870 bytes/entry, 256KB covers
    well over a day of 15-minute samples, and the log grows ~30MB/year.

    Malformed lines are skipped rather than raising: one bad append should
    degrade the sample count (which the caller already guards on) instead of
    blinding the decision entirely.
    """
    path = data_dir / RUN_LOG_FILE
    if not path.exists():
        return []
    if now is None:
        now = datetime.now(LOCAL_TZ)
    cutoff = now - timedelta(hours=hours)

    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - tail_bytes))
        chunk = f.read()

    lines = chunk.decode("utf-8", errors="replace").splitlines()
    # A tail read almost certainly starts mid-line; that fragment is not valid
    # JSON and would be skipped anyway, but drop it explicitly for clarity.
    if size > tail_bytes and lines:
        lines = lines[1:]

    temps: list[float] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry["timestamp"])
            temp = entry["outdoor_temp_f"]
            if temp is None:
                continue
            # Skip entries with offset-naive timestamps. The log is always written with
            # LOCAL_TZ, so a naive timestamp means a corrupt or foreign entry; guessing
            # its zone would silently shift a reading by hours.
            if ts >= cutoff:
                temps.append(float(temp))
        except (ValueError, KeyError, TypeError):
            # Skip malformed entries: bad JSON, missing keys, invalid timestamps,
            # or non-numeric temps. One corrupt log line should degrade the sample
            # count instead of blinding the entire decision.
            continue
    return temps
