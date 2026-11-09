"""Unit tests for disk monitor utility."""

import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from homelab.services.disk_monitor import disk_monitor
from homelab.services.disk_monitor.disk_monitor import (
    FILESYSTEMS,
    SshError,
    build_alert,
    calculate_rate,
    estimate_time_to_full,
    parse_df,
    should_alert,
)


class TestParseDf:
    """Test df output parsing."""

    def test_parse_two_filesystems(self):
        df_output = """Filesystem     1K-blocks     Used Available Use% Mounted on
/dev/sda1      312563200 78123456 234439744  25% /
/dev/sdb1      104857600 52428800  52428800  50% /srv"""

        result = parse_df(df_output)

        assert "/" in result
        assert "/srv" in result
        assert result["/"]["used_pct"] == 25
        assert result["/srv"]["used_pct"] == 50
        assert result["/"]["used_gb"] == 74.5
        assert result["/"]["avail_gb"] == 223.6

    def test_parse_single_filesystem(self):
        df_output = """Filesystem     1K-blocks     Used Available Use% Mounted on
/dev/sda1      100000000 80000000  20000000  80% /"""

        result = parse_df(df_output)

        assert len(result) == 1
        assert result["/"]["used_pct"] == 80


class TestCalculateRate:
    """Test rate of change calculation."""

    def test_calculate_rate_from_history(self):
        # Create history: 12 hours ago at 50GB, now at 51GB (within 24h window)
        now = datetime.now()
        history = [
            {
                "timestamp": now - timedelta(hours=12),
                "mount": "/",
                "used_pct": 50.0,
                "used_gb": 50.0,
            },
            {
                "timestamp": now,
                "mount": "/",
                "used_pct": 51.0,
                "used_gb": 51.0,
            },
        ]

        gb_per_day, pct_per_week = calculate_rate(history, "/")

        # 1GB over 12 hours = 2 GB/day
        assert gb_per_day == pytest.approx(2.0, rel=0.1)
        assert pct_per_week == pytest.approx(14.0, rel=0.1)

    def test_calculate_rate_shrinking(self):
        now = datetime.now()
        history = [
            {
                "timestamp": now - timedelta(hours=12),
                "mount": "/",
                "used_pct": 60.0,
                "used_gb": 60.0,
            },
            {
                "timestamp": now,
                "mount": "/",
                "used_pct": 59.0,
                "used_gb": 59.0,
            },
        ]

        gb_per_day, _ = calculate_rate(history, "/")

        # -1GB over 12 hours = -2 GB/day
        assert gb_per_day == pytest.approx(-2.0, rel=0.1)

    def test_calculate_rate_insufficient_history(self):
        history = [{"timestamp": datetime.now(), "mount": "/", "used_pct": 50.0, "used_gb": 50.0}]

        gb_per_day, pct_per_week = calculate_rate(history, "/")

        assert gb_per_day is None
        assert pct_per_week is None


class TestEstimateTimeToFull:
    """Test time to full estimation."""

    def test_estimate_at_current_rate(self):
        usage = {"used_gb": 80.0, "avail_gb": 20.0}
        rate_gb_per_day = 2.0

        ttf = estimate_time_to_full(usage, rate_gb_per_day)

        assert ttf == pytest.approx(10.0, rel=0.01)

    def test_estimate_no_growth(self):
        usage = {"used_gb": 80.0, "avail_gb": 20.0}
        rate_gb_per_day = 0

        ttf = estimate_time_to_full(usage, rate_gb_per_day)

        assert ttf is None

    def test_estimate_shrinking(self):
        usage = {"used_gb": 80.0, "avail_gb": 20.0}
        rate_gb_per_day = -1.0

        ttf = estimate_time_to_full(usage, rate_gb_per_day)

        assert ttf is None


