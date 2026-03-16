import argparse
import sys
from pathlib import Path

import yaml
from pyecobee.errors import InvalidTokenError

from climate.ecobee import auth, comforts, schedule

DEFAULT_SCHEDULE_PATH = Path(__file__).parent / "config" / "schedule.yaml"
DEFAULT_COMFORTS_PATH = Path(__file__).parent / "config" / "comforts.yaml"


def cmd_auth(args) -> None:
    api_key = auth.get_api_key()
    auth.pin_auth_flow(api_key)


def cmd_list(args) -> None:
    auth.list_thermostats()


def cmd_sync(args) -> None:
    ecobee = auth.make_ecobee()

    schedule_data = schedule.load_schedule(args.schedule)

    try:
        entries = list(schedule.iter_thermostat_entries(schedule_data, args.thermostat))
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
            print("Tokens invalid. Re-run 'just ecobee-auth'.")
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
            print("Tokens invalid. Re-run 'just ecobee-auth'.")
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

    try:
        entries = list(schedule.iter_thermostat_entries(schedule_data, args.thermostat))
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
            print("Tokens invalid. Re-run 'just ecobee-auth'.")
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


def cmd_comforts_capture(args) -> None:
    ecobee = auth.make_ecobee()

    print("Fetching comfort settings from Ecobee...")
    try:
        thermostat_data = comforts.capture_all_thermostats(ecobee)
    except InvalidTokenError:
        print("Tokens invalid. Re-run 'just ecobee-auth'.")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    out: dict = {"thermostats": {}}
    for api_name, thermostat_id, climates in thermostat_data:
        key = api_name.lower().replace(" ", "_")
        out["thermostats"][key] = {
            "thermostat_id": thermostat_id,
            "climates": comforts.climates_to_yaml_dict(climates),
        }

    header = (
        "# ecobee/comforts.yaml\n"
        "# Temperature setpoints (°F) for each comfort mode (climate).\n"
        "# Generated by 'just ecobee-comforts-capture'. Edit as desired.\n"
        "# Run 'just ecobee-comforts-sync' to push changes to thermostats.\n\n"
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

    try:
        entries = list(comforts.iter_thermostat_entries(comforts_data, args.thermostat))
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
            print("Tokens invalid. Re-run 'just ecobee-auth'.")
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
            comforts.push_comforts(ecobee, thermostat_id, updated_climates)
        except InvalidTokenError:
            print("Tokens invalid. Re-run 'just ecobee-auth'.")
            sys.exit(1)
        except RuntimeError as e:
            print(f"  Error: {e}")
            any_error = True
            continue

        print(f"  Comfort settings pushed successfully.")

    if any_error:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ecobee schedule sync")
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
        help="Path to schedule YAML (default: ecobee/schedule.yaml)",
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
        help="Path to schedule YAML (default: ecobee/schedule.yaml)",
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
        help="Path to write comforts YAML (default: ecobee/comforts.yaml)",
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
        help="Path to comforts YAML (default: ecobee/comforts.yaml)",
    )
    sync_comforts_parser.add_argument(
        "--thermostat",
        metavar="NAME",
        default=None,
        help="Only sync the named thermostat (default: all)",
    )

    subparsers.choices["validate"].set_defaults(func=cmd_validate)
    subparsers.choices["auth"].set_defaults(func=cmd_auth)
    subparsers.choices["list"].set_defaults(func=cmd_list)
    subparsers.choices["sync"].set_defaults(func=cmd_sync)
    subparsers.choices["capture-comforts"].set_defaults(func=cmd_comforts_capture)
    subparsers.choices["sync-comforts"].set_defaults(func=cmd_comforts_sync)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
