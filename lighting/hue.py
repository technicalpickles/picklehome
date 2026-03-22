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


def _get_room_for_light(bridge, light) -> str:
    """Find the room name for a light by walking device → room."""
    # light.owner is the device
    if light.owner:
        for room in bridge.groups.room:
            for child in room.children:
                if child.rid == light.owner.rid:
                    return room.metadata.name
    return "Other"


def _light_state_str(light) -> str:
    """Human-readable state for a light."""
    if not light.on.on:
        return "off"
    bri = light.dimming.brightness if light.dimming else None
    ct = light.color_temperature.mirek if (light.color_temperature and light.color_temperature.mirek) else None

    parts = ["on"]
    if bri is not None:
        parts.append(f"{bri:.0f}%")
    if ct is not None:
        # Convert mirek to kelvin (mirek = 1,000,000 / kelvin)
        kelvin = round(1_000_000 / ct)
        parts.append(f"{kelvin}K")
    return "  ".join(parts)


def _find_light(bridge, query):
    """Find a light by name substring or ID. Returns the light resource."""
    q = query.lower()

    # Exact ID match
    for light in bridge.lights:
        if light.id == q:
            return light

    # Fuzzy name match
    matches = []
    for light in bridge.lights:
        name = _light_name(bridge, light)
        if q in name.lower():
            matches.append(light)

    if not matches:
        sys.exit(f"No light matching '{query}'")
    if len(matches) > 1:
        print(f"  Multiple lights match '{query}':")
        for light in matches:
            print(f"    {_light_name(bridge, light)}")
        sys.exit("Be more specific")
    return matches[0]


def _light_name(bridge, light) -> str:
    """Get the human-readable name for a light."""
    return light.metadata.name if light.metadata else light.id


async def cmd_lights(bridge):
    """List all lights grouped by room."""
    section("Hue Lights")

    by_room = {}
    for light in bridge.lights:
        room = _get_room_for_light(bridge, light)
        by_room.setdefault(room, []).append(light)

    for room in sorted(by_room):
        print(f"\n  {room}")
        for light in sorted(by_room[room], key=lambda l: _light_name(bridge, l)):
            name = _light_name(bridge, light)
            state = _light_state_str(light)
            print(f"    {name:<30} {state}")


async def cmd_on(bridge, query):
    """Turn on a light."""
    light = _find_light(bridge, query)
    await bridge.lights.turn_on(light.id)
    print(f"  Turned on: {_light_name(bridge, light)}")


async def cmd_off(bridge, query):
    """Turn off a light."""
    light = _find_light(bridge, query)
    await bridge.lights.turn_off(light.id)
    print(f"  Turned off: {_light_name(bridge, light)}")


async def cmd_set(bridge, query, brightness):
    """Set light brightness (0-100)."""
    light = _find_light(bridge, query)
    try:
        level = int(brightness)
    except ValueError:
        sys.exit(f"Invalid brightness: {brightness} (expected 0-100)")
    if not 0 <= level <= 100:
        sys.exit(f"Brightness must be 0-100, got {level}")

    await bridge.lights.set_brightness(light.id, level)
    print(f"  Set {_light_name(bridge, light)} to {level}%")


async def cmd_scenes(bridge):
    """List all scenes grouped by room."""
    section("Hue Scenes")

    by_room = {}
    for scene in bridge.scenes:
        group = bridge.scenes.get_group(scene.id)
        room_name = group.metadata.name if group else "Other"
        by_room.setdefault(room_name, []).append(scene)

    for room in sorted(by_room):
        print(f"\n  {room}")
        for scene in sorted(by_room[room], key=lambda s: s.metadata.name):
            print(f"    {scene.metadata.name}")


async def cmd_scene(bridge, query):
    """Activate a scene by name (partial match)."""
    q = query.lower()
    matches = [s for s in bridge.scenes if q in s.metadata.name.lower()]

    if not matches:
        sys.exit(f"No scene matching '{query}'")
    if len(matches) > 1:
        print(f"  Multiple scenes match '{query}':")
        for s in matches:
            group = bridge.scenes.get_group(s.id)
            room = group.metadata.name if group else "?"
            print(f"    {s.metadata.name} ({room})")
        sys.exit("Be more specific")

    scene = matches[0]
    await bridge.scenes.recall(scene.id)
    group = bridge.scenes.get_group(scene.id)
    room = group.metadata.name if group else "?"
    print(f"  Activated: {scene.metadata.name} ({room})")
