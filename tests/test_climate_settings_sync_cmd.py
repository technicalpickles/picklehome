"""Tests for climate.sync cmd_settings_sync command."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from argparse import Namespace

import pytest
from pyecobee.errors import InvalidTokenError

from climate.sync import cmd_settings_sync


class TestCmdSettingsSync:
    """Tests for the settings-sync command."""

    def test_settings_sync_sets_hold_action_on_managed(self, capsys):
        """Should set holdAction on all managed thermostats when no --thermostat given."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hold_action") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {
                "thermostats": {
                    "downstairs": {"thermostat_id": "down_id", "settings": {"hold_action": "useEndTime4hour"}},
                    "upstairs": {"thermostat_id": "up_id", "settings": {"hold_action": "useEndTime4hour"}},
                }
            }
            mock_managed.return_value = [
                ("downstairs", "down_id"),
                ("upstairs", "up_id"),
            ]

            args = Namespace(dry_run=False, thermostat=None, thermostats=Path("config/thermostats.yaml"))
            cmd_settings_sync(args)

            assert mock_set.call_count == 2
            captured = capsys.readouterr()
            assert "[downstairs] Pushed holdAction=useEndTime4hour" in captured.out
            assert "[upstairs] Pushed holdAction=useEndTime4hour" in captured.out

    def test_settings_sync_dry_run_prevents_write(self, capsys):
        """Should preview what would be set without writing when --dry-run is passed."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hold_action") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {
                "thermostats": {
                    "downstairs": {"thermostat_id": "down_id", "settings": {"hold_action": "useEndTime4hour"}},
                }
            }
            mock_managed.return_value = [("downstairs", "down_id")]

            args = Namespace(dry_run=True, thermostat=None, thermostats=Path("config/thermostats.yaml"))
            cmd_settings_sync(args)

            mock_set.assert_not_called()
            captured = capsys.readouterr()
            assert "[downstairs] Would set holdAction=useEndTime4hour" in captured.out

    def test_settings_sync_skips_thermostat_without_settings(self, capsys):
        """Should skip silently a thermostat with no settings.hold_action key."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hold_action") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {
                "thermostats": {
                    "downstairs": {"thermostat_id": "down_id"},  # No settings
                    "upstairs": {"thermostat_id": "up_id", "settings": {"hold_action": "useEndTime4hour"}},
                }
            }
            mock_managed.return_value = [
                ("downstairs", "down_id"),
                ("upstairs", "up_id"),
            ]

            args = Namespace(dry_run=False, thermostat=None, thermostats=Path("config/thermostats.yaml"))
            cmd_settings_sync(args)

            # Only upstairs should be set
            assert mock_set.call_count == 1
            captured = capsys.readouterr()
            assert "[upstairs] Pushed holdAction=useEndTime4hour" in captured.out
            assert "downstairs" not in captured.out

    def test_settings_sync_scopes_to_single_thermostat(self, capsys):
        """Should set settings only on the named thermostat when --thermostat is given."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hold_action") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {
                "thermostats": {
                    "downstairs": {"thermostat_id": "down_id", "settings": {"hold_action": "useEndTime4hour"}},
                    "upstairs": {"thermostat_id": "up_id", "settings": {"hold_action": "useEndTime4hour"}},
                }
            }
            mock_managed.return_value = [
                ("downstairs", "down_id"),
                ("upstairs", "up_id"),
            ]

            args = Namespace(dry_run=False, thermostat="upstairs", thermostats=Path("config/thermostats.yaml"))
            cmd_settings_sync(args)

            # Only the upstairs set call should succeed
            mock_set.assert_called_once()
            call_args = mock_set.call_args[0]
            assert call_args[1] == "up_id"
            assert call_args[2] == "useEndTime4hour"

    def test_settings_sync_invalid_token_exits_immediately(self, capsys):
        """Should exit immediately with message if tokens are invalid (global failure)."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hold_action") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {
                "thermostats": {
                    "downstairs": {"thermostat_id": "down_id", "settings": {"hold_action": "useEndTime4hour"}},
                }
            }
            mock_managed.return_value = [("downstairs", "down_id")]
            mock_set.side_effect = InvalidTokenError("expired")

            args = Namespace(dry_run=False, thermostat=None, thermostats=Path("config/thermostats.yaml"))

            with pytest.raises(SystemExit) as exc_info:
                cmd_settings_sync(args)

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "Tokens invalid" in captured.out
            assert "just climate-auth" in captured.out

    def test_settings_sync_runtime_error_continues_to_next(self, capsys):
        """Should report error for one thermostat but continue to the next (per-thermostat failure)."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed, \
             patch("climate.sync.schedule.set_hold_action") as mock_set:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {
                "thermostats": {
                    "downstairs": {"thermostat_id": "down_id", "settings": {"hold_action": "useEndTime4hour"}},
                    "upstairs": {"thermostat_id": "up_id", "settings": {"hold_action": "useEndTime4hour"}},
                }
            }
            mock_managed.return_value = [
                ("downstairs", "down_id"),
                ("upstairs", "up_id"),
            ]
            # First thermostat fails, second succeeds
            mock_set.side_effect = [RuntimeError("Device unreachable"), None]

            args = Namespace(dry_run=False, thermostat=None, thermostats=Path("config/thermostats.yaml"))

            with pytest.raises(SystemExit) as exc_info:
                cmd_settings_sync(args)

            assert exc_info.value.code == 1
            assert mock_set.call_count == 2  # Both were attempted
            captured = capsys.readouterr()
            assert "[downstairs] Error: Device unreachable" in captured.out
            assert "[upstairs] Pushed holdAction=useEndTime4hour" in captured.out

    def test_settings_sync_exits_if_no_thermostat_found(self, capsys):
        """Should exit with error message if requested thermostat not found."""
        with patch("climate.sync.auth.make_ecobee") as mock_ecobee, \
             patch("climate.sync.load_thermostats") as mock_load, \
             patch("climate.sync.get_managed_thermostats") as mock_managed:

            mock_ecobee.return_value = MagicMock()
            mock_load.return_value = {"thermostats": {}}
            mock_managed.return_value = [("downstairs", "down_id")]

            args = Namespace(dry_run=False, thermostat="NonExistent", thermostats=Path("config/thermostats.yaml"))

            with pytest.raises(SystemExit) as exc_info:
                cmd_settings_sync(args)

            assert exc_info.value.code == 1
            captured = capsys.readouterr()
            assert "No managed thermostat named 'NonExistent'" in captured.out
