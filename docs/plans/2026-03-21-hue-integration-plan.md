# Hue Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Philips Hue control to the `lighting/` module — pairing, lights, scenes, groups, sensors, buttons — matching the Lutron Caseta CLI pattern.

**Architecture:** `aiohue` (async, Hue v2 API) connects to the bridge via HTTPS with an API key. `hue.py` holds bridge connection + device commands; `hue_cli.py` is the CLI entrypoint dispatching subcommands. Secrets flow through 1Password → `.env.template` → `.env`.

**Tech Stack:** Python 3.12, aiohue, aiohttp, argparse, 1Password CLI

---

### Task 1: Add dependency and env template

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.template`

**Step 1: Add aiohue to pyproject.toml**

In `pyproject.toml`, add `"aiohue>=4.7"` to the `dependencies` list under the `# lighting` comment:

```python
    # lighting
    "pylutron-caseta>=0.21",
    "aiohue>=4.7",
```

**Step 2: Add Hue env vars to .env.template**

Append to `.env.template` after the Lutron section:

```
# Philips Hue (1Password item: Philips Hue)
HUE_BRIDGE_IP={{ op://picklehome/Philips Hue/bridge_ip }}
HUE_API_KEY={{ op://picklehome/Philips Hue/api_key }}
```

**Step 3: Install the new dependency**

Run: `uv sync`

**Step 4: Commit**

```bash
git add pyproject.toml .env.template uv.lock
git commit -m "feat(lighting): add aiohue dependency and Hue env template"
```

---

### Task 2: Bridge connection and pairing

**Files:**
- Create: `lighting/hue.py`

**Step 1: Create hue.py with bridge connection and pair command**

`lighting/hue.py` — bridge connection helper and pair command:

```python
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
```

Note: `aiohue.util.create_app_key` handles the POST to `/api` with `devicetype`. The self-signed SSL context is required because the Hue bridge uses a self-signed certificate for its HTTPS API.

**Step 2: Commit**

```bash
git add lighting/hue.py
git commit -m "feat(lighting): add Hue bridge connection and pairing"
```

---

### Task 3: CLI entrypoint with pair command

**Files:**
- Create: `lighting/hue_cli.py`
- Modify: `Justfile`

**Step 1: Create hue_cli.py**

`lighting/hue_cli.py`:

```python
#!/usr/bin/env python3
"""
hue_cli.py — Philips Hue CLI

Usage:
    uv run lighting/hue_cli.py pair [<host>]      # one-time bridge pairing
    uv run lighting/hue_cli.py lights              # list all lights with state
    uv run lighting/hue_cli.py sensors             # motion sensors with status
    uv run lighting/hue_cli.py buttons             # tap buttons with last event
    uv run lighting/hue_cli.py scenes              # scenes by room
    uv run lighting/hue_cli.py groups              # rooms/zones with members
    uv run lighting/hue_cli.py on <light>          # turn on (partial match)
    uv run lighting/hue_cli.py off <light>         # turn off
    uv run lighting/hue_cli.py set <light> <bri>   # brightness 0-100%
    uv run lighting/hue_cli.py scene <scene>       # activate a scene
    uv run lighting/hue_cli.py status              # overview
"""

import argparse
import asyncio

from lighting.hue import cmd_pair


async def run(args):
    if args.command == "pair":
        await cmd_pair(args.host)
        return

    # All other commands need a connected bridge
    from lighting.hue import connect
    bridge = await connect()
    try:
        from lighting import hue as hue_cmds
        if args.command == "lights":
            await hue_cmds.cmd_lights(bridge)
        elif args.command == "sensors":
            await hue_cmds.cmd_sensors(bridge)
        elif args.command == "buttons":
            await hue_cmds.cmd_buttons(bridge)
        elif args.command == "scenes":
            await hue_cmds.cmd_scenes(bridge)
        elif args.command == "groups":
            await hue_cmds.cmd_groups(bridge)
        elif args.command == "on":
            await hue_cmds.cmd_on(bridge, args.light)
        elif args.command == "off":
            await hue_cmds.cmd_off(bridge, args.light)
        elif args.command == "set":
            await hue_cmds.cmd_set(bridge, args.light, args.brightness)
        elif args.command == "scene":
            await hue_cmds.cmd_scene(bridge, args.scene)
        elif args.command == "status":
            await hue_cmds.cmd_status(bridge)
    finally:
        await bridge.close()


def main():
    parser = argparse.ArgumentParser(description="Philips Hue CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_pair = sub.add_parser("pair", help="One-time bridge pairing")
    p_pair.add_argument("host", nargs="?", help="Bridge IP (or use HUE_BRIDGE_IP)")

    sub.add_parser("lights", help="List all lights with state")
    sub.add_parser("sensors", help="List motion sensors with status")
    sub.add_parser("buttons", help="List tap buttons with last event")
    sub.add_parser("scenes", help="List scenes by room")
    sub.add_parser("groups", help="List rooms/zones with members")
    sub.add_parser("status", help="Overview: lights, scenes, motion")

    p_on = sub.add_parser("on", help="Turn on a light")
    p_on.add_argument("light", help="Light name (partial match) or ID")

    p_off = sub.add_parser("off", help="Turn off a light")
    p_off.add_argument("light", help="Light name (partial match) or ID")

    p_set = sub.add_parser("set", help="Set brightness (0-100)")
    p_set.add_argument("light", help="Light name (partial match) or ID")
    p_set.add_argument("brightness", help="0-100")

    p_scene = sub.add_parser("scene", help="Activate a scene")
    p_scene.add_argument("scene", help="Scene name (partial match)")

    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
```

