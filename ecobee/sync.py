import argparse
import sys
from pathlib import Path

from pyecobee.errors import InvalidTokenError

from ecobee import auth, schedule

DEFAULT_SCHEDULE_PATH = Path(__file__).parent / "schedule.yaml"


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

    subparsers.choices["auth"].set_defaults(func=cmd_auth)
    subparsers.choices["list"].set_defaults(func=cmd_list)
    subparsers.choices["sync"].set_defaults(func=cmd_sync)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
