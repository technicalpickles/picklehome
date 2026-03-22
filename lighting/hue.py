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


def _device_for(bridge, resource):
    """Find the parent device for a resource (light, sensor, button, etc.)."""
    if resource.owner:
        return next((d for d in bridge.devices if d.id == resource.owner.rid), None)
    return None


def _device_name(bridge, resource) -> str:
    """Get the human-readable name from a resource's parent device."""
    device = _device_for(bridge, resource)
    if device and device.metadata:
        return device.metadata.name
    return resource.id


def _light_name(bridge, light) -> str:
    """Get the human-readable name for a light (lives on parent device)."""
    return _device_name(bridge, light)


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


async def cmd_groups(bridge):
    """List rooms and zones with their lights."""
    section("Hue Groups")

    print("\n  Rooms")
    for room in sorted(bridge.groups.room, key=lambda r: r.metadata.name):
        lights = bridge.groups.room.get_lights(room.id)
        light_names = sorted(_light_name(bridge, l) for l in lights)
        print(f"    {room.metadata.name}")
        for name in light_names:
            print(f"      {name}")

    zones = list(bridge.groups.zone)
    if zones:
        print("\n  Zones")
        for zone in sorted(zones, key=lambda z: z.metadata.name):
            lights = bridge.groups.zone.get_lights(zone.id)
            light_names = sorted(_light_name(bridge, l) for l in lights)
            print(f"    {zone.metadata.name}")
            for name in light_names:
                print(f"      {name}")


async def cmd_sensors(bridge):
    """List motion sensors with status."""
    section("Hue Sensors")

    for motion in sorted(bridge.sensors.motion, key=lambda m: _device_name(bridge, m)):
        name = _device_name(bridge, motion)
        detected = "motion" if motion.motion.motion else "clear"

        # Find the parent device for battery and temperature
        device = _device_for(bridge, motion)

        battery = ""
        if device:
            power = next((s for s in bridge.sensors.device_power if s.owner and s.owner.rid == device.id), None)
            if power and power.power_state:
                battery = f"  battery: {power.power_state.battery_level}%"

        temp = ""
        if device:
            temp_sensor = next((t for t in bridge.sensors.temperature if t.owner and t.owner.rid == device.id), None)
            if temp_sensor and temp_sensor.temperature:
                celsius = temp_sensor.temperature.temperature
                fahrenheit = celsius * 9 / 5 + 32
                temp = f"  temp: {fahrenheit:.0f}°F"

        print(f"  {name:<30} {detected:<8}{battery}{temp}")


async def cmd_buttons(bridge):
    """List tap buttons with last event."""
    section("Hue Buttons")

    for button in sorted(bridge.sensors.button, key=lambda b: _device_name(bridge, b)):
        name = _device_name(bridge, button)
        control_id = button.metadata.control_id if button.metadata else "?"
        last_event = button.button.last_event.value if button.button and button.button.last_event else "—"
        print(f"  {name:<30} button {control_id}  last: {last_event}")


async def cmd_status(bridge):
    """Quick overview — lights, active scenes, recent motion."""
    section("Hue Status")

    # Light summary
    lights = list(bridge.lights)
    on_count = sum(1 for l in lights if l.on.on)
    print(f"  Lights: {on_count}/{len(lights)} on")

    # On lights by room
    if on_count:
        by_room = {}
        for light in lights:
            if light.on.on:
                room = _get_room_for_light(bridge, light)
                by_room.setdefault(room, []).append(light)
        for room in sorted(by_room):
            names = ", ".join(_light_name(bridge, l) for l in by_room[room])
            print(f"    {room}: {names}")

    # Motion sensors
    motions = list(bridge.sensors.motion)
    if motions:
        active = [m for m in motions if m.motion.motion]
        if active:
            names = ", ".join(_device_name(bridge, m) for m in active)
            print(f"  Motion: {names}")
        else:
            print("  Motion: all clear")
