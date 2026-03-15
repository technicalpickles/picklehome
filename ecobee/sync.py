import argparse
import sys
from pathlib import Path

from pyecobee.errors import InvalidTokenError

from ecobee import auth, schedule

DEFAULT_SCHEDULE_PATH = Path(__file__).parent / "schedule.yaml"


def cmd_auth(args) -> None:
    api_key = auth.get_api_key()
    auth.pin_auth_flow(api_key)


def cmd_sync(args) -> None:
    ecobee = auth.make_ecobee()
    thermostat_id = auth.get_thermostat_id()

    schedule_data = schedule.load_schedule(args.schedule)
    schedule_dict = schedule_data["schedule"]

    try:
        schedule_array = schedule.build_schedule_array(schedule_dict)
    except ValueError as e:
        print(f"Error in schedule.yaml: {e}")
        sys.exit(1)

    # GET current program (needed for climate validation + preserving temperatures)
    # Note: climate validation is intentionally deferred until after GET,
    # because validate_climate_refs requires the live climates list from the thermostat.
    # Time/format validation (build_schedule_array) runs offline first.
    try:
        program = schedule.get_current_program(ecobee, thermostat_id)
    except InvalidTokenError:
        print("Tokens invalid. Re-run 'just ecobee-auth'.")
        sys.exit(1)
    except LookupError as e:
        # Thermostat ID in Keychain not found on account — config error
        print(f"Error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        # Network / transport / unexpected API failure
        print(f"Error: {e}")
        sys.exit(2)

    try:
        schedule.validate_climate_refs(schedule_dict, program)
    except ValueError as e:
        print(f"Error in schedule.yaml: {e}")
        sys.exit(1)

    if args.dry_run:
        schedule.print_schedule_grid(schedule_array, program)
        print("Dry run complete. No changes pushed.")
        return

    try:
        schedule.push_schedule(ecobee, thermostat_id, schedule_array, program["climates"])
    except InvalidTokenError:
        print("Tokens invalid. Re-run 'just ecobee-auth'.")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(2)

    print("Schedule pushed successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ecobee schedule sync")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("auth", help="First-time PIN auth flow + thermostat discovery")

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

    # Wire up subcommand functions
    subparsers.choices["auth"].set_defaults(func=cmd_auth)
    subparsers.choices["sync"].set_defaults(func=cmd_sync)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
