"""Tests for climate.ecobee.schedule endpoint functions (set_hold_action, etc.)."""
from unittest.mock import MagicMock, patch

import pytest

from climate.ecobee.schedule import set_hold_action


class TestSetHoldAction:
    """Tests for set_hold_action endpoint."""

    def test_set_hold_action_sends_correct_request(self):
        """Should send a POST request with holdAction in the thermostat settings."""
        mock_ecobee = MagicMock()
        mock_ecobee._request_with_refresh.return_value = {"status": {"code": 0}}

        set_hold_action(mock_ecobee, "thermostat_123", "useEndTime4hour")

        mock_ecobee._request_with_refresh.assert_called_once()
        call_args = mock_ecobee._request_with_refresh.call_args
        assert call_args[0][0] == "POST"  # method
        assert "set holdAction" in call_args[0][2]  # action message

        body = call_args[1]["body"]
        assert body["selection"]["selectionType"] == "thermostats"
        assert body["selection"]["selectionMatch"] == "thermostat_123"
        assert body["thermostat"]["settings"]["holdAction"] == "useEndTime4hour"

    def test_set_hold_action_raises_on_null_response(self):
        """Should raise RuntimeError if the request returns None (failed)."""
        mock_ecobee = MagicMock()
        mock_ecobee._request_with_refresh.return_value = None

        with pytest.raises(RuntimeError, match="Failed to set holdAction"):
            set_hold_action(mock_ecobee, "thermostat_123", "useEndTime4hour")

    def test_set_hold_action_accepts_different_values(self):
        """Should work with different holdAction values (only caller validates correctness)."""
        mock_ecobee = MagicMock()
        mock_ecobee._request_with_refresh.return_value = {"status": {"code": 0}}

        for value in ["useEndTime2hour", "nextPeriod", "indefinite"]:
            set_hold_action(mock_ecobee, "thermostat_123", value)
            body = mock_ecobee._request_with_refresh.call_args[1]["body"]
            assert body["thermostat"]["settings"]["holdAction"] == value
