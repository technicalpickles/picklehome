"""Human-readable formatting for Hisense units."""

from __future__ import annotations

from climate.hisense.client import HisenseUnit


def _fmt_temp(value: int | None) -> str:
    return f"{value}°F" if value is not None else "?"


def format_status(units: list[HisenseUnit]) -> str:
    if not units:
        return "No Hisense units found."

    lines: list[str] = []
    for u in units:
        lines.append(f"{u.name}  [{u.room}]")

        parts = ["on" if u.power else "off"]
        if u.power:
            parts.append(u.mode)
        parts.append(f"set {_fmt_temp(u.target_temp)}")
        if u.current_temp is not None:
            parts.append(f"current {u.current_temp}°F")
        parts.append(f"fan {u.fan}")
        if u.humidity is not None:
            parts.append(f"humidity {u.humidity}%")
        lines.append("  " + "  ".join(parts))

        if u.faults:
            lines.append(f"  Faults: {', '.join(u.faults)}")

        lines.append("")

    return "\n".join(lines).rstrip()
