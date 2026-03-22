"""Philips Hue bridge connection and commands."""

import os
import ssl
import sys

import aiohttp
from aiohue import HueBridgeV2
from aiohue.util import create_app_key
from dotenv import load_dotenv

from lighting import section

load_dotenv()


async def connect() -> HueBridgeV2:
    """Connect to the Hue bridge, return a HueBridgeV2 instance."""
    bridge_ip = os.environ.get("HUE_BRIDGE_IP")
    app_key = os.environ.get("HUE_API_KEY")

    missing = [
        name for name, val in [("HUE_BRIDGE_IP", bridge_ip), ("HUE_API_KEY", app_key)]
        if not val
    ]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}\nRun: just dotenv")

    bridge = HueBridgeV2(bridge_ip, app_key)
    await bridge.initialize()
    return bridge


async def cmd_pair(host: str | None = None):
    """Pair with the Hue bridge — press the button first, then run this."""
    if not host:
        host = os.environ.get("HUE_BRIDGE_IP")
    if not host:
        sys.exit("Pass bridge IP as argument or set HUE_BRIDGE_IP")

    print(f"Pairing with Hue bridge at {host}...")
    print("Make sure you've pressed the link button on the bridge.")
    print()

    # aiohue's create_app_key needs an aiohttp session;
    # Hue bridge uses a self-signed cert, so disable SSL verification
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(connector=connector) as session:
        app_key = await create_app_key(host, "picklehome#cli", websession=session)

    print(f"Success! App key: {app_key}")
    print()
    print("Save this in 1Password:")
    print(f'  Item: "Philips Hue" in picklehome vault')
    print(f"  Field: api_key = {app_key}")
    print(f"  Field: bridge_ip = {host}")
    print()
    print("Then run: just dotenv")
