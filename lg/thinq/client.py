"""Async client for LG ThinQ Connect: washer, dryer, and refrigerator status.

This is the only module that imports thinqconnect's device-fetching surface
(ThinQApi, ThinQAPIException). It returns plain dataclasses (Laundry,
Refrigerator) so nothing downstream -- the CLI today, a watcher later -- ever
sees a raw LG response. Swapping the SDK means touching only this file.

READ-ONLY: only async_get_device_list, async_get_device_profile, and
async_get_device_status are called. No control/write paths.

Every normalization here is load-bearing, not cosmetic -- each one is a
correctness finding from docs/research/lg-thinq/findings.md, confirmed against
the real account on 2026-08-02:

1. Washer status/profile come back as a JSON *list* (location-scoped, one
   entry); dryer and refrigerator come back as *dicts*. `_as_dict` normalizes.
2. Profiles are wrapped in error/notification/property, with the schema
   under `property` (and for the washer, `property` is itself a list) -- this
   is true of the raw shape, but nothing in this module unwraps it: no code
   path here reads profile fields programmatically. `get_raw_dump` (`devices
   --raw`) passes the profile through unmodified by design. If a future
   caller needs profile data (schema discovery, range validation against the
   declared min/max), add the unwrap here rather than assuming it already
   exists.
3. `deviceInfo.connected` is always null on this account -- never treated as
   an availability signal.
4. `runState.currentState` enums declare `END` but it fires on neither
   appliance (confirmed across two full cycles). Completion is instead
   detected via the washer's monotonic `cycle.cycleCount` (see
   observations.py) -- the dryer has no equivalent property and gets no
   completion detection in v1.
5. `remain == 0` while a run state is "active" means "not yet computed" (seen
   during washer DETECTING), not "done" -- rendered as an unknown remaining
   time rather than "0m left".
6. Timer values (remain/total) are only meaningful while the appliance is in
   an active run state; both machines retain stale/placeholder values while
   idle.
7. Refrigerator temperatures are setpoints (`targetTemperature`), not a
   measured air temperature -- callers must label them "(setpoint)".
8. Filter fields (`freshAirFilterRemainPercent`, `waterFilter1RemainPercent`)
   are unpopulated placeholders (always 0, not wired to hardware on this
   model) and are not exposed on the Refrigerator dataclass at all.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from thinqconnect import ThinQApi, ThinQAPIErrorCodes, ThinQAPIException

from lg.thinq.auth import describe_auth_error

DEVICE_TYPE_WASHER = "DEVICE_WASHER"
DEVICE_TYPE_DRYER = "DEVICE_DRYER"
DEVICE_TYPE_REFRIGERATOR = "DEVICE_REFRIGERATOR"

# Per-device-type active-state constants (docs/plans/2026-08-02-lg-thinq-design.md,
# "Completion detection" section). These are declared enums, not observed
# sequences -- INITIAL and SOAKING were never seen on the washer, INITIAL and
# WRINKLE_CARE never seen on the dryer, but they're kept as members of the
# "may arrive" set rather than dropped. PAUSE is deliberately in neither set:
# it's not active, and it's not completion either.
WASHER_ACTIVE_STATES = frozenset({"INITIAL", "DETECTING", "RUNNING", "SOAKING", "RINSING", "SPINNING"})
DRYER_ACTIVE_STATES = frozenset({"INITIAL", "RUNNING", "COOLING", "WRINKLE_CARE"})

# LG ThinQ error codes that indicate a transient, self-clearing problem
# rather than a credentials issue (see auth.AUTH_ERROR_CODES for those).
_RATE_LIMIT_ERROR_CODES = frozenset({ThinQAPIErrorCodes.EXCEEDED_API_CALLS})


class LGThinQError(RuntimeError):
    """Raised for LG ThinQ API failures, with which device/call/response failed."""


class LGThinQAuthError(LGThinQError):
    """Raised when LG rejected the token itself (expired/revoked), not a per-request fluke."""


class LGThinQRateLimitError(LGThinQError):
    """Raised when ThinQ Connect rate-limited this request. Transient -- clears on its own."""


def _wrap_api_error(exc: ThinQAPIException, device_name: str, call: str) -> LGThinQError:
    """Classify a ThinQAPIException so the CLI can present a useful message.

    Auth-rejection classification itself lives in auth.describe_auth_error --
    this just decides which exception type to raise, adding the
    device/call context auth.py doesn't have.
    """
    detail = f"{call} failed for {device_name}: {exc.error_name} ({exc.code}) - {exc.message}"
    auth_message = describe_auth_error(exc)
    if auth_message is not None:
        return LGThinQAuthError(f"{auth_message} (while fetching {call} for {device_name})")
    if exc.code in _RATE_LIMIT_ERROR_CODES:
        return LGThinQRateLimitError(
            f"LG ThinQ rate-limited {call} for {device_name} ({exc.error_name}). "
            "This is transient and should clear on its own -- not a credentials problem."
        )
    return LGThinQError(detail)


def _as_dict(raw: dict | list | None, device_name: str, what: str) -> dict:
    """Normalize the washer's list-wrapped payloads to a dict like everything else.

    Confirmed: washer status/profile are JSON lists (location-scoped, single
    entry); dryer and refrigerator are dicts. See module docstring point 1.
    """
    if raw is None:
        raise LGThinQError(f"{device_name}: {what} returned no data")
    if isinstance(raw, list):
        if not raw:
            raise LGThinQError(f"{device_name}: {what} returned an empty list")
        return raw[0]
    return raw


@dataclass
class DeviceRef:
    """One entry from async_get_device_list, identified by device type -- not nickname.

    Nicknames are user-editable in the ThinQ app and drift; device_type does not.
    """

    device_id: str
    alias: str
    device_type: str
    model: str


@dataclass
class Laundry:
    """Normalized washer or dryer state. `appliance` is "washer" or "dryer"."""

    device_id: str
    appliance: str
    name: str
    model: str
    state: str
    active: bool
    remain_minutes: int | None
    total_minutes: int | None
    remote_available: bool
    cycle_count: int | None  # washer only; always None for dryer (no equivalent property)


@dataclass
class Refrigerator:
    """Normalized refrigerator state.

    fridge_setpoint / freezer_setpoint are setpoints (targetTemperature),
    never a measured temperature -- callers must render them with an explicit
    "(setpoint)" label. Each carries its own `_unit` ("F" or "C") read from
    the payload's sibling `unit` key -- never assume Fahrenheit. The account
    has always reported "F" so far, but the profile itself declares setpoint
    ranges in Celsius (module docstring point 7 / findings.md), so a display
    unit flip is a real possibility, not a hypothetical. Filter fields are
    intentionally not represented here (see module docstring point 8).
    """

    device_id: str
    name: str
    model: str
    door_state: str  # "open" | "closed" | "unknown"
    fridge_setpoint: int | None
    fridge_setpoint_unit: str | None
    freezer_setpoint: int | None
    freezer_setpoint_unit: str | None
    power_save: bool
    express_mode: bool
    sabbath_mode: bool


def _parse_device_ref(raw: dict) -> DeviceRef:
    info = raw.get("deviceInfo") or {}
    return DeviceRef(
        device_id=raw["deviceId"],
        alias=info.get("alias") or raw["deviceId"],
        device_type=info.get("deviceType", "UNKNOWN"),
        model=info.get("modelName", ""),
    )


async def list_devices(api: ThinQApi) -> list[DeviceRef]:
    """Fetch the account's device inventory."""
    try:
        raw = await api.async_get_device_list()
    except ThinQAPIException as e:
        raise _wrap_api_error(e, "account", "device list") from e
    if raw is None:
        raise LGThinQError("device list returned no data")
    return [_parse_device_ref(d) for d in raw]


