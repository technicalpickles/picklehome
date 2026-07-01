"""Map Yale homes onto our canonical picklehome locations.

Yale returns each lock's home as a raw `house_name` string. The shared registry
(`picklehome.locations`) carries a `yale_houses` list per location, letting us
group and filter locks by our canonical slugs (home, beachhouse, ...) with the
same ordering climate uses.

Graceful by design: when no registry is configured, or a lock's house isn't
mapped to any location, the lock still shows up grouped under its raw Yale house
name, sorted after all known locations. Nothing is ever hidden.
"""

from dataclasses import dataclass, field

from picklehome.locations import Location, load_locations
from locks.yale.client import YaleLock


@dataclass
class LockGroup:
    """One display section: a canonical location, or an unmapped raw Yale home."""

    label: str  # section header (location label, or raw Yale house_name)
    order: int  # registry index for mapped groups; sorts unmapped ones last
    locks: list[YaleLock] = field(default_factory=list)


def group_locks(locks: list[YaleLock]) -> list[LockGroup]:
    """Group locks by canonical location, falling back to raw Yale house names.

    Mapped groups keep the registry's ordering (home first, then alphabetical);
    unmapped homes follow, alphabetical by name. Only groups with locks appear.
    """
    locations = load_locations()
    order_by_slug = {loc.slug: i for i, loc in enumerate(locations)}
    location_by_house: dict[str, Location] = {
        house.strip().lower(): loc
        for loc in locations
        for house in loc.yale_houses
    }

    groups: dict[str, LockGroup] = {}
    for lock in locks:
        loc = location_by_house.get(lock.house_name.strip().lower())
        if loc is not None:
            key = f"slug:{loc.slug}"
            group = groups.get(key) or LockGroup(loc.label, order_by_slug[loc.slug])
        else:
            key = f"raw:{lock.house_name}"
            group = groups.get(key) or LockGroup(lock.house_name, len(locations))
        groups[key] = group
        group.locks.append(lock)

    return sorted(groups.values(), key=lambda g: (g.order, g.label.lower()))
