import json
import os
from datetime import datetime
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
    with open(path) as f:
        return json.load(f)


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
