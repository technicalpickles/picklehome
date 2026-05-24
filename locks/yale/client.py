import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import aiohttp
from yalexs.api_async import ApiAsync
from yalexs.lock import LockDetail, LockDoorStatus, LockStatus

from locks.yale.auth import DEFAULT_TOKEN_PATH, YALE_BRAND, load_access_token


BridgeConnectivity = Literal["online", "offline"]


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
