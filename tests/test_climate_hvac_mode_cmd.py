"""Tests for climate.sync cmd_hvac_mode command."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace

import pytest
from pyecobee.errors import InvalidTokenError

from climate.sync import cmd_hvac_mode


class TestCmdHvacMode:
    """Tests for the hvac-mode command."""

    def test_hvac_mode_sets_all_managed_thermostats(self, capsys):
        """Should set HVAC mode on all managed thermostats when no --thermostat given."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hvac_mode") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {"thermostats": {}}
            mock_managed.return_value = [
                ("Downstairs", "downstairs_id"),
                ("Upstairs", "upstairs_id"),
            ]

            args = Namespace(mode="cool", dry_run=False, thermostat=None, thermostats=Path("config/thermostats.yaml"))
            cmd_hvac_mode(args)

            assert mock_set.call_count == 2
            captured = capsys.readouterr()
            assert "[Downstairs] HVAC mode set to cool" in captured.out
            assert "[Upstairs] HVAC mode set to cool" in captured.out

    def test_hvac_mode_dry_run_prevents_write(self, capsys):
        """Should preview what would be set without writing when --dry-run is passed."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hvac_mode") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {"thermostats": {}}
            mock_managed.return_value = [("Downstairs", "downstairs_id")]

            args = Namespace(mode="off", dry_run=True, thermostat=None, thermostats=Path("config/thermostats.yaml"))
            cmd_hvac_mode(args)

            mock_set.assert_not_called()
            captured = capsys.readouterr()
            assert "Would set HVAC mode to off" in captured.out

    def test_hvac_mode_scopes_to_single_thermostat(self, capsys):
        """Should set HVAC mode only on the named thermostat when --thermostat is given."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hvac_mode") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {"thermostats": {}}
            mock_managed.return_value = [
                ("Downstairs", "downstairs_id"),
                ("Upstairs", "upstairs_id"),
            ]

            args = Namespace(mode="heat", dry_run=False, thermostat="Upstairs", thermostats=Path("config/thermostats.yaml"))
            cmd_hvac_mode(args)

            mock_set.assert_called_once()
            call_args = mock_set.call_args[0]
            assert call_args[1] == "upstairs_id"
            assert call_args[2] == "heat"

    def test_hvac_mode_invalid_token_exits_immediately(self, capsys):
        """Should exit immediately with message if tokens are invalid (global failure)."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hvac_mode") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {"thermostats": {}}
            mock_managed.return_value = [("Downstairs", "downstairs_id")]
            mock_set.side_effect = InvalidTokenError("expired")

            args = Namespace(mode="auto", dry_run=False, thermostat=None, thermostats=Path("config/thermostats.yaml"))

            with pytest.raises(SystemExit) as exc_info:
                cmd_hvac_mode(args)

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Tokens invalid" in captured.out
            assert "just climate-auth" in captured.out

    def test_hvac_mode_runtime_error_continues_to_next(self, capsys):
        """Should report error for one thermostat but continue to the next (per-thermostat failure)."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hvac_mode") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {"thermostats": {}}
            mock_managed.return_value = [
                ("Downstairs", "downstairs_id"),
                ("Upstairs", "upstairs_id"),
            ]
            # First thermostat fails, second succeeds
            mock_set.side_effect = [RuntimeError("Device unreachable"), None]

            args = Namespace(mode="heat", dry_run=False, thermostat=None, thermostats=Path("config/thermostats.yaml"))

            with pytest.raises(SystemExit) as exc_info:
                cmd_hvac_mode(args)

            assert exc_info.value.code == 1
            assert mock_set.call_count == 2  # Both were attempted
            captured = capsys.readouterr()
            assert "[Downstairs] Error: Device unreachable" in captured.out
            assert "[Upstairs] HVAC mode set to heat" in captured.out

    def test_hvac_mode_exits_if_no_thermostat_found(self, capsys):
        """Should exit with error message if requested thermostat not found."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {"thermostats": {}}
            mock_managed.return_value = [("Downstairs", "downstairs_id")]

            args = Namespace(mode="cool", dry_run=False, thermostat="NonExistent", thermostats=Path("config/thermostats.yaml"))

            with pytest.raises(SystemExit) as exc_info:
                cmd_hvac_mode(args)

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "No managed thermostat named 'NonExistent'" in captured.out
