import json
from pathlib import Path

from climate.runlog import (
    get_data_dir,
    read_last_state,
    write_last_state,
    append_run_log,
)


def test_get_data_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIMATE_DATA_DIR", str(tmp_path))
    assert get_data_dir() == tmp_path


def test_get_data_dir_default(monkeypatch):
    monkeypatch.delenv("CLIMATE_DATA_DIR", raising=False)
    result = get_data_dir()
    assert "picklehome" in str(result)


def test_read_last_state_missing(tmp_path):
    assert read_last_state(tmp_path) is None


def test_read_last_state_exists(tmp_path):
    state = {"timestamp": "2026-03-27T06:00:00Z", "mode": "cool", "outdoor_temp_f": 66.6, "thermostats": []}
    (tmp_path / "last-state.json").write_text(json.dumps(state))
    assert read_last_state(tmp_path) == state


def test_write_last_state(tmp_path):
    state = {"timestamp": "2026-03-27T06:00:00Z", "mode": "cool", "outdoor_temp_f": 66.6, "thermostats": []}
    write_last_state(tmp_path, state)
    written = json.loads((tmp_path / "last-state.json").read_text())
    assert written == state


def test_append_run_log(tmp_path):
    entry1 = {"timestamp": "2026-03-27T06:00:00Z", "decision": "cool"}
    entry2 = {"timestamp": "2026-03-27T12:00:00Z", "decision": "cool"}
    append_run_log(tmp_path, entry1)
    append_run_log(tmp_path, entry2)

    lines = (tmp_path / "run-log.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == entry1
    assert json.loads(lines[1]) == entry2


def test_append_run_log_creates_file(tmp_path):
    entry = {"timestamp": "2026-03-27T06:00:00Z", "decision": "heat"}
    append_run_log(tmp_path, entry)
    assert (tmp_path / "run-log.jsonl").exists()
