from datetime import datetime, timedelta, timezone

from yalexs.lock import LockDoorStatus, LockStatus

from locks.yale.client import BridgeStatus, HealthIssue, YaleLock, _parse_bridge


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


def _make_bridge(
    connectivity: str = "online",
    wifi_issue_at: datetime | None = None,
) -> BridgeStatus:
    return BridgeStatus(
        connectivity=connectivity,
        last_online=None,
        last_offline=None,
        model="august-connect",
        firmware="2.3.1",
        mfg_id="TEST",
        wifi_issue_at=wifi_issue_at,
    )


_UNSET = object()
_NO_DATETIME = object()


def _make_lock(
    *,
    bridge=_UNSET,
    lock_status: LockStatus = LockStatus.LOCKED,
    battery_level: int = 97,
    status_datetime=_NO_DATETIME,
) -> YaleLock:
    if status_datetime is _NO_DATETIME:
        status_datetime = datetime.now(timezone.utc)
    if bridge is _UNSET:
        bridge = _make_bridge()
    return YaleLock(
        lock_id="lock-id",
        name="Test Lock",
        house_id="house-id",
        house_name="Test House",
        lock_status=lock_status,
        door_state=LockDoorStatus.CLOSED,
        doorsense=True,
        battery_level=battery_level,
        status_datetime=status_datetime,
        mac_address="00:00:00:00:00:00",
        firmware_version="1.0.0",
        model="AUG-MDY1",
        serial_number="TEST123",
        bridge=bridge,
    )


def test_healthy_lock_has_no_issues():
    lock = _make_lock()
    assert lock.health_issues == []
    assert lock.health_status == "healthy"


def test_unbridged_lock_returns_only_no_bridge():
    lock = _make_lock(bridge=None)
    assert lock.health_issues == [HealthIssue("critical", "no bridge")]
    assert lock.health_status == "unhealthy"


def test_bridge_offline_returns_only_bridge_offline():
    lock = _make_lock(bridge=_make_bridge(connectivity="offline"))
    assert lock.health_issues == [HealthIssue("critical", "bridge offline")]
    assert lock.health_status == "unhealthy"


def _offline_bridge(last_online: datetime | None) -> BridgeStatus:
    return BridgeStatus(
        connectivity="offline",
        last_online=last_online,
        last_offline=None,
        model="august-connect",
        firmware="2.3.1",
        mfg_id="TEST",
        wifi_issue_at=None,
    )


def test_bridge_offline_with_lock_dying_together_labels_dead_battery():
    # Classic 8 Hacker St pattern: bridge and lock both went dark within
    # ~minutes of each other, 60 days ago.
    sixty_days_ago = datetime.now(timezone.utc) - timedelta(days=60)
    lock = _make_lock(
        bridge=_offline_bridge(last_online=sixty_days_ago),
        status_datetime=sixty_days_ago + timedelta(minutes=10),
    )
    assert lock.health_issues == [
        HealthIssue("critical", "bridge offline (likely dead battery)")
    ]


def test_bridge_offline_with_lock_seen_recently_labels_bridge_down():
    # Phone reached the lock over BLE long after the bridge dropped: the
    # lock is alive, the bridge is the broken party.
    now = datetime.now(timezone.utc)
    lock = _make_lock(
        bridge=_offline_bridge(last_online=now - timedelta(days=30)),
        status_datetime=now - timedelta(minutes=5),
    )
    assert lock.health_issues == [
        HealthIssue("critical", "bridge offline (lock seen recently)")
    ]


def test_bridge_offline_no_bridge_last_online_uses_generic_label():
    lock = _make_lock(
        bridge=_offline_bridge(last_online=None),
        status_datetime=datetime.now(timezone.utc) - timedelta(days=1),
    )
    assert lock.health_issues == [HealthIssue("critical", "bridge offline")]


def test_bridge_offline_no_lock_status_datetime_uses_generic_label():
    lock = _make_lock(
        bridge=_offline_bridge(
            last_online=datetime.now(timezone.utc) - timedelta(days=1)
        ),
        status_datetime=None,
    )
    assert lock.health_issues == [HealthIssue("critical", "bridge offline")]


def test_short_circuit_unbridged_with_low_battery():
    # Even though battery would also fail, we suppress downstream issues.
    lock = _make_lock(bridge=None, battery_level=10)
    assert lock.health_issues == [HealthIssue("critical", "no bridge")]


def test_lock_status_unknown_is_unreachable():
    lock = _make_lock(lock_status=LockStatus.UNKNOWN)
    assert HealthIssue("critical", "lock unreachable") in lock.health_issues
    assert lock.health_status == "unhealthy"


def test_battery_invalid_is_unknown():
    lock = _make_lock(battery_level=-100)
    assert HealthIssue("critical", "battery unknown") in lock.health_issues
    assert lock.health_status == "unhealthy"


def test_battery_24_is_critical():
    lock = _make_lock(battery_level=24)
    assert HealthIssue("critical", "low battery (24%)") in lock.health_issues
    assert lock.health_status == "unhealthy"


def test_battery_25_is_warning():
    lock = _make_lock(battery_level=25)
    assert HealthIssue("warning", "low battery (25%)") in lock.health_issues
    assert lock.health_status == "warning"


def test_battery_39_is_warning():
    lock = _make_lock(battery_level=39)
    assert HealthIssue("warning", "low battery (39%)") in lock.health_issues
    assert lock.health_status == "warning"


def test_battery_40_is_healthy():
    lock = _make_lock(battery_level=40)
    assert lock.health_issues == []
    assert lock.health_status == "healthy"


def test_stale_data_flags_unhealthy():
    seven_hours_ago = datetime.now(timezone.utc) - timedelta(hours=7)
    lock = _make_lock(status_datetime=seven_hours_ago)
    assert HealthIssue("critical", "data stale (7h old)") in lock.health_issues
    assert lock.health_status == "unhealthy"


def test_status_datetime_none_flags_unhealthy():
    lock = _make_lock(status_datetime=None)
    assert HealthIssue("critical", "data stale (unknown)") in lock.health_issues
    assert lock.health_status == "unhealthy"


def test_multiple_issues_critical_wins():
    seven_hours_ago = datetime.now(timezone.utc) - timedelta(hours=7)
    lock = _make_lock(
        lock_status=LockStatus.UNKNOWN,
        battery_level=20,
        status_datetime=seven_hours_ago,
    )
    severities = {i.severity for i in lock.health_issues}
    assert "critical" in severities
    assert lock.health_status == "unhealthy"
    # All three downstream checks should fire (lock, battery, stale)
    assert len(lock.health_issues) == 3
