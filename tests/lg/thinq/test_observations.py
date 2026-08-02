from datetime import datetime, timedelta, timezone

from lg.thinq.observations import (
    CompletionEstimate,
    append_observation,
    find_counter_increment,
    read_observations,
)

DEVICE = "washer-0000-0000-0000-000000000001"
BASE = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _record(device_id: str, ts: datetime, **fields) -> dict:
    return {"timestamp": ts, "device_id": device_id, "fields": fields}


# ---------------------------------------------------------------------------
# append_observation / read_observations round trip
# ---------------------------------------------------------------------------


def test_append_and_read_round_trip(tmp_path):
    log_path = tmp_path / "observations.jsonl"
    append_observation(log_path, DEVICE, BASE, {"state": "RUNNING", "cycle_count": 48})
    append_observation(log_path, DEVICE, BASE + timedelta(minutes=1), {"state": "POWER_OFF", "cycle_count": 49})

    records = read_observations(log_path)

    assert len(records) == 2
    assert records[0]["device_id"] == DEVICE
    assert records[0]["timestamp"] == BASE
    assert records[0]["fields"] == {"state": "RUNNING", "cycle_count": 48}
    assert records[1]["fields"]["cycle_count"] == 49


def test_append_creates_parent_directories(tmp_path):
    log_path = tmp_path / "nested" / "dir" / "observations.jsonl"
    append_observation(log_path, DEVICE, BASE, {"state": "RUNNING"})

    assert log_path.exists()
    assert len(read_observations(log_path)) == 1


def test_read_observations_missing_file_returns_empty(tmp_path):
    assert read_observations(tmp_path / "does-not-exist.jsonl") == []


def test_read_observations_skips_corrupt_lines(tmp_path):
    log_path = tmp_path / "observations.jsonl"
    log_path.write_text(
        '{"timestamp": "2026-08-02T12:00:00+00:00", "device_id": "d1", "fields": {"a": 1}}\n'
        "not json at all\n"
        '{"timestamp": "not-a-timestamp", "device_id": "d1", "fields": {"a": 2}}\n'
        '{"device_id": "d1", "fields": {"a": 3}}\n'  # missing timestamp
        "\n"  # blank line
        '{"timestamp": "2026-08-02T12:05:00+00:00", "device_id": "d1", "fields": {"a": 4}}\n'
    )

    records = read_observations(log_path)

    assert len(records) == 2
    assert records[0]["fields"]["a"] == 1
    assert records[1]["fields"]["a"] == 4


def test_read_observations_skips_naive_timestamps(tmp_path):
    # A naive (tz-less) timestamp -- e.g. from a future watcher writing
    # `datetime.now().isoformat()` without a zone -- must not poison every
    # future read: mixing naive and aware datetimes raises TypeError the
    # moment find_counter_increment tries to sort them. Treat it as a
    # skippable bad record, same as a corrupt line.
    log_path = tmp_path / "observations.jsonl"
    log_path.write_text(
        '{"timestamp": "2026-08-02T12:00:00", "device_id": "d1", "fields": {"a": 1}}\n'  # naive
        '{"timestamp": "2026-08-02T12:05:00+00:00", "device_id": "d1", "fields": {"a": 2}}\n'
    )

    records = read_observations(log_path)

    assert len(records) == 1
    assert records[0]["fields"]["a"] == 2


def test_find_counter_increment_tolerates_a_naive_record_mixed_in(tmp_path):
    # The real regression: without the skip, sorting a mix of naive and
    # aware timestamps raises TypeError inside find_counter_increment, not
    # just read_observations -- a single bad record would take down every
    # future completion estimate for the device, not just its own line.
    log_path = tmp_path / "observations.jsonl"
    log_path.write_text(
        '{"timestamp": "2026-08-02T12:00:00", "device_id": "'
        + DEVICE
        + '", "fields": {"cycle_count": 1}}\n'  # naive -- must be skipped, not crash the sort
        '{"timestamp": "2026-08-02T12:00:00+00:00", "device_id": "'
        + DEVICE
        + '", "fields": {"cycle_count": 48}}\n'
        '{"timestamp": "2026-08-02T12:01:01+00:00", "device_id": "'
        + DEVICE
        + '", "fields": {"cycle_count": 49}}\n'
    )

    records = read_observations(log_path)
    now = datetime(2026, 8, 2, 14, 0, 0, tzinfo=timezone.utc)

    estimate = find_counter_increment(records, DEVICE, "cycle_count", 49, now=now)

    assert estimate is not None


# ---------------------------------------------------------------------------
# find_counter_increment: the degradation table from the design doc
# ---------------------------------------------------------------------------


def test_empty_log_yields_no_estimate():
    now = BASE + timedelta(hours=1)
    assert find_counter_increment([], DEVICE, "cycle_count", 49, now=now) is None


def test_no_transition_present_yields_no_estimate():
    # Counter has always read 49 in the log; nothing proves a cycle completed.
    records = [
        _record(DEVICE, BASE, cycle_count=49),
        _record(DEVICE, BASE + timedelta(minutes=30), cycle_count=49),
    ]
    now = BASE + timedelta(hours=1)
    assert find_counter_increment(records, DEVICE, "cycle_count", 49, now=now) is None


