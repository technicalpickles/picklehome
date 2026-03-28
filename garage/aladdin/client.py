import sys

import aiohttp
from genie_partner_sdk.client import AladdinConnectClient
from genie_partner_sdk.model import GarageDoor

from garage.aladdin.auth import AladdinAuth, load_tokens, DEFAULT_TOKEN_PATH


async def connect() -> tuple[aiohttp.ClientSession, AladdinConnectClient]:
    """Create an authenticated Aladdin Connect client.

    Returns the session (caller must close) and the client.
    """
    tokens = load_tokens()
    if not tokens or not tokens.get("access_token"):
        print("Aladdin tokens not found. Run 'just garage auth' to authenticate.")
        sys.exit(1)

    session = aiohttp.ClientSession(trust_env=True)
    auth = AladdinAuth(
        session,
        tokens["access_token"],
        tokens["refresh_token"],
        DEFAULT_TOKEN_PATH,
    )
    client = AladdinConnectClient(auth)
    return session, client


async def get_doors(client: AladdinConnectClient) -> list[GarageDoor]:
    """Fetch all garage doors."""
    return await client.get_doors()


async def open_door(client: AladdinConnectClient, device_id: str, door_number: int) -> bool:
    """Open a door. Returns True on success."""
    return await client.open_door(device_id, door_number)


async def close_door(client: AladdinConnectClient, device_id: str, door_number: int) -> bool:
    """Close a door. Returns True on success."""
    return await client.close_door(device_id, door_number)