async def _get_status(api: ThinQApi, device: DeviceRef) -> dict:
    try:
        raw = await api.async_get_device_status(device.device_id)
    except ThinQAPIException as e:
        raise _wrap_api_error(e, device.alias, "device status") from e
    return _as_dict(raw, device.alias, "device status")


async def get_laundry(api: ThinQApi, device: DeviceRef, appliance: str) -> Laundry:
    """Fetch and normalize washer or dryer status. `appliance` selects the active-state set."""
    if appliance not in ("washer", "dryer"):
        raise ValueError(f"appliance must be 'washer' or 'dryer', got {appliance!r}")

    status = await _get_status(api, device)

    run_state = (status.get("runState") or {}).get("currentState", "UNKNOWN")
    active_states = WASHER_ACTIVE_STATES if appliance == "washer" else DRYER_ACTIVE_STATES
    active = run_state in active_states

    remain_minutes: int | None = None
    total_minutes: int | None = None
    if active:
        timer = status.get("timer") or {}
        total_minutes = (timer.get("totalHour") or 0) * 60 + (timer.get("totalMinute") or 0)
        computed_remain = (timer.get("remainHour") or 0) * 60 + (timer.get("remainMinute") or 0)
        # remain == 0 while active means "not yet computed" (e.g. washer
        # DETECTING reports remain 0h00m / total 0h58m), never "done" --
        # module docstring point 5. Timer values while NOT active are simply
        # not read at all (point 6).
        remain_minutes = computed_remain if computed_remain > 0 else None

    cycle_count = None
    if appliance == "washer":
        cycle_count = (status.get("cycle") or {}).get("cycleCount")

    return Laundry(
        device_id=device.device_id,
        appliance=appliance,
        name=device.alias,
        model=device.model,
        state=run_state,
        active=active,
        remain_minutes=remain_minutes,
        total_minutes=total_minutes,
        remote_available=bool((status.get("remoteControlEnable") or {}).get("remoteControlEnabled", False)),
        cycle_count=cycle_count,
    )


