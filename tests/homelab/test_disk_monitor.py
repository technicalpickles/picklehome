"""Unit tests for disk monitor utility."""

import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from homelab.services.disk_monitor.disk_monitor import (
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
