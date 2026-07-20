"""Async ConnectLife wrapper for Hisense ductless HVAC.

Decodes ConnectLife appliances (device type 009, air conditioner) into
``HisenseUnit`` records and writes control commands via ``update_appliance``.

Property model verified against the beach house 009-104 heads (see
docs/research/hisense-connectlife/findings.md):
  t_power       0/1
  t_work_mode   0 fan_only, 1 heat, 2 cool, 3 dry, 4 auto
  t_temp        setpoint, 61-90 F (t_temp_type=1 => Fahrenheit)
  t_fan_speed   0 auto, 5 low, 6 middle_low, 7 medium, 8 middle_high, 9 high
  f_temp_in     current room temp
  f_humidity    raw humidity (sentinel > 100 when unavailable)
  f_e_*         fault flags (nonzero => active)

The library's status_list values are already coerced to int/float by its own
``convert()``, so numeric properties read back as ints.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from climate.hisense.auth import SandboxConnectLifeApi

# ConnectLife device type for air conditioners (all beach house heads are 009).
AC_DEVICE_TYPE = "009"

WORK_MODES = {0: "fan_only", 1: "heat", 2: "cool", 3: "dry", 4: "auto"}
FAN_SPEEDS = {0: "auto", 5: "low", 6: "middle_low", 7: "medium", 8: "middle_high", 9: "high"}

WORK_MODES_REVERSE = {v: k for k, v in WORK_MODES.items()}
FAN_SPEEDS_REVERSE = {v: k for k, v in FAN_SPEEDS.items()}

MODE_CHOICES = list(WORK_MODES_REVERSE)
FAN_CHOICES = list(FAN_SPEEDS_REVERSE)

TEMP_MIN_F = 61
TEMP_MAX_F = 90


class HisenseError(Exception):
    """A ConnectLife call failed for a diagnosable reason."""


@dataclass(frozen=True)
class HisenseUnit:
    puid: str
    name: str
    room: str
    # Raw gateway offlineState. NOT an availability signal: verified == 1 on every
    # head regardless of power, including one confirmed physically on and reporting
    # live (a temp change made at the unit synced back). Kept for JSON/debugging
    # only; never rendered as "offline".
    offline_state: int
    power: bool
    mode: str
    target_temp: int | None
    current_temp: int | None
    humidity: int | None
    fan: str
    faults: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _status_int(status: dict, key: str) -> int | None:
    """Read a numeric status property as int, or None if absent/non-numeric."""
    value = status.get(key)
    if isinstance(value, bool):  # guard: bool is an int subclass
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return None


def unit_from_appliance(appliance) -> HisenseUnit:
    """Decode a ConnectLifeAppliance into a HisenseUnit."""
    status = appliance.status_list
    mode_raw = _status_int(status, "t_work_mode")
    fan_raw = _status_int(status, "t_fan_speed")
    humidity = _status_int(status, "f_humidity")

    faults = sorted(
        key[len("f_e_"):]
        for key, value in status.items()
        if key.startswith("f_e_") and isinstance(value, (int, float)) and value != 0
    )

    return HisenseUnit(
        puid=appliance.puid,
        name=appliance.device_nickname,
        room=appliance.room_name,
        offline_state=appliance.offline_state,
        power=bool(_status_int(status, "t_power")),
        mode=WORK_MODES.get(mode_raw, "unknown") if mode_raw is not None else "unknown",
        target_temp=_status_int(status, "t_temp"),
        current_temp=_status_int(status, "f_temp_in"),
        # Values above 100 are the "no reading" sentinel (e.g. 128 when idle).
        humidity=humidity if humidity is not None and 0 <= humidity <= 100 else None,
        fan=FAN_SPEEDS.get(fan_raw, "unknown") if fan_raw is not None else "unknown",
        faults=faults,
    )


def build_control_properties(
    *,
    power: bool | None = None,
    mode: str | None = None,
    temp: int | None = None,
    fan: str | None = None,
) -> dict[str, str]:
    """Translate CLI control args into raw ConnectLife properties.

    Raises ValueError for unknown modes/fan speeds or out-of-range temps, and
    when nothing was requested.
    """
    props: dict[str, str] = {}

    if power is not None:
        props["t_power"] = "1" if power else "0"

    if mode is not None:
        if mode not in WORK_MODES_REVERSE:
            raise ValueError(f"Unknown mode '{mode}'. Valid: {', '.join(MODE_CHOICES)}")
        props["t_work_mode"] = str(WORK_MODES_REVERSE[mode])

    if temp is not None:
        if not (TEMP_MIN_F <= temp <= TEMP_MAX_F):
            raise ValueError(f"Temperature {temp} out of range ({TEMP_MIN_F}-{TEMP_MAX_F} F)")
        props["t_temp"] = str(int(temp))

    if fan is not None:
        if fan not in FAN_SPEEDS_REVERSE:
            raise ValueError(f"Unknown fan speed '{fan}'. Valid: {', '.join(FAN_CHOICES)}")
        props["t_fan_speed"] = str(FAN_SPEEDS_REVERSE[fan])

    if not props:
        raise ValueError("No control options given (use --power/--mode/--temp/--fan)")

    return props


async def get_units(username: str, password: str) -> list[HisenseUnit]:
    """Log in and return all air-conditioner heads on the account."""
    api = SandboxConnectLifeApi(username, password)
    try:
        appliances = await api.get_appliances()
    except Exception as e:
        raise HisenseError(f"Failed to fetch ConnectLife appliances: {e}") from e
    return [
        unit_from_appliance(a)
        for a in appliances
        if a.device_type_code == AC_DEVICE_TYPE
    ]


async def set_unit(username: str, password: str, puid: str, properties: dict[str, str]) -> None:
    """Push a control property update to one head."""
    api = SandboxConnectLifeApi(username, password)
    try:
        await api.update_appliance(puid, properties)
    except Exception as e:
        raise HisenseError(f"Failed to update appliance {puid}: {e}") from e
