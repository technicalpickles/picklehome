"""Lutron Caseta commands: device listing, status, and control."""

from lighting import section


# ── Device type display ──────────────────────────────────────────────────────

DEVICE_TYPES = {
    "WallDimmer": "Dimmer",
    "WallSwitch": "Switch",
    "CasetaFanSpeedController": "Fan",
    "SmartBridge": "Bridge",
}


def _type_label(dtype):
    return DEVICE_TYPES.get(dtype, dtype)


def _state_str(device):
    """Human-readable state for a device."""
    dtype = device.get("type", "")
    state = device.get("current_state", -1)

    if "Fan" in dtype:
        fan = device.get("fan_speed", None)
        return fan if fan else "?"
    if state == -1:
        return "n/a"
    if state == 0:
        return "off"
    if state == 100:
        return "on"
    return f"{state}%"


# ── Commands ─────────────────────────────────────────────────────────────────

async def cmd_devices(bridge):
    """List all devices with current state."""
    section("Lutron Caseta Devices")

    devices = bridge.get_devices()
    # Group by room (name prefix before underscore)
    by_room = {}
    for did, dev in sorted(devices.items(), key=lambda x: x[1].get("name", "")):
        if dev.get("type") == "SmartBridge":
            continue
        name = dev.get("name", "?")
        room = name.split("_")[0] if "_" in name else "Other"
        by_room.setdefault(room, []).append((did, dev))

    print(f"  {'Device':<35} {'Type':<10} {'State':<10} {'Model':<14} {'ID':>4}")
    print(f"  {'─'*35} {'─'*10} {'─'*10} {'─'*14} {'─'*4}")

    current_room = None
    for room in sorted(by_room):
        if room != current_room:
            current_room = room
        for did, dev in by_room[room]:
            name = dev.get("name", "?")
            dtype = _type_label(dev.get("type", "?"))
            model = dev.get("model", "?")
            state = _state_str(dev)
            print(f"  {name:<35} {dtype:<10} {state:<10} {model:<14} {did:>4}")


async def cmd_status(bridge):
    """Show current state of all controllable zones."""
    section("Lutron Caseta Status")

    devices = bridge.get_devices()
    for did, dev in sorted(devices.items(), key=lambda x: x[1].get("name", "")):
        if dev.get("type") == "SmartBridge":
            continue
        name = dev.get("name", "?")
        state = _state_str(dev)
        dtype = _type_label(dev.get("type", "?"))
        indicator = "●" if state.lower() not in ("off", "n/a", "?") else "○"
        print(f"  {indicator} {name:<35} {state}")


async def cmd_on(bridge, query):
    """Turn on a device (dimmer to 100%, switch on)."""
    did, dev = _find_device(bridge, query)
    await bridge.turn_on(did)
    print(f"  Turned on: {dev.get('name', did)}")


async def cmd_off(bridge, query):
    """Turn off a device."""
    did, dev = _find_device(bridge, query)
    await bridge.turn_off(did)
    print(f"  Turned off: {dev.get('name', did)}")


async def cmd_set(bridge, query, value):
    """Set a dimmer level (0-100) or fan speed (off/low/medium/high)."""
    did, dev = _find_device(bridge, query)
    dtype = dev.get("type", "")

    if "Fan" in dtype:
        speeds = {"off": "Off", "low": "Low", "medium": "Medium", "mediumhigh": "MediumHigh", "high": "High"}
        speed = speeds.get(value.lower())
        if not speed:
            print(f"  Invalid fan speed: {value}")
            print(f"  Valid speeds: {', '.join(speeds.keys())}")
            return
        await bridge.set_fan(did, speed)
        print(f"  Set {dev.get('name', did)} fan to {speed}")
    else:
        try:
            level = int(value)
        except ValueError:
            print(f"  Invalid brightness level: {value} (expected 0-100)")
            return
        if not 0 <= level <= 100:
            print(f"  Level must be 0-100, got {level}")
            return
        await bridge.set_value(did, level)
        print(f"  Set {dev.get('name', did)} to {level}%")


def _find_device(bridge, query):
    """Find a device by name substring or ID. Returns (device_id, device_dict)."""
    devices = bridge.get_devices()
    q = query.lower()

    # Try exact ID match first
    if q in devices:
        return q, devices[q]

    # Fuzzy name match
    matches = [
        (did, dev) for did, dev in devices.items()
        if q in dev.get("name", "").lower()
        and dev.get("type") != "SmartBridge"
    ]

    if not matches:
        import sys
        sys.exit(f"No device matching '{query}'")

    if len(matches) > 1:
        print(f"  Multiple devices match '{query}':")
        for did, dev in matches:
            print(f"    [{did}] {dev.get('name', '?')}")
        import sys
        sys.exit("Be more specific")

    return matches[0]