**Step 2: Add `just hue` to Justfile**

Append after the `lutron` task:

```just
# Philips Hue lighting: just hue lights | sensors | buttons | scenes | groups | on <light> | off <light> | set <light> <bri> | scene <scene> | status | pair [<host>]
hue *ARGS:
    uv run lighting/hue_cli.py {{ARGS}}
```

**Step 3: Commit**

```bash
git add lighting/hue_cli.py Justfile
git commit -m "feat(lighting): add Hue CLI entrypoint and Justfile task"
```

---

### Task 4: Light listing and room helpers

**Files:**
- Modify: `lighting/hue.py`

**Step 1: Add room lookup helper and lights command**

The Hue v2 API links lights to rooms via the device hierarchy: light → device → room. Add these to `hue.py`:

```python
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

    # Fuzzy name match — light name comes from its owner device metadata
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
```

**Step 2: Commit**

```bash
git add lighting/hue.py
git commit -m "feat(lighting): add Hue light listing with room grouping"
```

---

### Task 5: Light control commands (on/off/set)

**Files:**
- Modify: `lighting/hue.py`

**Step 1: Add on, off, set commands**

```python
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
```

**Step 2: Commit**

```bash
git add lighting/hue.py
git commit -m "feat(lighting): add Hue light on/off/set commands"
```

---

### Task 6: Scenes command and activation

**Files:**
- Modify: `lighting/hue.py`

**Step 1: Add scenes listing and activation**

```python
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
```

**Step 2: Commit**

```bash
git add lighting/hue.py
git commit -m "feat(lighting): add Hue scene listing and activation"
```

---

### Task 7: Groups command

**Files:**
- Modify: `lighting/hue.py`

**Step 1: Add groups listing**

```python
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
```

**Step 2: Commit**

```bash
git add lighting/hue.py
git commit -m "feat(lighting): add Hue groups listing"
```

---

### Task 8: Sensors and buttons commands

**Files:**
- Modify: `lighting/hue.py`

**Step 1: Add sensors command (motion + temperature + battery)**

```python
async def cmd_sensors(bridge):
    """List motion sensors with status."""
    section("Hue Sensors")

    for motion in sorted(bridge.sensors.motion, key=lambda m: m.metadata.name if m.metadata else ""):
        name = motion.metadata.name if motion.metadata else motion.id
        detected = "motion" if motion.motion.motion else "clear"

        # Find the parent device for battery and temperature
        device = None
        if motion.owner:
            device = next((d for d in bridge.devices if d.id == motion.owner.rid), None)

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

    for button in sorted(bridge.sensors.button, key=lambda b: b.metadata.name if b.metadata else ""):
        name = button.metadata.name if button.metadata else button.id
        last_event = button.button.last_event.value if button.button and button.button.last_event else "—"
        print(f"  {name:<30} last: {last_event}")
```

**Step 2: Commit**

```bash
git add lighting/hue.py
git commit -m "feat(lighting): add Hue sensor and button listing"
```

---

### Task 9: Status overview command

**Files:**
- Modify: `lighting/hue.py`

**Step 1: Add status command**

```python
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
            names = ", ".join(m.metadata.name for m in active if m.metadata)
            print(f"  Motion: {names}")
        else:
            print("  Motion: all clear")
```

**Step 2: Commit**

```bash
git add lighting/hue.py
git commit -m "feat(lighting): add Hue status overview"
```

---

### Task 10: Sandbox config and manual test

**Files:**
- Modify: `.claude/settings.local.json` (add Hue bridge IP to allowed network hosts)

**Step 1: Add bridge IP to sandbox network allowlist**

The Hue bridge at `192.168.1.51` needs to be reachable. Add it to `.claude/settings.local.json` under `allowedHosts` if not already present.

**Step 2: Run `just hue pair` and test**

This is a manual step — requires physically pressing the bridge button:

1. Press the link button on the Hue bridge
2. Run: `just hue pair 192.168.1.51`
3. Copy the returned API key to 1Password ("Philips Hue" item, `api_key` field; also set `bridge_ip` to `192.168.1.51`)
4. Run: `just dotenv`
5. Test: `just hue lights`
6. Test: `just hue status`
7. Test: `just hue scenes`
8. Test: `just hue sensors`
9. Test: `just hue buttons`
10. Test: `just hue groups`

**Step 3: Commit any fixups from testing**

---
