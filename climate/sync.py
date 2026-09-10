import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml
# InvalidTokenError means the OAuth tokens have expired beyond what auto-refresh
# can fix. The only recovery is re-running the PIN auth flow (just climate-auth).
from pyecobee.errors import InvalidTokenError

from climate.ecobee import auth, comforts, history, schedule, status
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
    from climate.ambient.client import load_weather_config
    from climate.ecobee.comfort_mode import resolve_schedule_array
    from climate import runlog

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

        try:
            mode, _ = _resolve_mode_for_push(
                program, getattr(args, "mode", None), load_weather_config(args.weather),
                runlog.get_data_dir(),
            )
        except RuntimeError as e:
            print(f"  Error: {e}")
            any_error = True
            continue
        schedule_array = resolve_schedule_array(schedule_array, mode)

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
    from climate.ambient.client import load_weather_config
    from climate.ecobee.comfort_mode import resolve_schedule_array
    from climate import runlog

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

        try:
            mode, _ = _resolve_mode_for_push(
                program, getattr(args, "mode", None), load_weather_config(args.weather),
                runlog.get_data_dir(),
            )
        except RuntimeError as e:
            print(f"  Error: {e}")
            any_mismatch = True
            continue
        local_array = resolve_schedule_array(local_array, mode)

        remote_array = program["schedule"]
        diffs = schedule.diff_schedules(local_array, remote_array, program)
        if diffs:
            print(f"  MISMATCH: {len(diffs)} slot(s) differ:")
            for line in diffs:
                print(line)
            any_mismatch = True
        else:
            print(f"  OK: remote matches schedule.yaml")

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


def cmd_history(args) -> None:
    ecobee = auth.make_ecobee()

    registry = load_thermostats(args.thermostats)
    managed = get_managed_thermostats(registry)
    if args.thermostat:
        managed = [(n, tid) for n, tid in managed if n == args.thermostat]
        if not managed:
            print(f"No managed thermostat named '{args.thermostat}'.")
            sys.exit(1)

    # A valid access token is needed for the report GET; get_thermostats()
    # triggers pyecobee's refresh-if-expired, same as cmd_status.
    if not ecobee.get_thermostats():
        print("Failed to authenticate with Ecobee.")
        sys.exit(1)
    token = ecobee.access_token

    end = date.today()
    start = end - timedelta(days=args.days - 1)

    if args.raw or args.json:
        granularity = "raw"
    elif args.days > 1:
        granularity = "daily"
    else:
        granularity = "hourly"

    json_out = []
    blocks = []
    for name, thermostat_id in managed:
        report = history.fetch_runtime_report(
            token, thermostat_id, start.isoformat(), end.isoformat()
        )
        series_list = history.parse_sensor_series(report)

        if args.json:
            json_out.append({"thermostat": name, "sensors": series_list})
        elif args.raw:
            blocks.append(history.format_raw(name, series_list))
        elif granularity == "daily":
            summaries = [history.summarize_daily(s) for s in series_list]
            blocks.append(history.format_history(name, summaries, "daily"))
        else:
            summaries = [history.summarize_hourly(s) for s in series_list]
            blocks.append(history.format_history(name, summaries, "hourly"))

    if args.json:
        import json as _json
        print(_json.dumps(json_out, indent=2, default=str))
    else:
        print("\n\n".join(blocks))


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


def cmd_locations(args) -> None:
    from picklehome.locations import resolve_locations

    try:
        locations = resolve_locations(args.location)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    print(f"{len(locations)} location(s) configured:\n")
    for loc in locations:
        macs = ", ".join(loc.station_macs) if loc.station_macs else "(none)"
        print(f"  {loc.slug}  {loc.label}")
        print(f"      coords:   ({loc.lat:.4f}, {loc.lon:.4f})")
        print(f"      stations: {macs}")
        print(f"      comfort:  {'managed (comfort-mode recommendation)' if loc.comfort_mode else 'weather-only'}")


