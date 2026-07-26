ECOBEE_SENTINEL = -5002


def decode_temp(raw: int) -> float | None:
    """Convert Ecobee's tenths-of-degree int to float °F. Returns None for sentinel/zero."""
    if raw == ECOBEE_SENTINEL or raw == 0:
        return None
    return raw / 10


def get_equipment_description(equipment_status: str) -> str:
    """Return human description of equipment status. Empty string means idle."""
    return equipment_status if equipment_status else "idle"


def get_active_hold(events: list) -> dict | None:
    """Return the first running hold event as a simplified dict, or None."""
    for event in events:
        if event.get("type") == "hold" and event.get("running"):
            end = (
                "indefinite"
                if event.get("isIndefinite")
                else f"{event['endDate']} {event['endTime']}"
            )
            return {
                "end": end,
                "cool_temp": decode_temp(event["coolHoldTemp"]),
                "heat_temp": decode_temp(event["heatHoldTemp"]),
            }
    return None


def get_climate_setpoints(climates: list, climate_ref: str) -> tuple[float | None, float | None]:
    """Return (cool_setpoint, heat_setpoint) for the named climate ref, or (None, None)."""
    for c in climates:
        if c.get("climateRef") == climate_ref:
            return decode_temp(c.get("coolTemp", 0)), decode_temp(c.get("heatTemp", 0))
    return None, None


def extract_thermostat_status(thermostat: dict) -> dict:
    """Extract a flat status dict from a raw thermostat API response."""
    runtime = thermostat.get("runtime", {})
    forecasts = thermostat.get("weather", {}).get("forecasts", [])
    current_weather = forecasts[0] if forecasts else {}

    aq_score = runtime.get("actualAQScore", ECOBEE_SENTINEL)
    voc = runtime.get("actualVOC", ECOBEE_SENTINEL)
    co2 = runtime.get("actualCO2", ECOBEE_SENTINEL)

    program = thermostat.get("program", {})
    climate_ref = program.get("currentClimateRef")
    cool_setpoint, heat_setpoint = get_climate_setpoints(program.get("climates", []), climate_ref)

    return {
        "name": thermostat.get("name"),
        "temp": decode_temp(runtime.get("actualTemperature", 0)),
        "humidity": runtime.get("actualHumidity"),
        "equipment": get_equipment_description(thermostat.get("equipmentStatus", "")),
        "hvac_mode": thermostat.get("settings", {}).get("hvacMode"),
        "climate_ref": climate_ref,
        "cool_setpoint": cool_setpoint,
        "heat_setpoint": heat_setpoint,
        "hold": get_active_hold(thermostat.get("events", [])),
        "aq_score": None if aq_score == ECOBEE_SENTINEL else aq_score,
        "voc": None if voc == ECOBEE_SENTINEL else voc,
        "co2": None if co2 == ECOBEE_SENTINEL else co2,
        "weather": {
            "temp": decode_temp(current_weather.get("temperature", 0)),
            "condition": current_weather.get("condition"),
            "humidity": current_weather.get("relativeHumidity"),
            "wind_speed": current_weather.get("windSpeed"),
            "wind_direction": current_weather.get("windDirection"),
        } if current_weather else None,
    }


def format_status(statuses: list[dict]) -> str:
    """Format a list of thermostat status dicts as a human-readable string."""
    lines = []

    for s in statuses:
        temp = f"{s['temp']}°F" if s["temp"] is not None else "?°F"
        humidity = f"{s['humidity']}%" if s["humidity"] is not None else "?"
        equipment = s["equipment"]
        hvac = s["hvac_mode"] or "?"

        hold_str = ""
        if s["hold"]:
            end = s["hold"]["end"]
            hold_str = f"  hold until {end}"

        climate = s["climate_ref"] or ""
        if s["hold"]:
            cool_sp = s["hold"]["cool_temp"]
            heat_sp = s["hold"]["heat_temp"]
        else:
            cool_sp = s.get("cool_setpoint")
            heat_sp = s.get("heat_setpoint")
        if cool_sp is not None and heat_sp is not None:
            climate = f"{climate} {heat_sp:.0f}/{cool_sp:.0f}°F"
        line = f"{s['name']:<14} {temp:<8} {humidity:<5} {equipment:<10} {climate:<20} {hvac}{hold_str}"
        lines.append(line.rstrip())

    # Weather: use first thermostat's weather (they share the same feed by location)
    weather_added = False
    for s in statuses:
        w = s.get("weather")
        if w and w.get("temp") is not None and not weather_added:
            cond = w["condition"] or ""
            wind = f"{w['wind_speed']}mph {w['wind_direction']}" if w["wind_speed"] else ""
            lines.append(f"{'Outdoor':<14} {w['temp']}°F     {w['humidity']}%   {cond} {wind}".rstrip())
            weather_added = True
            break

    # Air quality section
    aq_lines = []
    for s in statuses:
        if s["aq_score"] is not None:
            parts = [f"AQ {s['aq_score']}"]
            if s["voc"] is not None:
                parts.append(f"VOC {s['voc']}ppm")
            if s["co2"] is not None:
                parts.append(f"CO2 {s['co2']}ppm")
            aq_lines.append(f"  {s['name']}: {'  '.join(parts)}")

    if aq_lines:
        lines.append("")
        lines.append("Air quality:")
        lines.extend(aq_lines)

    return "\n".join(lines)
