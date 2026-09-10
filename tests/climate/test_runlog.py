import json
from datetime import datetime, timedelta
from pathlib import Path

from climate.runlog import (
    LOCAL_TZ,
    append_run_log,
    get_data_dir,
    now_iso,
    read_last_state,
    read_recent_outdoor_temps,
    write_last_state,
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


def test_now_iso_uses_eastern_timezone():
    ts = now_iso()
    # Should contain an offset like -04:00 or -05:00 (EDT/EST)
    assert "-04:00" in ts or "-05:00" in ts


def _write_log(data_dir, entries):
    path = data_dir / "run-log.jsonl"
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _entry(ts, temp):
    return {"timestamp": ts.isoformat(), "outdoor_temp_f": temp, "decision": "cool"}


def test_returns_temps_within_window(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    _write_log(tmp_path, [
        _entry(now - timedelta(hours=1), 70.0),
        _entry(now - timedelta(hours=2), 72.0),
    ])
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [70.0, 72.0]


def test_excludes_entries_outside_window(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    _write_log(tmp_path, [
        _entry(now - timedelta(hours=25), 40.0),
        _entry(now - timedelta(hours=1), 70.0),
    ])
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [70.0]


def test_entry_exactly_at_boundary_is_included(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    _write_log(tmp_path, [_entry(now - timedelta(hours=24), 55.0)])
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [55.0]


def test_malformed_lines_are_skipped(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    path = tmp_path / "run-log.jsonl"
    with open(path, "w") as f:
        f.write("not json at all\n")
        f.write(json.dumps({"timestamp": "garbage", "outdoor_temp_f": 1.0}) + "\n")
        f.write(json.dumps({"timestamp": now.isoformat()}) + "\n")  # no temp key
        f.write(json.dumps(_entry(now, None)) + "\n")               # null temp
        f.write(json.dumps(_entry(now, 68.0)) + "\n")
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [68.0]


def test_missing_log_returns_empty(tmp_path):
    assert read_recent_outdoor_temps(tmp_path, hours=24) == []


def test_partial_first_line_from_tail_read_is_dropped(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    entries = [_entry(now - timedelta(minutes=i), 70.0) for i in range(200)]
    _write_log(tmp_path, entries)
    # tail_bytes small enough to slice mid-line; the partial line must not crash
    # or contribute, and everything fully inside the tail must still be read.
    temps = read_recent_outdoor_temps(tmp_path, hours=24, now=now, tail_bytes=2000)
    assert len(temps) > 0
    assert all(t == 70.0 for t in temps)
    assert len(temps) < 200


def test_non_numeric_temp_is_skipped(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    path = tmp_path / "run-log.jsonl"
    with open(path, "w") as f:
        f.write(json.dumps({"timestamp": now.isoformat(), "outdoor_temp_f": "not-a-number", "decision": "cool"}) + "\n")
        f.write(json.dumps(_entry(now, 68.0)) + "\n")
    # Non-numeric temp should be skipped, not crash
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [68.0]


def test_offset_naive_timestamp_is_skipped(tmp_path):
    now = datetime(2026, 9, 10, 12, 0, tzinfo=LOCAL_TZ)
    path = tmp_path / "run-log.jsonl"
    with open(path, "w") as f:
        # Naive timestamp (no timezone offset)
        f.write(json.dumps({"timestamp": "2026-09-10T12:00:00", "outdoor_temp_f": 65.0, "decision": "cool"}) + "\n")
        f.write(json.dumps(_entry(now, 68.0)) + "\n")
    # Naive timestamp should be skipped, not crash
    assert read_recent_outdoor_temps(tmp_path, hours=24, now=now) == [68.0]
