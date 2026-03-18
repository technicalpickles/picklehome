# Code Review: Story 1.1 — Outdoor Temperature Comfort Mode

**Reviewer:** claude-opus-4-6 (superpowers:code-reviewer)
**Date:** 2026-03-17
**Status:** Changes Requested (2 important items)

## Acceptance Criteria Verification

| AC | Status | Notes |
|----|--------|-------|
| 1. `aioambient==2024.08.0`, `HOME_LAT`/`HOME_LON` | PASS | `pyproject.toml` + `.env.template` |
| 2. Concurrent fetch, timeout, error handling, plausibility, freshness | PASS | `client.py` — `asyncio.gather`, explicit `(RequestError, TimeoutError)` only |
| 3. `weather.yaml` with valid structure | PASS | Stations empty (requires live discover step) |
| 4. `just climate-weather-discover` exists | PASS | Justfile wired correctly |
| 5. `just climate-weather` prints temp, age, MAC, recommendation | PASS | All four fields output |
| 6. `just climate-comfort-switch` heat/cool/auto | PASS | Fully implemented with dry-run |
| 7. `_apply_comfort_mode` comment-safe regex + tests | PASS | 6 dedicated tests including comment preservation |
| 8. Sync failure triggers schedule.yaml rollback | PASS | Tested by `test_cmd_comfort_switch_sync_failure_rollback` |
| 9. Unit tests for all new functions | PARTIAL | `get_data_age_minutes` missing dedicated test |
| 10. `hvac-spec.md` updated | PARTIAL | Thresholds + seasonal switching added, but schedule tables inconsistent |

**Tests:** 43 passing (18 ambient client, 12 comfort-switch, 13 pre-existing ecobee). No regressions.

## Strengths

- **`client.py` architecture** — concurrent station fetch via `asyncio.gather`, plausibility guard (`is_temp_plausible`), freshness check (`is_data_fresh`), 3-tuple return type `(mac, temp, age_minutes)` is a clean design.
- **Exception discipline** — only `RequestError` and `asyncio.TimeoutError` caught. No bare `Exception`. Programming errors propagate as intended.
- **Comment-safe regex** — `_apply_comfort_mode` uses `(climate:\s*)smart1\b` to target only YAML value positions. Dedicated tests prove comments are untouched.
- **Rollback logic** — `cmd_comfort_switch` catches `SystemExit(non-zero)` after `cmd_sync` and restores original schedule content.
- **CLI structure** — follows existing `sync.py` subcommand pattern. All four `just` tasks properly wired.
- **Env guard** — `cmd_weather_discover` uses explicit `if not lat_str or not lon_str` checks, not the `or`-chained `sys.exit` anti-pattern from the original plan.

## Issues

### Important — Fix Before Committing

#### 1. `hvac-spec.md` schedule tables inconsistent with `schedule.yaml`

**What:** `schedule.yaml` now uses `smart2` (Comfort Heat) everywhere, but `hvac-spec.md` schedule tables still show "Comfort Cool" as the occupied mode.

**Where:** `climate/spec/hvac-spec.md` lines ~42, 52, 54, 60

**Evidence:**
- `schedule.yaml` line 14: `climate: smart2  # Comfort Heat`
- `hvac-spec.md` line 42: `| 6:00 am  | Comfort Cool | Start warming up before people are up |`

**Fix:** Update the schedule tables in `hvac-spec.md` to show "Comfort Heat" where the schedule currently uses `smart2`. The story spec AC 10 notes that schedule tables "already reflect Comfort Heat" — but the actual file does not match.

#### 2. `get_data_age_minutes` has no dedicated test

**What:** AC 9 requires "all new functions have unit tests." `get_data_age_minutes` is a public function in `client.py` with no dedicated test in `test_client.py`.

**Where:** `climate/ambient/client.py` line 33 — function definition; `tests/ambient/test_client.py` — no matching test section.

**Fix:** Add tests for `get_data_age_minutes` covering:
- Recent timestamp → returns positive float near expected minutes
- Missing `dateutc` key → returns `None`
- Old timestamp → returns large float

Example:

```python
# --- get_data_age_minutes ---

def test_get_data_age_minutes_recent():
    last_data = {"dateutc": int(time.time() * 1000) - 120_000}  # 2 minutes ago
    age = get_data_age_minutes(last_data)
    assert age is not None
    assert 1.5 < age < 2.5

def test_get_data_age_minutes_missing_timestamp():
    assert get_data_age_minutes({}) is None
```

### Suggestions — Nice to Have

#### 3. Stale inline comments after mode switch

`schedule.yaml` has comments like `# Comfort Heat` on value lines. After running `just climate-comfort-switch cool`, values change to `smart1` but comments still say "Comfort Heat." This is a known trade-off — the regex intentionally preserves comments for safety. Consider removing these inline comments from `schedule.yaml` since the meaning of `smart1`/`smart2` is documented in `hvac-spec.md`.

#### 4. `load_weather_config` calls `sys.exit(1)` on file errors

Fine for CLI usage, but couples the function to CLI behavior. Raising an exception and catching at the CLI boundary would be cleaner. Low priority for a personal project tool.

#### 5. `_fetch_temp` has no direct unit test

Exercised indirectly through mocked `_fetch_all_temps`, but no test verifies its plausibility/freshness/timeout filtering with mock API responses. The pure-function guards are tested independently, so this is acceptable — but a direct test would increase confidence in the orchestration logic.

#### 6. `.gitignore` addition of `vendor/` is unrelated to this story

Presumably from development when referencing HA core source for the `aioambient` API. Reasonable addition, but out of scope.

## Files Reviewed

| File | Type | Notes |
|------|------|-------|
| `climate/ambient/__init__.py` | New | Empty package init |
| `climate/ambient/client.py` | New | Core module — clean, well-structured |
| `climate/config/weather.yaml` | New | Valid YAML, stations placeholder |
| `climate/config/schedule.yaml` | Modified | Now uses `smart2` (Comfort Heat) |
| `climate/sync.py` | Modified | 3 new subcommands + `_apply_comfort_mode` |
| `climate/spec/hvac-spec.md` | Modified | Thresholds added; **schedule tables stale** |
| `Justfile` | Modified | 4 new tasks |
| `pyproject.toml` | Modified | `aioambient` dep + pytest config |
| `.env.template` | Modified | `HOME_LAT`/`HOME_LON` |
| `.gitignore` | Modified | Added `vendor/` (unrelated) |
| `tests/ambient/__init__.py` | New | Empty test package init |
| `tests/ambient/test_client.py` | New | 18 tests — thorough |
| `tests/test_comfort_switch.py` | New | 12 tests — thorough |

## Assessment

**Overall:** Well-executed implementation with solid architecture and good test coverage. Fix the two Important items (spec table consistency + missing test), then ready to commit.
