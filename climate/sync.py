import argparse
import re
import sys
from pathlib import Path

import yaml
# InvalidTokenError means the OAuth tokens have expired beyond what auto-refresh
# can fix. The only recovery is re-running the PIN auth flow (just climate-auth).
from pyecobee.errors import InvalidTokenError

from climate.ecobee import auth, comforts, schedule, status
from climate.ecobee.thermostats import load_thermostats, get_managed_thermostats
from climate.ambient.client import DEFAULT_WEATHER_PATH

DEFAULT_SCHEDULE_PATH = Path(__file__).parent / "config" / "schedule.yaml"
DEFAULT_COMFORTS_PATH = Path(__file__).parent / "config" / "comforts.yaml"
DEFAULT_THERMOSTATS_PATH = Path(__file__).parent / "config" / "thermostats.yaml"


def cmd_auth(args) -> None:
    api_key = auth.get_api_key()
    auth.pin_auth_flow(api_key)


def cmd_list(args) -> None:
    auth.list_thermostats()


def cmd_sync(args) -> None:
    ecobee = auth.make_ecobee()

    schedule_data = schedule.load_schedule(args.schedule)
    registry = load_thermostats(args.thermostats)

    try:
        entries = list(schedule.iter_thermostat_entries(schedule_data, registry, args.thermostat))
    except ValueError as e:
        print(f"Error in schedule.yaml: {e}")
        sys.exit(1)

    if not entries:
        if args.thermostat:
            print(f"No thermostat named '{args.thermostat}' found in schedule.yaml.")
        else:
            print("No thermostats configured in schedule.yaml.")
        sys.exit(1)

    any_error = False

    for name, thermostat_id, schedule_dict in entries:
        print(f"\n[{name}]")

        # Offline validation first (no API call needed)
        try:
            schedule_array = schedule.build_schedule_array(schedule_dict)
        except ValueError as e:
            print(f"  Error: {e}")
            any_error = True
            continue

        # GET current program (needed for climate validation + preserving temperatures)
        # Note: climate validation is intentionally deferred until after GET,
        # because validate_climate_refs requires the live climates list from the thermostat.
        try:
            program = schedule.get_current_program(ecobee, thermostat_id)
        except InvalidTokenError:
            print("Tokens invalid. Re-run 'just climate-auth'.")
            sys.exit(1)
        except LookupError as e:
            print(f"  Error: {e}")
            any_error = True
            continue
        except RuntimeError as e:
            print(f"  Error: {e}")
            any_error = True
            continue

        try:
            schedule.validate_climate_refs(schedule_dict, program)
        except ValueError as e:
            print(f"  Error: {e}")
            any_error = True
            continue

        if args.dry_run:
            schedule.print_schedule_grid(schedule_array, program, name=name)
            print(f"  Dry run complete. No changes pushed.")
            continue

        try:
            schedule.push_schedule(ecobee, thermostat_id, schedule_array, program["climates"])
        except InvalidTokenError:
            print("Tokens invalid. Re-run 'just climate-auth'.")
            sys.exit(1)
        except RuntimeError as e:
            print(f"  Error: {e}")
            any_error = True
            continue

        print(f"  Schedule pushed successfully.")

    if any_error:
        sys.exit(1)


def cmd_validate(args) -> None:
    ecobee = auth.make_ecobee()

    schedule_data = schedule.load_schedule(args.schedule)
    registry = load_thermostats(args.thermostats)

    try:
        entries = list(schedule.iter_thermostat_entries(schedule_data, registry, args.thermostat))
    except ValueError as e:
        print(f"Error in schedule.yaml: {e}")
        sys.exit(1)

    if not entries:
        if args.thermostat:
            print(f"No thermostat named '{args.thermostat}' found in schedule.yaml.")
        else:
            print("No thermostats configured in schedule.yaml.")
        sys.exit(1)

    any_mismatch = False

    for name, thermostat_id, schedule_dict in entries:
        print(f"\n[{name}]")

        try:
            local_array = schedule.build_schedule_array(schedule_dict)
        except ValueError as e:
            print(f"  Error building local schedule: {e}")
            any_mismatch = True
            continue

        try:
            program = schedule.get_current_program(ecobee, thermostat_id)
        except InvalidTokenError:
            print("Tokens invalid. Re-run 'just climate-auth'.")
            sys.exit(1)
        except (LookupError, RuntimeError) as e:
            print(f"  Error: {e}")
            any_mismatch = True
            continue

        remote_array = program["schedule"]
        diffs = schedule.diff_schedules(local_array, remote_array, program)
        if diffs:
            print(f"  MISMATCH — {len(diffs)} slot(s) differ:")
            for line in diffs:
                print(line)
            any_mismatch = True
        else:
            print(f"  OK — remote matches schedule.yaml")

    if any_mismatch:
        sys.exit(1)


