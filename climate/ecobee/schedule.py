import sys
from pathlib import Path

import yaml
from pyecobee.const import ECOBEE_ENDPOINT_THERMOSTAT

from climate.ecobee.thermostats import get_thermostat_id


def get_current_program(ecobee, thermostat_id: str) -> dict:
    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        raise RuntimeError("Failed to fetch thermostat data from Ecobee.")
    thermostat = next(
        (t for t in ecobee.thermostats if t["identifier"] == thermostat_id), None
    )
    if thermostat is None:
        raise LookupError(
            f"Thermostat {thermostat_id} not found. Re-run 'just climate-auth'."
        )
    program = thermostat.get("program")
    if program is None:
        raise RuntimeError(f"Thermostat {thermostat_id} returned no program data.")
    return program


def push_schedule(ecobee, thermostat_id: str, schedule_array: list, climates: list) -> None:
    body = {
        "selection": {
            "selectionType": "thermostats",
            "selectionMatch": thermostat_id,
        },
        "thermostat": {
            "program": {
                "schedule": schedule_array,
                "climates": climates,
            }
        },
    }
    response = ecobee._request_with_refresh(
        "POST", ECOBEE_ENDPOINT_THERMOSTAT, "push schedule", body=body
    )
    if response is None:
        raise RuntimeError("Failed to push schedule to Ecobee.")


def load_schedule(path: str | Path) -> dict:
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except OSError as e:
        print(f"Cannot read schedule file: {path}: {e}")
        sys.exit(1)
    if data is None or not isinstance(data, dict):
        print("schedule.yaml is empty or invalid")
        sys.exit(1)
    if "thermostats" not in data:
        print("schedule.yaml must have a top-level 'thermostats' key")
        sys.exit(1)
    return data


def iter_thermostat_entries(data: dict, registry: dict, name_filter: str | None = None):
    """Yield (name, thermostat_id, schedule_dict) for each configured thermostat."""
    for name, entry in data["thermostats"].items():
        if name_filter and name != name_filter:
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"Thermostat '{name}' entry must be a mapping")
        try:
            thermostat_id = get_thermostat_id(registry, name)
        except KeyError:
            raise ValueError(
                f"Thermostat '{name}' in schedule.yaml not found in thermostats.yaml"
            )
        schedule_dict = entry.get("schedule")
        if not isinstance(schedule_dict, dict):
            raise ValueError(f"Thermostat '{name}' is missing 'schedule'")
        yield name, thermostat_id, schedule_dict


def time_to_slot(time_str: str) -> int:
    try:
        hour_str, minute_str = time_str.split(":")
        hour = int(hour_str)
        minute = int(minute_str)
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid time format: {time_str} — expected HH:MM")
    if not (0 <= hour <= 23):
        raise ValueError(f"Invalid hour in {time_str}")
    if minute not in (0, 30):
        raise ValueError(
            f"Time {time_str} not 30-minute aligned. Use :00 or :30 — Ecobee uses 30-minute slots."
        )
    return hour * 2 + minute // 30


def expand_day(day_name: str, transitions: list[dict]) -> list[str]:
    if not transitions:
        raise ValueError(f"Day '{day_name}' has no transitions.")
    pairs = [(time_to_slot(t["time"]), t["climate"]) for t in transitions]
    pairs.sort(key=lambda x: x[0])

    # Validate 00:00 start after sorting (author may write transitions out of order)
    if pairs[0][0] != 0:
        first_hour, first_min = pairs[0][0] // 2, (pairs[0][0] % 2) * 30
        raise ValueError(
            f"Day '{day_name}': first transition must be time '00:00', "
            f"got '{first_hour:02d}:{first_min:02d}'"
        )

    # Detect duplicate slots
    slots = [s for s, _ in pairs]
    dupes = sorted({s for s in slots if slots.count(s) > 1})
    if dupes:
        dupe_times = [f"{s // 2:02d}:{(s % 2) * 30:02d}" for s in dupes]
        raise ValueError(f"Day '{day_name}': duplicate time(s): {', '.join(dupe_times)}")

    result = [""] * 48
    for i, (slot, climate) in enumerate(pairs):
        if i < len(pairs) - 1:
            next_slot = pairs[i + 1][0]
            result[slot:next_slot] = [climate] * (next_slot - slot)
        else:
            result[slot:48] = [climate] * (48 - slot)

    # Guard: all slots must be filled (belt-and-suspenders against logic gaps)
    if "" in result:
        raise ValueError(f"Day '{day_name}': internal error — unexpanded slots remain")

    return result


DAYS_ORDER = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]


def build_schedule_array(schedule_dict: dict) -> list[list[str]]:
    required = set(DAYS_ORDER)
    missing = required - set(schedule_dict.keys())
    if missing:
        raise ValueError(
            f"Missing days in schedule: {sorted(missing)}. All 7 days are required."
        )
    return [expand_day(day, schedule_dict[day]) for day in DAYS_ORDER]


def validate_climate_refs(schedule_dict: dict, program: dict) -> None:
    valid = {c["climateRef"] for c in program["climates"]}
    used = set()
    for transitions in schedule_dict.values():
        if not isinstance(transitions, list):
            continue  # skip anchor-definition keys and other non-list values
        for entry in transitions:
            if isinstance(entry, dict) and "climate" in entry:
                used.add(entry["climate"])
    unknowns = used - valid
    if unknowns:
        raise ValueError(
            f"Unknown climate(s): {sorted(unknowns)}. "
            f"Valid climateRefs for this thermostat: {sorted(valid)}"
        )


def diff_schedules(local: list, remote: list, program: dict) -> list[str]:
    """Return human-readable lines describing slots where local and remote differ.

    Both arrays are 7×48 lists of climateRef strings.
    Returns an empty list if they are identical.
    """
    day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    ref_to_name = {c["climateRef"]: c.get("name", c["climateRef"]) for c in program["climates"]}
    lines = []
    for day_idx, (local_day, remote_day) in enumerate(zip(local, remote)):
        for slot, (l, r) in enumerate(zip(local_day, remote_day)):
            if l != r:
                hour = slot // 2
                minute = (slot % 2) * 30
                ln = ref_to_name.get(l, l)
                rn = ref_to_name.get(r, r)
                lines.append(
                    f"  {day_names[day_idx]} {hour:02d}:{minute:02d}  local={ln}  remote={rn}"
                )
    return lines


def print_schedule_grid(schedule_array: list, program: dict, name: str = "") -> None:
    day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    ref_to_name = {c["climateRef"]: c.get("name", c["climateRef"]) for c in program["climates"]}

    header = f"Schedule preview — {name}" if name else "Schedule preview"
    print(f"{header} (transitions only):\n")
    for day_idx, day_slots in enumerate(schedule_array):
        print(day_names[day_idx])
        prev = None
        for slot, climate in enumerate(day_slots):
            if climate != prev:
                hour = slot // 2
                minute = (slot % 2) * 30
                display = ref_to_name.get(climate, climate)
                print(f"  {hour:02d}:{minute:02d}  {display}")
                prev = climate
