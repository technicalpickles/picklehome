from water.flo.client import FloValve
from water.water_cli import format_status


def _valve(**overrides):
    base = dict(
        name="Main Shutoff",
        state="open",
        mode="home",
        gpm=0.0,
        psi=62.0,
        temp_f=68.0,
        telemetry_updated="2026-09-04T11:57:00Z",
        rssi=-54,
        connected=True,
        pending_alerts=0,
    )
    base.update(overrides)
    return FloValve(**base)


def test_renders_every_field():
    out = format_status(_valve())
    assert "Main Shutoff" in out
    assert "open" in out
    assert "0.0 gpm" in out
    assert "62 psi" in out
    assert "68 °F" in out
    assert "home" in out
    assert "-54 dBm" in out
    assert "none" in out


def test_distinguishes_no_reading_from_zero():
    assert "0.0 gpm" in format_status(_valve(gpm=0.0))
    assert "no reading" in format_status(_valve(gpm=None))


def test_pluralizes_and_counts_alerts():
    assert "none" in format_status(_valve(pending_alerts=0))
    assert "1 pending" in format_status(_valve(pending_alerts=1))
    assert "3 pending" in format_status(_valve(pending_alerts=3))


def test_flags_a_closed_valve_and_a_disconnected_device():
    assert "closed" in format_status(_valve(state="closed"))
    assert "disconnected" in format_status(_valve(connected=False))


def test_telemetry_timestamp_is_visible_when_present():
    # A telemetry reading can be hours stale (see FloValve.telemetry_updated
    # docstring); the timestamp must be visible in the default output, not
    # just --json, or the flow/pressure numbers read as live when they aren't.
    out = format_status(_valve(telemetry_updated="2026-09-04T11:57:00Z"))
    assert "2026-09-04T11:57:00Z" in out


def test_missing_telemetry_timestamp_does_not_crash_or_render_a_stray_note():
    out = format_status(_valve(telemetry_updated=None, gpm=None, psi=None, temp_f=None))
    assert "no reading" in out
    assert "as of None" not in out
