import asyncio
from unittest.mock import AsyncMock, patch

from water.flo.client import FloValve
from water.water_cli import cmd_status, format_status


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


class _FakeApiCtx:
    """Stand-in for water.flo.client.with_api()'s async context manager."""

    async def __aenter__(self):
        return "fake-api"

    async def __aexit__(self, *exc_info):
        return False


def test_status_prints_explicit_message_when_no_devices(capsys):
    # An account with no paired devices used to fall through to
    # "\n\n".join([]) -- an empty string -- and exit 0 with no output at all,
    # indistinguishable from a hang or a silent failure.
    async def _run():
        with (
            patch("water.water_cli.with_api", return_value=_FakeApiCtx()),
            patch("water.water_cli.fetch_raw", new=AsyncMock(return_value={"devices": []})),
        ):
            await cmd_status(json_output=False)

    asyncio.run(_run())
    assert capsys.readouterr().out.strip() == "No Flo devices on this account."


def test_device_redacts_by_default(capsys):
    from water.water_cli import cmd_device

    payload = {"user": {"email": "josh@example.com"}, "locations": [], "devices": []}

    async def _run():
        with (
            patch("water.water_cli.with_api", return_value=_FakeApiCtx()),
            patch("water.water_cli.fetch_raw", new=AsyncMock(return_value=payload)),
        ):
            await cmd_device(unredacted=False)

    asyncio.run(_run())
    captured = capsys.readouterr()
    assert "josh@example.com" not in captured.out
    assert "REDACTED" in captured.out
    assert captured.err == ""


def test_device_unredacted_skips_scrub_and_warns_on_stderr(capsys):
    from water.water_cli import cmd_device

    payload = {"user": {"email": "josh@example.com"}, "locations": [], "devices": []}

    async def _run():
        with (
            patch("water.water_cli.with_api", return_value=_FakeApiCtx()),
            patch("water.water_cli.fetch_raw", new=AsyncMock(return_value=payload)),
        ):
            await cmd_device(unredacted=True)

    asyncio.run(_run())
    captured = capsys.readouterr()
    assert "josh@example.com" in captured.out
    assert "email" in captured.err.lower() or "mac" in captured.err.lower()
    assert captured.err.strip() != ""