class TestShouldAlert:
    """Test alert threshold logic."""

    def test_alert_on_high_usage(self):
        usage = {"/": {"used_pct": 85, "used_gb": 85, "avail_gb": 15}}
        history = []

        assert should_alert(usage, history) is True

    def test_no_alert_on_normal_usage(self):
        usage = {"/": {"used_pct": 50, "used_gb": 50, "avail_gb": 50}}
        history = []

        assert should_alert(usage, history) is False

    def test_alert_on_high_fill_rate(self):
        # Normal usage but filling fast: 3GB over 12 hours = 6GB/day > 2GB/day threshold
        usage = {"/": {"used_pct": 60, "used_gb": 60, "avail_gb": 40}}
        now = datetime.now()
        history = [
            {
                "timestamp": now - timedelta(hours=12),
                "mount": "/",
                "used_pct": 57.0,
                "used_gb": 57.0,
            },
            {
                "timestamp": now,
                "mount": "/",
                "used_pct": 60.0,
                "used_gb": 60.0,
            },
        ]

        assert should_alert(usage, history) is True

    def test_build_alert_includes_disk_report(self):
        usage = {"/": {"used_pct": 85, "used_gb": 25.5, "avail_gb": 4.5}}
        history = []
        top_paths = ["25G /srv/data", "10G /srv/containerd"]
        disk_report = "=== Filesystem usage ===\nFilesystem..."

        message = build_alert(usage, history, top_paths, disk_report)

        assert "🚨 Picklelab Disk Alert" in message
        assert "⚠️ WARNING /" in message
        assert "25G /srv/data" in message
        assert "Full disk-report:" in message
        assert "=== Filesystem usage ===" in message

    def test_alert_on_time_to_full(self):
        # 10GB free, filling at 3GB over 12h = 6GB/day, ~1.67 days to full < 7 day threshold
        usage = {"/": {"used_pct": 70, "used_gb": 70, "avail_gb": 10}}
        now = datetime.now()
        history = [
            {
                "timestamp": now - timedelta(hours=12),
                "mount": "/",
                "used_pct": 67.0,
                "used_gb": 67.0,
            },
            {
                "timestamp": now,
                "mount": "/",
                "used_pct": 70.0,
                "used_gb": 70.0,
            },
        ]

        assert should_alert(usage, history) is True

    def test_no_alert_on_stable_low_usage(self):
        usage = {"/": {"used_pct": 40, "used_gb": 40, "avail_gb": 60}}
        now = datetime.now()
        history = [
            {
                "timestamp": now - timedelta(hours=24),
                "mount": "/",
                "used_pct": 40.0,
                "used_gb": 40.0,
            },
            {
                "timestamp": now,
                "mount": "/",
                "used_pct": 40.0,
                "used_gb": 40.0,
            },
        ]

        assert should_alert(usage, history) is False

    def test_alert_on_srv_not_root(self):
        # Root is fine, but /srv is at 90%
        usage = {
            "/": {"used_pct": 50, "used_gb": 50, "avail_gb": 50},
            "/srv": {"used_pct": 90, "used_gb": 90, "avail_gb": 10},
        }
        history = []

        assert should_alert(usage, history) is True


FOUR_MOUNTS_DF = """Filesystem                1K-blocks     Used Available Use% Mounted on
/dev/mapper/vg0-root       31457280  8000000  23457280  26% /
/dev/mapper/vg0-srv        73400320 47000000  26400320  65% /srv
/dev/mapper/vg0-containerd 157286400 142000000 15286400  91% /srv/containerd
/dev/mapper/vg0-ci-docker  104857600 20000000  84857600  20% /srv/ci-docker"""


class TestFourMounts:
    """The Docker split adds /srv/containerd and /srv/ci-docker as own mounts."""

    def test_monitors_all_four_mounts(self):
        assert FILESYSTEMS == ["/", "/srv", "/srv/containerd", "/srv/ci-docker"]

    def test_parse_df_handles_four_mounts(self):
        result = parse_df(FOUR_MOUNTS_DF)

        assert set(result) == {"/", "/srv", "/srv/containerd", "/srv/ci-docker"}
        assert result["/srv/containerd"]["used_pct"] == 91

    def test_alert_fires_for_containerd_when_others_are_fine(self):
        usage = parse_df(FOUR_MOUNTS_DF)
        usage["/srv/containerd"]["used_pct"] = 90
        for mount in ("/", "/srv", "/srv/ci-docker"):
            usage[mount]["used_pct"] = 40

        assert should_alert(usage, []) is True

    def test_no_alert_when_all_four_are_fine(self):
        usage = parse_df(FOUR_MOUNTS_DF)
        for data in usage.values():
            data["used_pct"] = 40

        assert should_alert(usage, []) is False


class TestGetDiskUsage:
    """get_disk_usage builds its df from FILESYSTEMS and tolerates missing mounts."""

    def test_df_command_lists_every_monitored_mount(self):
        with patch.object(disk_monitor, "ssh_command", return_value=FOUR_MOUNTS_DF) as ssh:
            disk_monitor.get_disk_usage()

        cmd = ssh.call_args.args[0]
        for mount in FILESYSTEMS:
            assert mount in cmd

    def test_missing_mount_does_not_break_the_run(self):
        # Before the Docker split, df prints only the mounts that exist.
        partial = "\n".join(FOUR_MOUNTS_DF.splitlines()[:3])
        with patch.object(disk_monitor, "ssh_command", return_value=partial):
            usage = disk_monitor.get_disk_usage()

        assert set(usage) == {"/", "/srv"}

    def test_df_exit_status_does_not_fail_the_ssh_call(self):
        # df exits non-zero when a mount is missing; ssh would then report failure.
        with patch.object(disk_monitor, "ssh_command", return_value=FOUR_MOUNTS_DF) as ssh:
            disk_monitor.get_disk_usage()

        assert ssh.call_args.args[0].rstrip().endswith("|| true")

    def test_top_paths_does_not_pin_to_one_filesystem(self):
        with patch.object(disk_monitor, "ssh_command", return_value="1G /srv/data") as ssh:
            disk_monitor.get_top_paths()

        cmd = ssh.call_args.args[0]
        assert "du " in cmd
        assert " -x" not in cmd and "-xh" not in cmd