def _discover_at(loc, radius: float) -> None:
    """Discover and print nearby outdoor stations for one location."""
    from climate.ambient.client import discover_stations_sync

    print(f"Searching within {radius} mile(s) of ({loc.lat:.4f}, {loc.lon:.4f})...")
    try:
        stations = discover_stations_sync(loc.lat, loc.lon, radius_miles=radius)
    except RuntimeError as e:
        print(f"Discovery failed: {e}")
        return

    if not stations:
        print("No outdoor stations found. Try --radius 1 or larger.")
        return

    temps = [s.get("lastData", {}).get("tempf") for s in stations if s.get("lastData", {}).get("tempf") is not None]
    median_temp = sorted(temps)[len(temps) // 2] if temps else None

    print(f"Found {len(stations)} outdoor station(s):\n")
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


def cmd_weather_discover(args) -> None:
    from picklehome.locations import resolve_locations

    try:
        locations = resolve_locations(args.location)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    multi = len(locations) > 1
    for loc in locations:
        if multi:
            print(f"\n=== {loc.label} ===")
        _discover_at(loc, args.radius)

    print("\nStore chosen MACs on the location's 1Password item (station_macs field), "
          "then run 'just dotenv'. Legacy single-home setups: set AMBIENT_STATION_MACS in .env.")


def cmd_weather(args) -> None:
    from climate.ambient.client import load_weather_config, get_outdoor_temp_from_stations
    from picklehome.locations import resolve_locations

    # Thresholds are location-agnostic; stations now come per-location.
    config = load_weather_config(args.weather)
    thresholds = config.get("thresholds", {})
    heat_below = thresholds.get("heat_below", 60)
    cool_above = thresholds.get("cool_above", 65)

    try:
        locations = resolve_locations(args.location)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    multi = len(locations) > 1
    any_error = False
    for loc in locations:
        if multi:
            print(f"\n=== {loc.label} ===")

        if not loc.station_macs:
            print("No stations configured for this location. Run "
                  "'just climate-weather-discover', then add station_macs in 1Password.")
            any_error = True
            continue

        result = get_outdoor_temp_from_stations(loc.station_macs)
        if result is None:
            print("Could not read a fresh, plausible outdoor temp from any configured station.")
            any_error = True
            continue

        mac, temp, age_minutes = result
        age_str = f"{age_minutes:.0f} min old"
        print(f"Outdoor temp: {temp}°F  ({age_str}, {mac})")

        # The comfort-mode line is an Ecobee-specific (smart1/smart2) recommendation,
        # only meaningful for a location whose thermostat this tooling manages.
        if not loc.comfort_mode:
            continue

        if temp < heat_below:
            mode = "heat  → Comfort Heat (smart2)"
        elif temp > cool_above:
            mode = "cool  → Comfort Cool (smart1)"
        else:
            mode = f"neutral  (between {heat_below}°F–{cool_above}°F, no change recommended)"
        print(f"Comfort mode: {mode}")

    if any_error:
        sys.exit(1)


def _resolve_mode_for_push(program, explicit_mode, weather_config, data_dir):
    """Pick the mode to resolve `comfort` against. Returns (mode, reasoning).

    Order: an explicit --mode wins; otherwise preserve whatever the thermostat
    is already running, so a structural sync (moving a transition time) does not
    accidentally flip the season; otherwise fall back to the rolling window.
    Never defaults -- an undeterminable mode raises.
    """
    from climate.ecobee.comfort_mode import decide_mode, detect_live_mode
    from climate import runlog

    if explicit_mode:
        return explicit_mode, {"reason": "explicit_mode"}

    live = detect_live_mode(program)
    if live:
        return live, {"reason": "preserved_live_mode"}

    thresholds = weather_config.get("thresholds", {})
    temps = runlog.read_recent_outdoor_temps(data_dir)
    decided, info = decide_mode(
        temps,
        thresholds.get("heat_below", 60),
        thresholds.get("cool_above", 65),
    )
    if decided:
        return decided, info
    raise RuntimeError(
        "Cannot determine the comfort mode: the live program uses neither "
        "smart1 nor smart2 (or uses both), and the outdoor window was "
        f"inconclusive ({info}). Re-run with --mode heat|cool."
    )


def cmd_comfort_switch(args) -> None:
    from climate.ambient.client import load_weather_config, get_configured_macs, get_outdoor_temp_from_stations
    from climate.ecobee.comfort_mode import decide_mode, resolve_schedule_array
    from climate import runlog

    mode = args.mode
    outdoor_temp = None
    hysteresis = False
    decision_info = None
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
        # The instantaneous reading is still fetched and logged: it is no longer
        # what we decide from, but it is what future 24h windows are built out
        # of. Do not remove this alongside the unconditional push.
        thresholds = config.get("thresholds", {})
        temps = runlog.read_recent_outdoor_temps(data_dir)
        decided, decision_info = decide_mode(
            temps, thresholds.get("heat_below", 60), thresholds.get("cool_above", 65)
        )
        if decided is None:
            print(f"No change: {decision_info}")
            hysteresis = True
        else:
            mode = decided
            print(f"24h mean {decision_info['mean']}°F "
                  f"({decision_info['samples']} samples) → {mode}")

    # Check last-state for no-op
    last_state = runlog.read_last_state(data_dir)
    previous_mode = last_state["mode"] if last_state else None

    # Always fetch thermostat status for logging
    ecobee = auth.make_ecobee()
    registry = load_thermostats(args.thermostats)
    managed = get_managed_thermostats(registry)
    managed_ids = {tid for _, tid in managed}

    # This is the first network call in the function. pyecobee propagates
    # InvalidTokenError from it directly (it does not return False), so it
    # must be guarded here rather than relying on a later call to catch it.
    try:
        success = ecobee.get_thermostats()
    except InvalidTokenError:
        print("Tokens invalid. Re-run 'just climate-auth'.")
        sys.exit(1)
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
        # --dry-run means zero persistent writes, full stop -- including here.
        # This path used to write unconditionally even under --dry-run, which
        # would inject a sample into the very rolling window decide_mode reads
        # and mutate last-state.json during what's supposed to be a preview.
        if args.dry_run:
            print("[dry run] Would record hysteresis no-change. No run-log or last-state written.")
            return

        log_entry = {
            "timestamp": runlog.now_iso(),
            "outdoor_temp_f": outdoor_temp,
            "decision": "no_change",
            "reason": "hysteresis",
            "decision_info": decision_info,
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

    schedule_data = schedule.load_schedule(args.schedule)
    try:
        entries = list(
            schedule.iter_thermostat_entries(schedule_data, registry, None)
        )
    except ValueError as e:
        print(f"Error in schedule.yaml: {e}")
        sys.exit(1)

    # The timer only ever acts on managed:true thermostats. schedule.yaml has
    # no managed filter of its own (cmd_sync/cmd_validate intentionally act on
    # whatever it lists, since those are explicit user-invoked commands), so
    # without this intersection an entry like a `managed: false` property
    # accidentally added to schedule.yaml would get pushed to and resumed by
    # the unattended timer. Filtering here keeps the push loop and the
    # --clear-holds loop (which already walks `managed`) operating on the
    # same set.
    entries = [
        (name, thermostat_id, schedule_dict)
        for name, thermostat_id, schedule_dict in entries
        if thermostat_id in managed_ids
    ]

    pushed = []
    any_error = False
    for name, thermostat_id, schedule_dict in entries:
        # Mirrors cmd_sync's handling of this same call: InvalidTokenError is
        # global (the credentials are dead for every thermostat, so stop now
        # rather than repeating the same failure per thermostat), while
        # LookupError/RuntimeError are per-thermostat -- one zone being
        # unreachable or missing from the account should not stop the other
        # zone from being corrected.
        try:
            program = schedule.get_current_program(ecobee, thermostat_id)
        except InvalidTokenError:
            print("Tokens invalid. Re-run 'just climate-auth'.")
            sys.exit(1)
        except LookupError as e:
            print(f"  [{name}] Error: {e}")
            any_error = True
            continue
        except RuntimeError as e:
            print(f"  [{name}] Error: {e}")
            any_error = True
            continue

        try:
            schedule.validate_climate_refs(schedule_dict, program)
        except ValueError as e:
            print(f"  [{name}] Error: {e}")
            any_error = True
            continue

        desired = resolve_schedule_array(
            schedule.build_schedule_array(schedule_dict), mode
        )
        diffs = schedule.diff_schedules(desired, program["schedule"], program)
        if not diffs:
            print(f"  [{name}] Already correct, nothing to push.")
            continue
        if args.dry_run:
            print(f"  [{name}] Would push {len(diffs)} slot change(s).")
            continue

        # Mirrors cmd_sync's handling of this same call (RuntimeError on a
        # null response; InvalidTokenError propagates from the underlying
        # request). A transient Ecobee failure on one thermostat must not
        # abort the whole run -- the other thermostat still needs a chance to
        # converge, and the run log / last-state write below still needs to
        # happen for whatever did succeed.
        try:
            schedule.push_schedule(ecobee, thermostat_id, desired, program["climates"])
        except InvalidTokenError:
            print("Tokens invalid. Re-run 'just climate-auth'.")
            sys.exit(1)
        except RuntimeError as e:
            print(f"  [{name}] Error: {e}")
            any_error = True
            continue

        print(f"  [{name}] Pushed {len(diffs)} slot change(s).")
        pushed.append((name, thermostat_id))

    # Resume only where we actually changed something and no one is holding.
    # An active hold is a deliberate human override and is never cleared here.
    # Build a hold-status lookup so we can decide per-thermostat whether to
    # resume. Ecobee API returns title-cased names ("Upstairs") but
    # thermostats.yaml uses lowercase ("upstairs"), normalize to lowercase
    # for the lookup.
    hold_by_name = {s["name"].lower(): s.get("hold") for s in thermostat_statuses}
    if args.clear_holds:
        for name, thermostat_id in managed:
            if args.dry_run:
                # --dry-run means no writes, full stop -- clearing a hold for
                # real here would violate that even though --clear-holds was
                # also passed. See hvac-spec.md: an active hold is a deliberate
                # human override and is only ever cleared with explicit intent.
                print(f"  [{name}] Would clear active holds")
                continue
            # Mirrors cmd_sync's push_schedule handling: a transient failure
            # on one thermostat must not abort clearing holds on the other.
            try:
                schedule.resume_program(ecobee, thermostat_id)
            except InvalidTokenError:
                print("Tokens invalid. Re-run 'just climate-auth'.")
                sys.exit(1)
            except RuntimeError as e:
                print(f"  [{name}] Warning: failed to clear holds: {e}")
                any_error = True
                continue
            print(f"  [{name}] Cleared active holds")
            holds_cleared = True
    else:
        for name, thermostat_id in pushed:
            # "unknown" (not "no hold") is the fail-closed default: the
            # lookup keys come from the Ecobee device name while `pushed`
            # names come from schedule.yaml, aligned only by lowercase
            # convention -- renaming a thermostat in the app breaks the
            # match. Treating "not found in the status snapshot" the same as
            # "confirmed no hold" would resume (and thus clear) a real hold
            # on a silent lookup miss. Only an explicit `None` clears it.
            if hold_by_name.get(name.lower(), "unknown") is None:
                try:
                    schedule.resume_program(ecobee, thermostat_id)
                except InvalidTokenError:
                    print("Tokens invalid. Re-run 'just climate-auth'.")
                    sys.exit(1)
                except RuntimeError as e:
                    print(f"  [{name}] Warning: failed to resume program: {e}")
                    any_error = True
                    continue
                print(f"  [{name}] Resumed program so the change applies now")

    # hvacMode is deliberately NOT written here. A person setting Off or
    # heat-only outranks the automation; see climate/spec/hvac-spec.md.
    switched = bool(pushed)

    # --dry-run means zero persistent writes, full stop. The push/resume
    # loops above already no-op their real API calls under --dry-run; this is
    # the same rule applied to the run log and last-state file so a preview
    # run can never inject a sample into decide_mode's rolling window or
    # mutate last-state.json.
    if args.dry_run:
        print("[dry run] No run-log or last-state written.")
    else:
        log_entry = {
            "timestamp": runlog.now_iso(),
            "outdoor_temp_f": outdoor_temp,
            "decision": mode,
            "decision_info": decision_info,
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

    if any_error:
        sys.exit(1)


def cmd_air_quality(args) -> None:
    import asyncio
    from climate.outdoor_air.client import AirQualityError, format_air_quality
    from climate.outdoor_air.pollen import PollenError, format_pollen, get_api_key
    from climate.outdoor_air import client as aq_client
    from climate.outdoor_air import pollen as pollen_client
    from picklehome.locations import resolve_locations

    try:
        locations = resolve_locations(args.location)
    except RuntimeError as e:
        print(e)
        sys.exit(1)

    # Check for pollen API key once before kicking off fetches
    try:
        api_key = get_api_key()
    except PollenError as e:
        api_key = None
        pollen_warning = str(e)

    async def fetch_all(lat: float, lon: float):
        tasks = [aq_client._fetch(lat, lon)]
        if api_key:
            tasks.append(pollen_client._fetch(lat, lon, api_key))
        return await asyncio.gather(*tasks, return_exceptions=True)

    multi = len(locations) > 1
    any_error = False
    for loc in locations:
        if multi:
            print(f"\n=== {loc.label} ===")

        results = asyncio.run(fetch_all(loc.lat, loc.lon))
        aq_result = results[0]
        pollen_result = results[1] if api_key else None

        if isinstance(aq_result, AirQualityError):
            print(f"Air quality unavailable: {aq_result}", file=sys.stderr)
            any_error = True
        elif isinstance(aq_result, Exception):
            print(f"Unexpected error fetching air quality: {aq_result}", file=sys.stderr)
            any_error = True
        else:
            print(format_air_quality(aq_result))

        if api_key is None:
            print(f"\n(pollen skipped: {pollen_warning})")
        elif isinstance(pollen_result, PollenError):
            print(f"\nPollen unavailable: {pollen_result}", file=sys.stderr)
        elif isinstance(pollen_result, Exception):
            print(f"\nUnexpected error fetching pollen: {pollen_result}", file=sys.stderr)
        else:
            print()
            print(format_pollen(pollen_result))

    if any_error:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Climate automation: Ecobee schedule, comfort, and status sync")
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
    sync_parser.add_argument(
        "--mode",
        choices=["heat", "cool"],
        default=None,
        help="Force the seasonal comfort mode instead of preserving/deciding it",
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
    validate_parser.add_argument(
        "--mode",
        choices=["heat", "cool"],
        default=None,
        help="Force the seasonal comfort mode instead of preserving/deciding it",
    )

    # NOTE: loop variable deliberately not named `parser` -- this function's
    # top-level ArgumentParser is already bound to that name, and `for`
    # loop variables in Python leak into the enclosing scope, so reusing it
    # here would silently rebind `parser` to `validate_parser` for the rest
    # of main() (breaking parser.parse_args()/parser.print_help() below).
    for p in (sync_parser, validate_parser):
        p.add_argument(
            "--weather", type=Path, default=DEFAULT_WEATHER_PATH,
            help="Path to weather.yaml (thresholds for the seasonal decision)",
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

    history_parser = subparsers.add_parser(
        "history", help="Show room-sensor temperature and occupancy history"
    )
    history_parser.add_argument(
        "--thermostat",
        metavar="NAME",
        default=None,
        help="Only this managed thermostat (default: all)",
    )
    history_parser.add_argument(
        "--days",
        type=int,
        default=1,
        metavar="N",
        help="Number of calendar days back to include, ending today (default: 1)",
    )
    history_parser.add_argument(
        "--raw",
        action="store_true",
        help="Print every 5-minute interval instead of summaries",
    )
    history_parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON (full granularity)",
    )
    history_parser.add_argument(
        "--thermostats",
        type=Path,
        default=DEFAULT_THERMOSTATS_PATH,
        metavar="PATH",
        help="Path to thermostats YAML (default: climate/config/thermostats.yaml)",
    )

    subparsers.add_parser(
        "locations", help="List configured locations (main house, beachhouse, ...)"
    ).add_argument(
        "--location",
        metavar="SLUG",
        default=None,
        help="Limit to one location by slug (default: all)",
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
    discover_parser.add_argument(
        "--location",
        metavar="SLUG",
        default=None,
        help="Limit to one location by slug (default: all configured locations)",
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
    weather_parser.add_argument(
        "--location",
        metavar="SLUG",
        default=None,
        help="Limit to one location by slug (default: all configured locations)",
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

    air_quality_parser = subparsers.add_parser(
        "air-quality", help="Show current outdoor air quality, UV index, and pollen"
    )
    air_quality_parser.add_argument(
        "--location",
        metavar="SLUG",
        default=None,
        help="Limit to one location by slug (default: all configured locations)",
    )

    subparsers.choices["auth"].set_defaults(func=cmd_auth)
    subparsers.choices["list"].set_defaults(func=cmd_list)
    subparsers.choices["sync"].set_defaults(func=cmd_sync)
    subparsers.choices["validate"].set_defaults(func=cmd_validate)
    subparsers.choices["status"].set_defaults(func=cmd_status)
    subparsers.choices["history"].set_defaults(func=cmd_history)
    subparsers.choices["capture-comforts"].set_defaults(func=cmd_comforts_capture)
    subparsers.choices["sync-comforts"].set_defaults(func=cmd_comforts_sync)
    subparsers.choices["locations"].set_defaults(func=cmd_locations)
    subparsers.choices["discover-stations"].set_defaults(func=cmd_weather_discover)
    subparsers.choices["weather"].set_defaults(func=cmd_weather)
    subparsers.choices["comfort-switch"].set_defaults(func=cmd_comfort_switch)
    subparsers.choices["air-quality"].set_defaults(func=cmd_air_quality)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