def cmd_status(args) -> None:
    ecobee = auth.make_ecobee()

    registry = load_thermostats(args.thermostats)
    managed = get_managed_thermostats(registry)
    managed_ids = {thermostat_id for _, thermostat_id in managed}

    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        print("Failed to fetch thermostat data from Ecobee.")
        sys.exit(1)

    statuses = [
        status.extract_thermostat_status(t)
        for t in ecobee.thermostats
        if t["identifier"] in managed_ids
    ]

    if args.json:
        import json
        print(json.dumps({"thermostats": statuses}, indent=2, default=str))
    else:
        print(status.format_status(statuses))


def cmd_comforts_capture(args) -> None:
    ecobee = auth.make_ecobee()

    print("Fetching comfort settings from Ecobee...")
    try:
        thermostat_data = comforts.capture_all_thermostats(ecobee)
    except InvalidTokenError:
        print("Tokens invalid. Re-run 'just climate-auth'.")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    out: dict = {"thermostats": {}}
    for api_name, thermostat_id, climates in thermostat_data:
        key = api_name.lower().replace(" ", "_")
        out["thermostats"][key] = {
            "climates": comforts.climates_to_yaml_dict(climates),
        }

    header = (
        "# climate/config/comforts.yaml\n"
        "# Temperature setpoints (°F) for each comfort mode (climate).\n"
        "# Thermostat IDs are in climate/config/thermostats.yaml.\n"
        "# Generated by 'just climate-comforts-capture'. Edit as desired.\n"
        "# Run 'just climate-comforts-sync' to push changes to thermostats.\n\n"
    )
    path = args.comforts
    with open(path, "w") as f:
        f.write(header)
        yaml.dump(out, f, default_flow_style=False, sort_keys=False)

    print(f"Comfort settings written to {path}\n")
    for api_name, _, climates in thermostat_data:
        print(f"[{api_name}]")
        for c in climates:
            ref = c["climateRef"]
            cool = c["coolTemp"] // 10
            heat = c["heatTemp"] // 10
            label = f"{ref} ({c['name']})" if c.get("owner") == "user" else ref
            print(f"  {label}: cool={cool}°F  heat={heat}°F")


def cmd_comforts_sync(args) -> None:
    ecobee = auth.make_ecobee()

    comforts_data = comforts.load_comforts(args.comforts)
    registry = load_thermostats(args.thermostats)

    try:
        entries = list(comforts.iter_thermostat_entries(comforts_data, registry, args.thermostat))
    except ValueError as e:
        print(f"Error in comforts.yaml: {e}")
        sys.exit(1)

    if not entries:
        if args.thermostat:
            print(f"No thermostat named '{args.thermostat}' found in comforts.yaml.")
        else:
            print("No thermostats configured in comforts.yaml.")
        sys.exit(1)

    any_error = False

    for name, thermostat_id, climates_dict in entries:
        print(f"\n[{name}]")

        try:
            program = schedule.get_current_program(ecobee, thermostat_id)
        except InvalidTokenError:
            print("Tokens invalid. Re-run 'just climate-auth'.")
            sys.exit(1)
        except (LookupError, RuntimeError) as e:
            print(f"  Error: {e}")
            any_error = True
            continue

        try:
            updated_climates = comforts.apply_comforts_to_climates(
                climates_dict, program["climates"]
            )
        except ValueError as e:
            print(f"  Error: {e}")
            any_error = True
            continue

        if args.dry_run:
            comforts.print_comforts(climates_dict, program["climates"], name=name)
            print(f"  Dry run complete. No changes pushed.")
            continue

        try:
            comforts.push_comforts(ecobee, thermostat_id, updated_climates, program["schedule"])
        except InvalidTokenError:
            print("Tokens invalid. Re-run 'just climate-auth'.")
            sys.exit(1)
        except RuntimeError as e:
            print(f"  Error: {e}")
            any_error = True
            continue

        print(f"  Comfort settings pushed successfully.")

    if any_error:
        sys.exit(1)


