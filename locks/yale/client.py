import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import aiohttp
from yalexs.api_async import ApiAsync
from yalexs.lock import LockDetail, LockDoorStatus, LockStatus

from locks.yale.auth import DEFAULT_TOKEN_PATH, YALE_BRAND, load_access_token


BridgeConnectivity = Literal["online", "offline"]

HEALTH_BATTERY_WARNING  = 40
HEALTH_BATTERY_CRITICAL = 25
HEALTH_MAX_DATA_AGE     = timedelta(hours=6)

# When a bridge goes offline within this window of its lock's last update,
# the failure pattern matches "dead lock dragged the bridge offline": a
# bridge with a dead paired lock reports as offline because it cannot keep
# the BLE link alive. Empirically the two timestamps land within minutes of
# each other in that mode.
HEALTH_BRIDGE_LOCK_COINCIDENCE = timedelta(hours=1)

HealthSeverity = Literal["warning", "critical"]
HealthStatus = Literal["healthy", "warning", "unhealthy"]
BridgeOfflineReason = Literal["bridge_down", "battery_likely", "unknown"]


@dataclass
class HealthIssue:
    severity: HealthSeverity
    message: str


@dataclass
class BridgeStatus:
    """State of an August Connect bridge. None elsewhere = lock is unbridged."""
    connectivity: BridgeConnectivity
    last_online: datetime | None
    last_offline: datetime | None
    model: str | None
    firmware: str | None
    mfg_id: str | None
    wifi_issue_at: datetime | None


