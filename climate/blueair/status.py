def _c_to_f(celsius: int | float | None) -> int | None:
    """Convert Celsius to Fahrenheit. BlueAir API returns Celsius integers."""
    if celsius is None:
        return None
    return round(celsius * 9 / 5 + 32)


def _int(value) -> int | None:
    """Coerce a numeric value to int for clean display (e.g. 77.0 -> 77)."""
    if value is None:
        return None
    return int(value)


def format_status(statuses: list[dict]) -> str:
    lines = []

    for s in statuses:
        name = s["name"]
        # Shorten model name for display
        model = s["model"].replace("Blueair ", "")
        lines.append(f"{name} ({model})")

        if s.get("standby"):
            lines.append("  Standby")
            if s["filter_usage_percentage"] is not None:
                lines.append(f"  Filter: {s['filter_usage_percentage']}% remaining")
            lines.append("")
            continue

        # Air quality
        aq_parts = []
        if s["pm2_5"] is not None:
            aq_parts.append(f"PM2.5 {s['pm2_5']}")
        if s["pm1"] is not None:
            aq_parts.append(f"PM1 {s['pm1']}")
        if s["pm10"] is not None:
            aq_parts.append(f"PM10 {s['pm10']}")
        if s["total_voc"] is not None:
            aq_parts.append(f"VOC {s['total_voc']}")
        elif s["voc"] is not None:
            aq_parts.append(f"VOC {s['voc']}")
        if aq_parts:
            lines.append(f"  Air Quality: {', '.join(aq_parts)}")

        # Environment
        env_parts = []
        temp_f = _c_to_f(s["temperature"])
        if temp_f is not None:
            env_parts.append(f"{temp_f}°F")
        if s["humidity"] is not None:
            env_parts.append(f"{s['humidity']}% humidity")
        if env_parts:
            lines.append(f"  Environment: {', '.join(env_parts)}")

        # Fan
        fan_mode = "Auto" if s["fan_auto_mode"] else "Manual"
        if s["night_mode"]:
            fan_mode = "Night"
        fan_speed = _int(s["fan_speed"])
        lines.append(f"  Fan: {fan_mode}, speed {fan_speed}%")

        # Filter
        filter_pct = _int(s["filter_usage_percentage"])
        if filter_pct is not None:
            lines.append(f"  Filter: {filter_pct}% remaining")

        # Settings
        settings_parts = []
        brightness = _int(s.get("brightness"))
        if brightness is not None:
            settings_parts.append(f"LED: {'off' if brightness == 0 else brightness}")
        if s.get("child_lock"):
            settings_parts.append("Child Lock: on")
        if s.get("germ_shield"):
            settings_parts.append("Germ Shield: on")
        if settings_parts:
            lines.append(f"  {', '.join(settings_parts)}")

        lines.append("")

    return "\n".join(lines).rstrip()
