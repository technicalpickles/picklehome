import sys
from dataclasses import dataclass

import aiohttp

from garage.aladdin.auth import load_tokens, API_URL, DEFAULT_TOKEN_PATH


@dataclass
class GarageDoor:
    device_id: str
    door_index: int
    name: str
    status: str
    link_status: str
    battery_level: int
    fault: str
    ble_strength: int
    is_enabled: bool
    updated_at: str
    # Device-level fields
    rssi: int
    device_status: str
    software_version: str
    model: str


# Map numeric status codes to human-readable strings
DOOR_STATUS = {
    0: "unknown",
    1: "open",
    2: "opening",
    3: "timeout_opening",
    4: "closed",
    5: "closing",
    6: "timeout_closing",
    7: "not_configured",
}

LINK_STATUS = {
    0: "unknown",
    1: "not_configured",
    2: "paired",
    3: "connected",
}

DEVICE_STATUS = {
    0: "offline",
    1: "connected",
}

FAULT_STATUS = {
    0: "none",
    1: "ul_lockout",
    2: "interlock",
    3: "not_safe",
    4: "will_not_move",
}


async def connect() -> tuple[aiohttp.ClientSession, str]:
    """Create an authenticated session for the Aladdin API.

    Returns the session (caller must close) and the access token.
    """
    tokens = load_tokens()
    if not tokens or not tokens.get("access_token"):
        print("Aladdin tokens not found. Run 'just garage auth' to authenticate.")
        sys.exit(1)

    session = aiohttp.ClientSession(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        trust_env=True,
    )
    return session, tokens["access_token"]


async def get_doors(session: aiohttp.ClientSession) -> list[GarageDoor]:
    """Fetch all garage doors."""
    async with session.get("/devices") as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)

    doors = []
    for device in data.get("devices", []):
        device_id = device["id"]
        for door in device.get("doors", []):
            doors.append(GarageDoor(
                device_id=device_id,
                door_index=door["door_index"],
                name=door.get("name", device.get("name", "Unknown")),
                status=DOOR_STATUS.get(door.get("status", 0), "unknown"),
                link_status=LINK_STATUS.get(door.get("link_status", 0), "unknown"),
                battery_level=door.get("battery_level", 0),
                fault=FAULT_STATUS.get(door.get("fault", 0), "unknown"),
                ble_strength=door.get("ble_strength", 0),
                is_enabled=door.get("is_enabled", False),
                updated_at=door.get("updated_at", ""),
                rssi=device.get("rssi", 0),
                device_status=DEVICE_STATUS.get(device.get("status", 0), "unknown"),
                software_version=device.get("software_version", ""),
                model=device.get("vendor", ""),
            ))
    return doors


async def open_door(session: aiohttp.ClientSession, device_id: str, door_index: int) -> bool:
    """Open a door. Returns True on success."""
    async with session.post(
        f"/command/devices/{device_id}/doors/{door_index}",
        json={"command": "OPEN_DOOR"},
    ) as resp:
        return resp.status <= 299


async def close_door(session: aiohttp.ClientSession, device_id: str, door_index: int) -> bool:
    """Close a door. Returns True on success."""
    async with session.post(
        f"/command/devices/{device_id}/doors/{door_index}",
        json={"command": "CLOSE_DOOR"},
    ) as resp:
        return resp.status <= 299