def test_clean_transition_yields_tight_bounds():
    # 48 -> 49 observed 61 seconds apart (the actual measured cadence from
    # docs/research/lg-thinq/findings.md), then queried 2h14m later.
    t1 = BASE
    t2 = BASE + timedelta(seconds=61)
    records = [
        _record(DEVICE, t1, cycle_count=48),
        _record(DEVICE, t2, cycle_count=49),
    ]
    now = t2 + timedelta(hours=2, minutes=14)

    estimate = find_counter_increment(records, DEVICE, "cycle_count", 49, now=now)

    assert estimate is not None
    assert estimate.earliest_ago == timedelta(hours=2, minutes=14)
    assert estimate.latest_ago == timedelta(hours=2, minutes=14, seconds=61)
    assert estimate.describe() == "finished about 2h 14m ago"


def test_first_seen_this_invocation_yields_within_the_last_wording():
    # Last known-lower observation is 6 hours before "now"; nothing has
    # logged the higher value yet, so this call is the first to see it --
    # earliest_ago is 0 (detected right now), latest_ago is bounded by
    # last_low. Must never claim a point estimate here.
    t1 = BASE
    records = [_record(DEVICE, t1, cycle_count=48)]
    now = BASE + timedelta(hours=6)

    estimate = find_counter_increment(records, DEVICE, "cycle_count", 49, now=now)

    assert estimate is not None
    assert estimate.earliest_ago == timedelta(0)
    assert estimate.latest_ago == timedelta(hours=6)
    assert estimate.describe() == "finished within the last 6h"


def test_stale_log_with_high_value_already_recorded_bounds_the_elapsed_range():
    # Regression for the finding: a washer whose cycle finished 7 days ago
    # (48 at day-8, 48->49 transition first recorded at day-7) must render as
    # a wide, honest range -- never as "sometime in the last 24h" (the old
    # bug: rendering just the width of the detection window, `gap`, instead
    # of time-since-detection). The old test only ever exercised the
    # first_high-is-None path (test_first_seen_this_invocation_yields_...
    # above); this one puts a real, already-logged `first_high` in the log,
    # which is what earlier let this bug ship invisibly.
    t_low = BASE  # last seen at 47 -- day "-8" relative to now
    t_high = BASE + timedelta(days=1)  # first seen at 48 -- day "-7" relative to now
    records = [
        _record(DEVICE, t_low, cycle_count=47),
        _record(DEVICE, t_high, cycle_count=48),
    ]
    now = t_high + timedelta(days=7)

    estimate = find_counter_increment(records, DEVICE, "cycle_count", 48, now=now)

    assert estimate is not None
    assert estimate.earliest_ago == timedelta(days=7)
    assert estimate.latest_ago == timedelta(days=8)
    text = estimate.describe()
    assert text == "finished between 7d and 8d ago"
    # Must not understate this as a recent event.
    assert "24h" not in text
    assert "last 24h" not in text


def test_back_to_back_cycles_use_only_the_most_recent_transition():
    # 48 -> 49 (close gap, long ago) then 49 -> 50 (close gap, recent).
    # Querying for current_value=50 must use the second transition, not the first.
    t1 = BASE
    t2 = BASE + timedelta(minutes=1)
    t3 = BASE + timedelta(hours=10)
    t4 = BASE + timedelta(hours=10, minutes=1)
    records = [
        _record(DEVICE, t1, cycle_count=48),
        _record(DEVICE, t2, cycle_count=49),
        _record(DEVICE, t3, cycle_count=49),
        _record(DEVICE, t4, cycle_count=50),
    ]
    now = t4 + timedelta(minutes=20)

    estimate = find_counter_increment(records, DEVICE, "cycle_count", 50, now=now)

    assert estimate is not None
    assert estimate.earliest_ago == timedelta(minutes=20)
    assert estimate.describe() == "finished about 20m ago"


def test_ignores_other_devices():
    other_device = "dryer-0000-0000-0000-000000000002"
    records = [
        _record(other_device, BASE, cycle_count=1),
        _record(other_device, BASE + timedelta(minutes=1), cycle_count=99),
    ]
    now = BASE + timedelta(hours=1)

    assert find_counter_increment(records, DEVICE, "cycle_count", 99, now=now) is None


def test_describe_tight_window_wording():
    estimate = CompletionEstimate(earliest_ago=timedelta(minutes=5), latest_ago=timedelta(minutes=5))
    assert estimate.describe() == "finished about 5m ago"


def test_describe_wide_window_wording():
    estimate = CompletionEstimate(earliest_ago=timedelta(hours=3), latest_ago=timedelta(hours=9))
    assert estimate.describe() == "finished between 3h and 9h ago"


def test_describe_zero_earliest_ago_wording():
    estimate = CompletionEstimate(earliest_ago=timedelta(0), latest_ago=timedelta(hours=3))
    assert estimate.describe() == "finished within the last 3h"


def test_format_duration_adds_a_day_unit():
    # finding #7: _format_duration topped out at hours ("finished 504h ago").
    estimate = CompletionEstimate(earliest_ago=timedelta(hours=504), latest_ago=timedelta(hours=504))
    assert estimate.describe() == "finished about 21d ago"