def cmd_weather_discover(args) -> None:
    import os
    from climate.ambient.client import discover_stations_sync

    lat_str = os.environ.get("HOME_LAT", "")
    lon_str = os.environ.get("HOME_LON", "")
    if not lat_str or not lon_str:
        print("HOME_LAT and HOME_LON must be set. Run 'just dotenv'.")
        sys.exit(1)
    try:
        lat, lon = float(lat_str), float(lon_str)
    except ValueError:
        print(f"HOME_LAT/HOME_LON are not valid floats: {lat_str!r}, {lon_str!r}")
        sys.exit(1)

    print(f"Searching within {args.radius} mile(s) of ({lat:.4f}, {lon:.4f})...")
    try:
        stations = discover_stations_sync(lat, lon, radius_miles=args.radius)
    except RuntimeError as e:
        print(f"Discovery failed: {e}")
        sys.exit(1)

    if not stations:
        print("No outdoor stations found. Try --radius 1 or larger.")
        sys.exit(1)

    from climate.ambient.client import is_temp_plausible
    temps = [s.get("lastData", {}).get("tempf") for s in stations if s.get("lastData", {}).get("tempf") is not None]
    median_temp = sorted(temps)[len(temps) // 2] if temps else None

    print(f"\nFound {len(stations)} outdoor station(s):\n")
    for s in stations:
        mac = s.get("macAddress", "unknown")
        name = (s.get("info", {}).get("name")
                or s.get("info", {}).get("coords", {}).get("location", "unnamed"))
        temp = s.get("lastData", {}).get("tempf")
        if temp is None:
            temp_str = "no temp"
        elif median_temp is not None and abs(temp - median_temp) > 15:
            temp_str = f"{temp}°F  ⚠ outlier"
        else:
            temp_str = f"{temp}°F"
        print(f"  {mac}  {name}  ({temp_str})")
    print("\nStore chosen MACs in 1Password → AMBIENT_STATION_MACS in .env (see .env.template).")


def cmd_weather(args) -> None:
    from climate.ambient.client import load_weather_config, get_configured_macs, get_outdoor_temp_from_stations

    config = load_weather_config(args.weather)
    macs = get_configured_macs(config)

    if not macs:
        print("No stations configured. Run 'just climate-weather-discover', then set AMBIENT_STATION_MACS in .env.")
        sys.exit(1)

    result = get_outdoor_temp_from_stations(macs)
    if result is None:
        print("Could not read a fresh, plausible outdoor temp from any configured station.")
        sys.exit(1)

    mac, temp, age_minutes = result
    age_str = f"{age_minutes:.0f} min old"

    thresholds = config.get("thresholds", {})
    heat_below = thresholds.get("heat_below", 60)
    cool_above = thresholds.get("cool_above", 65)

    if temp < heat_below:
        mode = f"heat  → Comfort Heat (smart2)"
    elif temp > cool_above:
        mode = f"cool  → Comfort Cool (smart1)"
    else:
        mode = f"neutral  (between {heat_below}°F–{cool_above}°F, no change recommended)"

    print(f"Outdoor temp: {temp}°F  ({age_str}, {mac})")
    print(f"Comfort mode: {mode}")


def _apply_comfort_mode(schedule_text: str, mode: str) -> str:
    """Swap smart1↔smart2 in YAML `climate:` value positions only (not comments).

    mode='heat' → smart1 → smart2 (Comfort Heat)
    mode='cool' → smart2 → smart1 (Comfort Cool)
    """
    if mode == "heat":
        return re.sub(r'(climate:\s*)smart1\b', r'\1smart2', schedule_text)
    elif mode == "cool":
        return re.sub(r'(climate:\s*)smart2\b', r'\1smart1', schedule_text)
    else:
        raise ValueError(f"Unknown mode: {mode!r}. Use 'heat' or 'cool'.")


def cmd_comfort_switch(args) -> None:
    from climate.ambient.client import load_weather_config, get_configured_macs, get_outdoor_temp_from_stations
    from climate import runlog

    mode = args.mode
    outdoor_temp = None
    hysteresis = False
    data_dir = runlog.get_data_dir()

    if mode == "auto":
        config = load_weather_config(args.weather)
        macs = get_configured_macs(config)
        if not macs:
            print("No stations configured. Run 'just climate-weather-discover', then set AMBIENT_STATION_MACS in .env.")
            sys.exit(1)
        result = get_outdoor_temp_from_stations(macs)
        if result is None:
            print("Could not read outdoor temp from any configured station.")
            sys.exit(1)
        mac, outdoor_temp, age_minutes = result
        thresholds = config.get("thresholds", {})
        heat_below = thresholds.get("heat_below", 60)
        cool_above = thresholds.get("cool_above", 65)
        if outdoor_temp < heat_below:
            mode = "heat"
        elif outdoor_temp > cool_above:
            mode = "cool"
        else:
            hysteresis = True
            print(f"Outdoor temp {outdoor_temp}°F is in hysteresis band ({heat_below}-{cool_above}°F). No change.")

        if not hysteresis:
            print(f"Outdoor temp: {outdoor_temp}°F → switching to {mode}")

    # Check last-state for no-op
    last_state = runlog.read_last_state(data_dir)
    previous_mode = last_state["mode"] if last_state else None

    # Always fetch thermostat status for logging
    ecobee = auth.make_ecobee()
    registry = load_thermostats(args.thermostats)
    managed = get_managed_thermostats(registry)
    managed_ids = {tid for _, tid in managed}

    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        print("Failed to fetch thermostat data from Ecobee.")
        sys.exit(1)

    thermostat_statuses = [
        status.extract_thermostat_status(t)
        for t in ecobee.thermostats
        if t["identifier"] in managed_ids
    ]

    # Hysteresis: log and exit without changing anything
    if hysteresis:
        log_entry = {
            "timestamp": runlog.now_iso(),
            "outdoor_temp_f": outdoor_temp,
            "decision": "no_change",
            "reason": "hysteresis",
            "previous_mode": previous_mode,
            "switched": False,
            "holds_cleared": False,
            "skipped": True,
            "thermostats": thermostat_statuses,
        }
        runlog.append_run_log(data_dir, log_entry)

        state = {
            "timestamp": runlog.now_iso(),
            "mode": previous_mode or "unknown",
            "outdoor_temp_f": outdoor_temp,
            "thermostats": thermostat_statuses,
        }
        runlog.write_last_state(data_dir, state)
        return

    switched = False
    holds_cleared = False
    skipped = False

    if previous_mode == mode:
        print(f"Already in {mode} mode. Skipping schedule push.")
        skipped = True
    elif args.dry_run:
        schedule_path = args.schedule
        original = schedule_path.read_text()
        updated = _apply_comfort_mode(original, mode)
        if updated != original:
            print(f"[dry run] Would switch to {mode} comfort:")
            for i, (old, new) in enumerate(zip(original.splitlines(), updated.splitlines()), 1):
                if old != new:
                    print(f"  line {i}: {old.strip()!r} → {new.strip()!r}")
        else:
            print(f"Schedule already set to {mode} comfort.")
        if args.clear_holds:
            print(f"[dry run] Would clear active holds on all managed thermostats")
        print(f"[dry run] Would set HVAC mode to auto on all managed thermostats")
        return
    else:
        # Push schedule change
        schedule_path = args.schedule
        original = schedule_path.read_text()
        updated = _apply_comfort_mode(original, mode)

        if updated != original:
            schedule_path.write_text(updated)
            print(f"schedule.yaml updated to {mode} comfort. Syncing to Ecobee...")
            sync_args = argparse.Namespace(
                schedule=schedule_path,
                thermostats=args.thermostats,
                thermostat=None,
                dry_run=False,
            )
            try:
                cmd_sync(sync_args)
            except SystemExit as e:
                if e.code != 0:
                    print("Ecobee sync failed. Restoring schedule.yaml to original content.")
                    schedule_path.write_text(original)
                    raise
            switched = True
        else:
            print(f"Schedule already set to {mode} comfort.")

        if args.clear_holds:
            for name, thermostat_id in managed:
                try:
                    schedule.resume_program(ecobee, thermostat_id)
                    print(f"  [{name}] Cleared active holds")
                    holds_cleared = True
                except RuntimeError as e:
                    print(f"  [{name}] Warning: failed to clear holds: {e}")

        hvac_mode = "auto"
        for name, thermostat_id in managed:
            try:
                schedule.set_hvac_mode(ecobee, thermostat_id, hvac_mode)
                print(f"  [{name}] HVAC mode set to {hvac_mode}")
            except RuntimeError as e:
                print(f"  [{name}] Warning: failed to set HVAC mode: {e}")

    # Write run log and last-state
    log_entry = {
        "timestamp": runlog.now_iso(),
        "outdoor_temp_f": outdoor_temp,
        "decision": mode,
        "previous_mode": previous_mode,
        "switched": switched,
        "holds_cleared": holds_cleared,
        "skipped": skipped,
        "thermostats": thermostat_statuses,
    }
    runlog.append_run_log(data_dir, log_entry)

    state = {
        "timestamp": runlog.now_iso(),
        "mode": mode,
        "outdoor_temp_f": outdoor_temp,
        "thermostats": thermostat_statuses,
    }
    runlog.write_last_state(data_dir, state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Climate automation — Ecobee schedule, comfort, and status sync")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("auth", help="First-time PIN auth flow + thermostat discovery")
    subparsers.add_parser("list", help="List thermostats and climate refs on this account")

    sync_parser = subparsers.add_parser("sync", help="Push schedule.yaml to Ecobee")
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview expanded schedule without pushing",
    )
    sync_parser.add_argument(
        "--schedule",
        type=Path,
        default=DEFAULT_SCHEDULE_PATH,
        metavar="PATH",
        help="Path to schedule YAML (default: climate/config/schedule.yaml)",
    )
    sync_parser.add_argument(
        "--thermostats",
        type=Path,
        default=DEFAULT_THERMOSTATS_PATH,
        metavar="PATH",
        help="Path to thermostats YAML (default: climate/config/thermostats.yaml)",
    )
    sync_parser.add_argument(
        "--thermostat",
        metavar="NAME",
        default=None,
        help="Only sync the named thermostat (default: all)",
    )

    validate_parser = subparsers.add_parser(
        "validate", help="Compare schedule.yaml against the live schedule on Ecobee"
    )
    validate_parser.add_argument(
        "--schedule",
        type=Path,
        default=DEFAULT_SCHEDULE_PATH,
        metavar="PATH",
        help="Path to schedule YAML (default: climate/config/schedule.yaml)",
    )
    validate_parser.add_argument(
        "--thermostats",
        type=Path,
        default=DEFAULT_THERMOSTATS_PATH,
        metavar="PATH",
        help="Path to thermostats YAML (default: climate/config/thermostats.yaml)",
    )
    validate_parser.add_argument(
        "--thermostat",
        metavar="NAME",
        default=None,
        help="Only validate the named thermostat (default: all)",
    )

    capture_parser = subparsers.add_parser(
        "capture-comforts", help="Snapshot current comfort mode temps from Ecobee → comforts.yaml"
    )
    capture_parser.add_argument(
        "--comforts",
        type=Path,
        default=DEFAULT_COMFORTS_PATH,
        metavar="PATH",
        help="Path to write comforts YAML (default: climate/config/comforts.yaml)",
    )

    sync_comforts_parser = subparsers.add_parser(
        "sync-comforts", help="Push comforts.yaml setpoints to Ecobee"
    )
    sync_comforts_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview comfort changes without pushing",
    )
    sync_comforts_parser.add_argument(
        "--comforts",
        type=Path,
        default=DEFAULT_COMFORTS_PATH,
        metavar="PATH",
        help="Path to comforts YAML (default: climate/config/comforts.yaml)",
    )
    sync_comforts_parser.add_argument(
        "--thermostats",
        type=Path,
        default=DEFAULT_THERMOSTATS_PATH,
        metavar="PATH",
        help="Path to thermostats YAML (default: climate/config/thermostats.yaml)",
    )
    sync_comforts_parser.add_argument(
        "--thermostat",
        metavar="NAME",
        default=None,
        help="Only sync the named thermostat (default: all)",
    )

    status_parser = subparsers.add_parser("status", help="Show current thermostat state")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    status_parser.add_argument(
        "--thermostats",
        type=Path,
        default=DEFAULT_THERMOSTATS_PATH,
        metavar="PATH",
        help="Path to thermostats YAML (default: climate/config/thermostats.yaml)",
    )

    discover_parser = subparsers.add_parser(
        "discover-stations", help="List nearby outdoor Ambient Weather stations"
    )
    discover_parser.add_argument(
        "--radius",
        type=float,
        default=0.5,
        metavar="N",
        help="Search radius in miles (default: 0.5)",
    )

    weather_parser = subparsers.add_parser(
        "weather", help="Show current outdoor temp and comfort mode recommendation"
    )
    weather_parser.add_argument(
        "--weather",
        type=Path,
        default=DEFAULT_WEATHER_PATH,
        metavar="PATH",
        help="Path to weather YAML (default: climate/config/weather.yaml)",
    )

    comfort_switch_parser = subparsers.add_parser(
        "comfort-switch", help="Switch schedule comfort mode (heat|cool|auto)"
    )
    comfort_switch_parser.add_argument(
        "mode",
        choices=["heat", "cool", "auto"],
        help="Comfort mode to apply, or 'auto' to decide from outdoor temp",
    )
    comfort_switch_parser.add_argument(
        "--clear-holds",
        action="store_true",
        help="Clear any active temperature holds before switching",
    )
    comfort_switch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing or syncing",
    )
    comfort_switch_parser.add_argument(
        "--schedule",
        type=Path,
        default=DEFAULT_SCHEDULE_PATH,
        metavar="PATH",
        help="Path to schedule YAML (default: climate/config/schedule.yaml)",
    )
    comfort_switch_parser.add_argument(
        "--thermostats",
        type=Path,
        default=DEFAULT_THERMOSTATS_PATH,
        metavar="PATH",
        help="Path to thermostats YAML (default: climate/config/thermostats.yaml)",
    )
    comfort_switch_parser.add_argument(
        "--weather",
        type=Path,
        default=DEFAULT_WEATHER_PATH,
        metavar="PATH",
        help="Path to weather YAML (default: climate/config/weather.yaml)",
    )

    subparsers.choices["auth"].set_defaults(func=cmd_auth)
    subparsers.choices["list"].set_defaults(func=cmd_list)
    subparsers.choices["sync"].set_defaults(func=cmd_sync)
    subparsers.choices["validate"].set_defaults(func=cmd_validate)
    subparsers.choices["status"].set_defaults(func=cmd_status)
    subparsers.choices["capture-comforts"].set_defaults(func=cmd_comforts_capture)
    subparsers.choices["sync-comforts"].set_defaults(func=cmd_comforts_sync)
    subparsers.choices["discover-stations"].set_defaults(func=cmd_weather_discover)
    subparsers.choices["weather"].set_defaults(func=cmd_weather)
    subparsers.choices["comfort-switch"].set_defaults(func=cmd_comfort_switch)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
