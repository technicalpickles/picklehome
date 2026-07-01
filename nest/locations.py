"""Map Nest/SDM structures onto our canonical picklehome locations.

SDM structures carry only an opaque id plus a "custom name" the account owner
sets in the Google Home app. The shared registry (`picklehome.locations`)
carries a `nest_structures` list per location, letting us group and filter
devices by our canonical slugs (home, beachhouse, ...) the same way
locks/locations.py does for Yale homes.

Graceful by design: when no registry is configured, or a device's structure
isn't mapped to any location, the device still shows up grouped under its raw
structure name, sorted after all known locations. Nothing is ever hidden.
"""

from dataclasses import dataclass, field

from nest.sdm.client import NestDevice
from picklehome.locations import Location, load_locations


@dataclass
class DeviceGroup:
    """One display section: a canonical location, or an unmapped raw structure."""

    label: str  # section header (location label, or raw structure custom_name)
    order: int  # registry index for mapped groups; sorts unmapped ones last
    devices: list[NestDevice] = field(default_factory=list)


def group_devices(devices: list[NestDevice], structure_names_by_id: dict[str, str]) -> list[DeviceGroup]:
    """Group devices by canonical location, falling back to raw structure names.

    `structure_names_by_id` maps structure id -> custom_name, as returned by
    get_structures(); devices only carry the id.
    """
    locations = load_locations()
    order_by_slug = {loc.slug: i for i, loc in enumerate(locations)}
    location_by_structure_name: dict[str, Location] = {
        structure_name.strip().lower(): loc
        for loc in locations
        for structure_name in loc.nest_structures
    }

    groups: dict[str, DeviceGroup] = {}
    for device in devices:
        structure_name = structure_names_by_id.get(device.structure_id, device.structure_id)
        loc = location_by_structure_name.get(structure_name.strip().lower())
        if loc is not None:
            key = f"slug:{loc.slug}"
            group = groups.get(key) or DeviceGroup(loc.label, order_by_slug[loc.slug])
        else:
            key = f"raw:{structure_name}"
            group = groups.get(key) or DeviceGroup(structure_name, len(locations))
        groups[key] = group
        group.devices.append(device)

    return sorted(groups.values(), key=lambda g: (g.order, g.label.lower()))