class TestSshTarget:
    """The ssh user is configuration, not a hardcoded name."""

    def test_no_user_means_bare_host(self):
        assert disk_monitor.ssh_target(None) == disk_monitor.PICKLELAB_HOST

    def test_user_is_prefixed_when_set(self):
        assert disk_monitor.ssh_target("josh") == f"josh@{disk_monitor.PICKLELAB_HOST}"


class TestSshFailureIsLoud:
    """An unreachable picklelab must not look the same as a healthy one."""

    def test_ssh_command_raises_with_stderr_on_failure(self):
        failed = type("R", (), {"returncode": 255, "stdout": "", "stderr": "Permission denied (publickey)."})()
        with patch.object(disk_monitor.subprocess, "run", return_value=failed):
            with pytest.raises(SshError, match="Permission denied"):
                disk_monitor.ssh_command("true")

    def test_main_exits_nonzero_and_prints_an_alert(self, capsys):
        with patch.object(disk_monitor, "ssh_command", side_effect=SshError("Permission denied")):
            code = disk_monitor.main()

        out = capsys.readouterr().out
        assert code == 1
        assert "could not reach picklelab" in out.lower()
        assert "Permission denied" in out

    def test_a_failing_top_paths_lookup_does_not_hide_the_alert(self):
        with patch.object(disk_monitor, "ssh_command", side_effect=SshError("boom")):
            assert disk_monitor.get_top_paths() == []
            assert disk_monitor.get_disk_report() is None


class TestLocalMode:
    """DISK_MONITOR_LOCAL=1 runs commands with bash on this host instead of ssh."""

    def test_runs_command_with_bash_not_ssh(self, monkeypatch):
        monkeypatch.setenv("DISK_MONITOR_LOCAL", "1")
        ok = type("R", (), {"returncode": 0, "stdout": "out\n", "stderr": ""})()
        with patch.object(disk_monitor.subprocess, "run", return_value=ok) as run:
            result = disk_monitor.ssh_command("echo hi")

        assert run.call_args.args[0] == ["bash", "-c", "echo hi"]
        assert result == "out"

    def test_ssh_is_the_default(self, monkeypatch):
        monkeypatch.delenv("DISK_MONITOR_LOCAL", raising=False)
        ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch.object(disk_monitor.subprocess, "run", return_value=ok) as run:
            disk_monitor.ssh_command("true")

        assert run.call_args.args[0][0] == "ssh"

    def test_local_failure_raises_with_stderr(self, monkeypatch):
        monkeypatch.setenv("DISK_MONITOR_LOCAL", "1")
        failed = type("R", (), {"returncode": 3, "stdout": "", "stderr": "no such file"})()
        with patch.object(disk_monitor.subprocess, "run", return_value=failed):
            with pytest.raises(SshError, match=r"failed \(3\): no such file"):
                disk_monitor.ssh_command("false")

    def test_local_timeout_raises(self, monkeypatch):
        monkeypatch.setenv("DISK_MONITOR_LOCAL", "1")
        timeout = disk_monitor.subprocess.TimeoutExpired("bash", 30)
        with patch.object(disk_monitor.subprocess, "run", side_effect=timeout):
            with pytest.raises(SshError, match="timed out after 30"):
                disk_monitor.ssh_command("sleep 99")

    def test_local_run_really_executes_bash(self, monkeypatch):
        monkeypatch.setenv("DISK_MONITOR_LOCAL", "1")

        assert disk_monitor.ssh_command("echo a | tr a b") == "b"

    def test_empty_df_in_local_mode_is_loud(self, monkeypatch, capsys):
        monkeypatch.setenv("DISK_MONITOR_LOCAL", "1")
        with patch.object(disk_monitor, "ssh_command", return_value=""):
            code = disk_monitor.main()

        assert code == 1
        assert "could not reach picklelab" in capsys.readouterr().out.lower()


class TestCsvPath:
    """DISK_MONITOR_CSV places the history file."""

    def test_default_is_under_home_state_dir(self, monkeypatch):
        monkeypatch.delenv("DISK_MONITOR_CSV", raising=False)

        assert disk_monitor.csv_path() == Path.home() / ".local/state/picklehome/disk-monitor.csv"

    def test_env_overrides_the_path(self, monkeypatch, tmp_path):
        target = tmp_path / "state" / "h.csv"
        monkeypatch.setenv("DISK_MONITOR_CSV", str(target))
        usage = {"/": {"used_pct": 50, "used_gb": 5.0, "avail_gb": 5.0}}

        disk_monitor.save_history(usage)
        history = disk_monitor.load_history()

        assert target.exists()
        assert [h["mount"] for h in history] == ["/"]