def _normalize_door_state(raw_state: str | None) -> str:
    if raw_state == "CLOSE":
        return "closed"
    if raw_state == "OPEN":
        return "open"
    return "unknown"


async def get_refrigerator(api: ThinQApi, device: DeviceRef) -> Refrigerator:
    """Fetch and normalize refrigerator status."""
    status = await _get_status(api, device)

    door_entries = status.get("doorStatus") or []
    door_raw = None
    for entry in door_entries:
        if entry.get("locationName") == "MAIN":
            door_raw = entry.get("doorState")
            break
    else:
        if door_entries:
            door_raw = door_entries[0].get("doorState")

    fridge_value = freezer_value = None
    fridge_unit = freezer_unit = None
    for entry in status.get("temperature") or []:
        loc = entry.get("locationName")
        if loc not in ("FRIDGE", "FREEZER"):
            continue
        value = entry.get("targetTemperature")
        if value is None:
            continue
        # The unit isn't optional to render (module docstring point 7 /
        # findings.md: profile declares Celsius ranges, status has reported
        # Fahrenheit so far but nothing guarantees that stays true). Rather
        # than assume "F" and silently mislabel a Celsius reading, raise if
        # the payload ever omits its own sibling `unit` key.
        unit = entry.get("unit")
        if unit is None:
            raise LGThinQError(
                f"{device.alias}: temperature entry for {loc} has targetTemperature "
                f"({value!r}) but no sibling 'unit' key"
            )
        if loc == "FRIDGE":
            fridge_value, fridge_unit = value, unit
        else:
            freezer_value, freezer_unit = value, unit

    return Refrigerator(
        device_id=device.device_id,
        name=device.alias,
        model=device.model,
        door_state=_normalize_door_state(door_raw),
        fridge_setpoint=fridge_value,
        fridge_setpoint_unit=fridge_unit,
        freezer_setpoint=freezer_value,
        freezer_setpoint_unit=freezer_unit,
        power_save=bool((status.get("powerSave") or {}).get("powerSaveEnabled", False)),
        express_mode=bool((status.get("refrigeration") or {}).get("expressMode", False)),
        sabbath_mode=bool((status.get("sabbath") or {}).get("sabbathMode", False)),
    )


async def get_appliance(api: ThinQApi, device: DeviceRef) -> Laundry | Refrigerator:
    """Dispatch a single device by its device_type. Raises LGThinQError for unsupported types.

    Only DEVICE_WASHER, DEVICE_DRYER, and DEVICE_REFRIGERATOR are handled --
    the WASHTOWER*/WASHCOMBO* combo-unit types are not present on this
    account and are deliberately not handled speculatively (see the design
    doc's "Three separate appliances, no WashTower" note).
    """
    if device.device_type == DEVICE_TYPE_WASHER:
        return await get_laundry(api, device, "washer")
    if device.device_type == DEVICE_TYPE_DRYER:
        return await get_laundry(api, device, "dryer")
    if device.device_type == DEVICE_TYPE_REFRIGERATOR:
        return await get_refrigerator(api, device)
    raise LGThinQError(f"{device.alias}: unsupported device type {device.device_type!r}")


async def get_appliances(
    api: ThinQApi, devices: list[DeviceRef]
) -> list[tuple[DeviceRef, Laundry | Refrigerator | BaseException]]:
    """Fetch all given devices concurrently.

    Uses return_exceptions=True so one appliance failing (timeout, rate limit,
    bad token) doesn't cancel the others -- the caller pairs each DeviceRef
    with either its normalized result or the exception that occurred.
    """
    results = await asyncio.gather(*(get_appliance(api, d) for d in devices), return_exceptions=True)
    return list(zip(devices, results))


async def get_raw_dump(api: ThinQApi, device: DeviceRef) -> dict:
    """Fetch unmassaged profile + status for one device. For `lg devices --raw` only."""
    try:
        profile = await api.async_get_device_profile(device.device_id)
    except ThinQAPIException as e:
        raise _wrap_api_error(e, device.alias, "device profile") from e
    try:
        status = await api.async_get_device_status(device.device_id)
    except ThinQAPIException as e:
        raise _wrap_api_error(e, device.alias, "device status") from e
    return {
        "device_id": device.device_id,
        "alias": device.alias,
        "device_type": device.device_type,
        "model": device.model,
        "profile": profile,
        "status": status,
    }