@dataclass
class YaleLock:
    lock_id: str
    name: str
    house_id: str
    house_name: str
    lock_status: LockStatus
    door_state: LockDoorStatus
    doorsense: bool
    battery_level: int
    status_datetime: datetime | None
    mac_address: str | None
    firmware_version: str
    model: str | None
    serial_number: str
    bridge: BridgeStatus | None  # None means no bridge attached at all

    @property
    def is_stale(self) -> bool:
        """Lock data is stale whenever we have no live path to the device."""
        return self.bridge is None or self.bridge.connectivity != "online"

    @property
    def battery_valid(self) -> bool:
        return 0 <= self.battery_level <= 100

    @property
    def is_wedged(self) -> bool:
        """Online bridge, but the lock's firmware hung and stopped answering BLE.

        The tell is blank identity on an otherwise-online bridge: the lock
        firmware reads as ``0.0.0`` (never read) and the battery is the ``-1``
        "no reading" sentinel. A dead battery keeps its cached identity, so this
        is distinct -- the fix is a power-cycle of the lock, not new batteries.
        See locks/README.md findings.
        """
        return (
            self.bridge is not None
            and self.bridge.connectivity == "online"
            and self.firmware_version.startswith("0.0.0")
            and not self.battery_valid
        )

    @property
    def health_issues(self) -> list[HealthIssue]:
        if self.bridge is None:
            return [HealthIssue("critical", "no bridge")]
        if self.bridge.connectivity != "online":
            return [HealthIssue("critical", _bridge_offline_label(
                self.bridge, self.status_datetime
            ))]
        if self.is_wedged:
            return [HealthIssue("critical", "lock wedged (power-cycle)")]

        issues: list[HealthIssue] = []

        if self.lock_status not in (LockStatus.LOCKED, LockStatus.UNLOCKED):
            issues.append(HealthIssue("critical", "lock unreachable"))

        if not self.battery_valid:
            issues.append(HealthIssue("critical", "battery unknown"))
        elif self.battery_level < HEALTH_BATTERY_CRITICAL:
            issues.append(HealthIssue("critical", f"low battery ({self.battery_level}%)"))
        elif self.battery_level < HEALTH_BATTERY_WARNING:
            issues.append(HealthIssue("warning", f"low battery ({self.battery_level}%)"))

        if self.status_datetime is None:
            issues.append(HealthIssue("critical", "data stale (unknown)"))
        else:
            age = datetime.now(timezone.utc) - self.status_datetime
            if age > HEALTH_MAX_DATA_AGE:
                hours = int(age.total_seconds() // 3600)
                issues.append(HealthIssue("critical", f"data stale ({hours}h old)"))

        return issues

    @property
    def health_status(self) -> HealthStatus:
        issues = self.health_issues
        if not issues:
            return "healthy"
        if any(i.severity == "critical" for i in issues):
            return "unhealthy"
        return "warning"

    @property
    def bridge_offline_reason(self) -> BridgeOfflineReason | None:
        """Why is the bridge offline? None if it isn't (online / no bridge)."""
        if self.bridge is None or self.bridge.connectivity == "online":
            return None
        return _bridge_offline_reason(self.bridge, self.status_datetime)


_BRIDGE_OFFLINE_LABELS: dict[BridgeOfflineReason, str] = {
    "bridge_down":     "bridge offline (lock seen recently)",
    "battery_likely":  "bridge offline (likely dead battery)",
    "unknown":         "bridge offline",
}


def _bridge_offline_reason(
    bridge: BridgeStatus, lock_status_dt: datetime | None
) -> BridgeOfflineReason:
    # Disambiguate the overloaded "offline" state: a dead lock and a dead
    # bridge both surface as bridge.connectivity == "offline", but the
    # remediation is different (replace AAs vs. power-cycle the bridge).
    if bridge.last_online is None or lock_status_dt is None:
        return "unknown"
    delta = abs(bridge.last_online - lock_status_dt)
    if delta <= HEALTH_BRIDGE_LOCK_COINCIDENCE:
        return "battery_likely"
    if lock_status_dt > bridge.last_online:
        return "bridge_down"
    return "unknown"


def _bridge_offline_label(
    bridge: BridgeStatus, lock_status_dt: datetime | None
) -> str:
    return _BRIDGE_OFFLINE_LABELS[_bridge_offline_reason(bridge, lock_status_dt)]


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    # August returns "2026-04-04T20:48:36.283Z"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _parse_bridge(raw_bridge: dict | None) -> BridgeStatus | None:
    if not raw_bridge:
        return None
    status = raw_bridge.get("status") or {}
    current = status.get("current")
    # Treat any non-"online" value as offline -- the API has been observed to
    # return only "online" or "offline", but be permissive about unknowns.
    connectivity: BridgeConnectivity = "online" if current == "online" else "offline"

    enhanced = raw_bridge.get("enhancedStatus") or {}
    wifi_issue_ms = enhanced.get("WifiModuleConnectionIssue")
    wifi_issue_at = (
        datetime.fromtimestamp(wifi_issue_ms / 1000, tz=timezone.utc)
        if wifi_issue_ms else None
    )

    return BridgeStatus(
        connectivity=connectivity,
        last_online=_parse_iso(status.get("lastOnline")),
        last_offline=_parse_iso(status.get("lastOffline")),
        model=raw_bridge.get("deviceModel"),
        firmware=raw_bridge.get("firmwareVersion"),
        mfg_id=raw_bridge.get("mfgBridgeID"),
        wifi_issue_at=wifi_issue_at,
    )


def _build_lock(detail: LockDetail) -> YaleLock:
    raw = detail.raw
    return YaleLock(
        lock_id=detail.device_id,
        name=detail.device_name,
        house_id=raw.get("HouseID", ""),
        house_name=raw.get("HouseName", "(unknown home)"),
        lock_status=detail.lock_status,
        door_state=detail.door_state,
        doorsense=detail.doorsense,
        battery_level=detail.battery_level,
        status_datetime=detail.lock_status_datetime,
        mac_address=detail.mac_address,
        firmware_version=detail.firmware_version,
        model=detail.model,
        serial_number=detail.serial_number,
        bridge=_parse_bridge(raw.get("Bridge")),
    )


async def get_locks() -> list[YaleLock]:
    """Fetch all Yale locks and their details across every home on the account."""
    access_token = load_access_token(DEFAULT_TOKEN_PATH)
    if not access_token:
        print("Yale tokens not found. Run 'just locks auth' to authenticate.")
        sys.exit(1)

    async with aiohttp.ClientSession(trust_env=True) as session:
        api = ApiAsync(session, brand=YALE_BRAND)
        locks = await api.async_get_locks(access_token)

        details: list[YaleLock] = []
        for lock in locks:
            detail = await api.async_get_lock_detail(access_token, lock.device_id)
            details.append(_build_lock(detail))

    return details
