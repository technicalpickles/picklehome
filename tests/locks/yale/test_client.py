from datetime import datetime, timezone

from locks.yale.client import _parse_bridge


def test_parse_bridge_captures_wifi_issue_timestamp():
    raw = {
        "deviceModel": "august-connect",
        "firmwareVersion": "2.3.1",
        "mfgBridgeID": "C5W3Q00D1A",
        "status": {"current": "online", "lastOnline": None, "lastOffline": None},
        "enhancedStatus": {"WifiModuleConnectionIssue": 1746237052214},
    }
    bridge = _parse_bridge(raw)
    assert bridge is not None
    assert bridge.wifi_issue_at == datetime.fromtimestamp(
        1746237052.214, tz=timezone.utc
    )


def test_parse_bridge_no_wifi_issue():
    raw = {
        "deviceModel": "august-connect",
        "firmwareVersion": "2.3.1",
        "mfgBridgeID": "C5W3Q00D1A",
        "status": {"current": "online", "lastOnline": None, "lastOffline": None},
    }
    bridge = _parse_bridge(raw)
    assert bridge is not None
    assert bridge.wifi_issue_at is None
