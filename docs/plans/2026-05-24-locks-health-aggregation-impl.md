# Locks Health Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggregate per-lock signals (bridge online, lock reachable, battery, data freshness) into a three-tier health verdict (healthy/warning/unhealthy) displayed in `just locks status`.

**Architecture:** Add derived `@property` methods to the existing `YaleLock` dataclass (matching the existing `is_stale` / `battery_valid` pattern). Capture one additional field from Yale's API for diagnostic display. All health logic is a pure function of `YaleLock`, making it easy to unit-test without mocking.

**Tech Stack:** Python 3, dataclasses, pytest, `yalexs` library.

**Spec:** `docs/plans/2026-05-24-locks-health-aggregation.md`

---

## File Structure

**Modified:**
- `locks/yale/client.py`: add `HealthIssue` dataclass, health thresholds, `wifi_issue_at` field on `BridgeStatus`, `_parse_bridge` capture, and two new `@property` methods on `YaleLock`
- `locks/locks_cli.py`: add Health line to summary header, health glyph column to per-home table, Health block + WiFi issue line to detail view, `═` underline fix

**Created:**
- `tests/locks/__init__.py`
- `tests/locks/yale/__init__.py`
- `tests/locks/yale/test_client.py`: tests for `_parse_bridge` (WiFi capture) and `YaleLock.health_issues` / `health_status`

CLI changes are not unit-tested (per project convention, string formatting has no logic). They're validated by running `just locks status` against the live account.

---

## Task 1: Capture `WifiModuleConnectionIssue` in `BridgeStatus`

**Files:**
- Modify: `locks/yale/client.py:17-24` (BridgeStatus), `locks/yale/client.py:63-76` (_parse_bridge)
- Create: `tests/locks/__init__.py`, `tests/locks/yale/__init__.py`, `tests/locks/yale/test_client.py`

- [ ] **Step 1: Create test directory structure**

```bash
mkdir -p tests/locks/yale
touch tests/locks/__init__.py
touch tests/locks/yale/__init__.py
```

- [ ] **Step 2: Write failing parser test**

Create `tests/locks/yale/test_client.py`:

```python
from datetime import datetime, timezone

from locks.yale.client import _parse_bridge


def test_parse_bridge_captures_wifi_issue_timestamp():
    raw = {
        "deviceModel": "august-connect",
        "firmwareVersion": "2.3.1",
        "mfgBridgeID": "C5W3Q00D1A",
        "status": {"current": "online", "lastOnline": None, "lastOffline": None},
        "enhancedStatus": {"WifiModuleConnectionIssue": 1746237052214},
    }
    bridge = _parse_bridge(raw)
    assert bridge is not None
    assert bridge.wifi_issue_at == datetime.fromtimestamp(
        1746237052.214, tz=timezone.utc
    )


def test_parse_bridge_no_wifi_issue():
    raw = {
        "deviceModel": "august-connect",
        "firmwareVersion": "2.3.1",
        "mfgBridgeID": "C5W3Q00D1A",
        "status": {"current": "online", "lastOnline": None, "lastOffline": None},
    }
    bridge = _parse_bridge(raw)
    assert bridge is not None
    assert bridge.wifi_issue_at is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/locks/yale/test_client.py -v`
Expected: FAIL, `BridgeStatus.__init__() got an unexpected keyword argument 'wifi_issue_at'` or AttributeError on `wifi_issue_at`.

- [ ] **Step 4: Add `wifi_issue_at` field to `BridgeStatus`**

In `locks/yale/client.py`, update the `BridgeStatus` dataclass (around line 17-24):

```python
@dataclass
class BridgeStatus:
    """State of an August Connect bridge. None elsewhere = lock is unbridged."""
    connectivity: BridgeConnectivity
    last_online: datetime | None
    last_offline: datetime | None
    model: str | None
    firmware: str | None
    mfg_id: str | None
    wifi_issue_at: datetime | None
```

- [ ] **Step 5: Update `_parse_bridge` to capture the WiFi issue timestamp**

In `locks/yale/client.py`, replace the body of `_parse_bridge` (around line 63-76) with:

```python
def _parse_bridge(raw_bridge: dict | None) -> BridgeStatus | None:
    if not raw_bridge:
        return None
    status = raw_bridge.get("status") or {}
    current = status.get("current")
    connectivity: BridgeConnectivity = "online" if current == "online" else "offline"

    enhanced = raw_bridge.get("enhancedStatus") or {}
    wifi_issue_ms = enhanced.get("WifiModuleConnectionIssue")
    wifi_issue_at = (
        datetime.fromtimestamp(wifi_issue_ms / 1000, tz=timezone.utc)
        if wifi_issue_ms else None
    )

    return BridgeStatus(
        connectivity=connectivity,
        last_online=_parse_iso(status.get("lastOnline")),
        last_offline=_parse_iso(status.get("lastOffline")),
        model=raw_bridge.get("deviceModel"),
        firmware=raw_bridge.get("firmwareVersion"),
        mfg_id=raw_bridge.get("mfgBridgeID"),
        wifi_issue_at=wifi_issue_at,
    )
```

You'll also need to add `timezone` to the existing `from datetime import datetime` line at the top of the file:

```python
from datetime import datetime, timezone
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/locks/yale/test_client.py -v`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add locks/yale/client.py tests/locks/__init__.py tests/locks/yale/__init__.py tests/locks/yale/test_client.py
git commit -m "feat(locks): capture WifiModuleConnectionIssue from Yale API

Surface Yale's own WiFi-flap signal as a new wifi_issue_at field on
BridgeStatus, for diagnostic display. Not yet used as a health gate."
```

---

## Task 2: Add `HealthIssue`, thresholds, and `health_issues` / `health_status` properties

**Files:**
- Modify: `locks/yale/client.py` (add dataclass, constants, two properties on YaleLock)
- Modify: `tests/locks/yale/test_client.py` (add ~12 test cases + factory helper)

This task is one TDD cycle per scenario from the spec. The `_make_lock` factory keeps each test to one or two lines.

- [ ] **Step 1: Add `_make_lock` factory and the first failing test (fully healthy)**

Append to `tests/locks/yale/test_client.py`:

```python
from datetime import timedelta

from yalexs.lock import LockDoorStatus, LockStatus

from locks.yale.client import BridgeStatus, HealthIssue, YaleLock


def _make_bridge(
    connectivity: str = "online",
    wifi_issue_at: datetime | None = None,
) -> BridgeStatus:
    return BridgeStatus(
        connectivity=connectivity,
        last_online=None,
        last_offline=None,
        model="august-connect",
        firmware="2.3.1",
        mfg_id="TEST",
        wifi_issue_at=wifi_issue_at,
    )


def _make_lock(
    *,
    bridge: BridgeStatus | None = None,
    lock_status: LockStatus = LockStatus.LOCKED,
    battery_level: int = 97,
    status_datetime: datetime | None = None,
) -> YaleLock:
    if status_datetime is None:
        status_datetime = datetime.now(timezone.utc)
    if bridge is None:
        bridge = _make_bridge()
    return YaleLock(
        lock_id="lock-id",
        name="Test Lock",
        house_id="house-id",
        house_name="Test House",
        lock_status=lock_status,
        door_state=LockDoorStatus.CLOSED,
        doorsense=True,
        battery_level=battery_level,
        status_datetime=status_datetime,
        mac_address="00:00:00:00:00:00",
        firmware_version="1.0.0",
        model="AUG-MDY1",
        serial_number="TEST123",
        bridge=bridge,
    )


def test_healthy_lock_has_no_issues():
    lock = _make_lock()
    assert lock.health_issues == []
    assert lock.health_status == "healthy"
```

- [ ] **Step 2: Run to verify the test fails**

Run: `uv run pytest tests/locks/yale/test_client.py::test_healthy_lock_has_no_issues -v`
Expected: FAIL, `ImportError: cannot import name 'HealthIssue'` or `AttributeError: 'YaleLock' object has no attribute 'health_issues'`.

- [ ] **Step 3: Add `HealthIssue` dataclass and thresholds**

First, extend the datetime import at the top of `locks/yale/client.py` from:

```python
from datetime import datetime, timezone
```

to:

```python
from datetime import datetime, timedelta, timezone
```

The `Literal` import also needs to be added. Replace the existing `from typing import Literal` line if present, or add it under the other imports:

```python
from typing import Literal
```

Then, near the top of the file (after the existing `BridgeConnectivity` type alias), add:

```python
HEALTH_BATTERY_WARNING  = 40
HEALTH_BATTERY_CRITICAL = 25
HEALTH_MAX_DATA_AGE     = timedelta(hours=6)

HealthSeverity = Literal["warning", "critical"]
HealthStatus = Literal["healthy", "warning", "unhealthy"]


@dataclass
class HealthIssue:
    severity: HealthSeverity
    message: str
```

- [ ] **Step 4: Add minimal `health_issues` and `health_status` properties**

In `locks/yale/client.py`, add these two properties to `YaleLock` (right after the existing `battery_valid` property):

```python
    @property
    def health_issues(self) -> list[HealthIssue]:
        return []

    @property
    def health_status(self) -> HealthStatus:
        issues = self.health_issues
        if not issues:
            return "healthy"
        if any(i.severity == "critical" for i in issues):
            return "unhealthy"
        return "warning"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/locks/yale/test_client.py::test_healthy_lock_has_no_issues -v`
Expected: PASS.

- [ ] **Step 6: Add bridge-level failing tests**

Append to `tests/locks/yale/test_client.py`:

```python
def test_unbridged_lock_returns_only_no_bridge():
    lock = _make_lock(bridge=None)
    assert lock.health_issues == [HealthIssue("critical", "no bridge")]
    assert lock.health_status == "unhealthy"


def test_bridge_offline_returns_only_bridge_offline():
    lock = _make_lock(bridge=_make_bridge(connectivity="offline"))
    assert lock.health_issues == [HealthIssue("critical", "bridge offline")]
    assert lock.health_status == "unhealthy"


def test_short_circuit_unbridged_with_low_battery():
    # Even though battery would also fail, we suppress downstream issues.
    lock = _make_lock(bridge=None, battery_level=10)
    assert lock.health_issues == [HealthIssue("critical", "no bridge")]
```

- [ ] **Step 7: Run to verify they fail**

Run: `uv run pytest tests/locks/yale/test_client.py -v`
Expected: 3 new failures (existing test still passes).

- [ ] **Step 8: Implement bridge-level checks**

Replace the body of `health_issues` in `locks/yale/client.py`:

```python
    @property
    def health_issues(self) -> list[HealthIssue]:
        if self.bridge is None:
            return [HealthIssue("critical", "no bridge")]
        if self.bridge.connectivity != "online":
            return [HealthIssue("critical", "bridge offline")]
        return []
```

- [ ] **Step 9: Run to verify all tests pass**

Run: `uv run pytest tests/locks/yale/test_client.py -v`
Expected: 5 passed.

- [ ] **Step 10: Add downstream check tests**

Append to `tests/locks/yale/test_client.py`:

```python
def test_lock_status_unknown_is_unreachable():
    lock = _make_lock(lock_status=LockStatus.UNKNOWN)
    assert HealthIssue("critical", "lock unreachable") in lock.health_issues
    assert lock.health_status == "unhealthy"


def test_battery_invalid_is_unknown():
    lock = _make_lock(battery_level=-100)
    assert HealthIssue("critical", "battery unknown") in lock.health_issues
    assert lock.health_status == "unhealthy"


def test_battery_24_is_critical():
    lock = _make_lock(battery_level=24)
    assert HealthIssue("critical", "low battery (24%)") in lock.health_issues
    assert lock.health_status == "unhealthy"


def test_battery_25_is_warning():
    lock = _make_lock(battery_level=25)
    assert HealthIssue("warning", "low battery (25%)") in lock.health_issues
    assert lock.health_status == "warning"


def test_battery_39_is_warning():
    lock = _make_lock(battery_level=39)
    assert HealthIssue("warning", "low battery (39%)") in lock.health_issues
    assert lock.health_status == "warning"


def test_battery_40_is_healthy():
    lock = _make_lock(battery_level=40)
    assert lock.health_issues == []
    assert lock.health_status == "healthy"


def test_stale_data_flags_unhealthy():
    seven_hours_ago = datetime.now(timezone.utc) - timedelta(hours=7)
    lock = _make_lock(status_datetime=seven_hours_ago)
    msgs = [i.message for i in lock.health_issues]
    assert any(m.startswith("data stale") for m in msgs)
    assert lock.health_status == "unhealthy"


def test_status_datetime_none_flags_unhealthy():
    # The factory defaults status_datetime to "now" if not given; for this
    # case we want None explicitly, so we construct from a base lock.
    base = _make_lock()
    lock = YaleLock(**{**base.__dict__, "status_datetime": None})
    msgs = [i.message for i in lock.health_issues]
    assert any(m.startswith("data stale") for m in msgs)
    assert lock.health_status == "unhealthy"


def test_multiple_issues_critical_wins():
    seven_hours_ago = datetime.now(timezone.utc) - timedelta(hours=7)
    lock = _make_lock(
        lock_status=LockStatus.UNKNOWN,
        battery_level=20,
        status_datetime=seven_hours_ago,
    )
    severities = {i.severity for i in lock.health_issues}
    assert "critical" in severities
    assert lock.health_status == "unhealthy"
    # All three downstream checks should fire (lock, battery, stale)
    assert len(lock.health_issues) == 3
```

- [ ] **Step 11: Run to verify they fail**

Run: `uv run pytest tests/locks/yale/test_client.py -v`
Expected: 9 new failures.

- [ ] **Step 12: Implement downstream checks**

Replace the body of `health_issues` again:

```python
    @property
    def health_issues(self) -> list[HealthIssue]:
        if self.bridge is None:
            return [HealthIssue("critical", "no bridge")]
        if self.bridge.connectivity != "online":
            return [HealthIssue("critical", "bridge offline")]

        issues: list[HealthIssue] = []

        if self.lock_status not in (LockStatus.LOCKED, LockStatus.UNLOCKED):
            issues.append(HealthIssue("critical", "lock unreachable"))

        if not self.battery_valid:
            issues.append(HealthIssue("critical", "battery unknown"))
        elif self.battery_level < HEALTH_BATTERY_CRITICAL:
            issues.append(HealthIssue("critical", f"low battery ({self.battery_level}%)"))
        elif self.battery_level < HEALTH_BATTERY_WARNING:
            issues.append(HealthIssue("warning", f"low battery ({self.battery_level}%)"))

        if self.status_datetime is None:
            issues.append(HealthIssue("critical", "data stale (unknown)"))
        else:
            age = datetime.now(timezone.utc) - self.status_datetime
            if age > HEALTH_MAX_DATA_AGE:
                hours = int(age.total_seconds() // 3600)
                issues.append(HealthIssue("critical", f"data stale ({hours}h old)"))

        return issues
```

The import of `LockStatus` is already present at the top of the file (line `from yalexs.lock import LockDetail, LockDoorStatus, LockStatus`).

- [ ] **Step 13: Run all tests to verify they pass**

Run: `uv run pytest tests/locks/yale/test_client.py -v`
Expected: 15 passed (2 from Task 1 + 13 from this task).

- [ ] **Step 14: Commit**

```bash
git add locks/yale/client.py tests/locks/yale/test_client.py
git commit -m "feat(locks): aggregate per-lock signals into health verdict

Add HealthIssue dataclass and health_issues / health_status properties
on YaleLock. Three-tier verdict: healthy / warning / unhealthy.
Battery <25% or any unreachability is critical; battery 25-39% is
warning. Short-circuits noise from compound failures."
```

---

## Task 3: Add Health line to CLI summary header

**Files:**
- Modify: `locks/locks_cli.py:134-146` (_print_summary)

CLI display has no unit tests (per project convention); verify by running the CLI.

- [ ] **Step 1: Run the CLI to capture current output for comparison**

Run: `just locks status`
Note the current "Yale locks: N across M homes" header so you can compare after.

- [ ] **Step 2: Update `_print_summary` to include a Health line**

In `locks/locks_cli.py`, replace `_print_summary` (around line 134-146) with:

```python
def _print_summary(locks: list[YaleLock]) -> None:
    homes = {l.house_id for l in locks}
    online = sum(1 for l in locks if l.bridge and l.bridge.connectivity == "online")
    offline = sum(1 for l in locks if l.bridge and l.bridge.connectivity == "offline")
    unbridged = sum(1 for l in locks if l.bridge is None)
    batt_ok = sum(1 for l in locks if l.battery_valid and not l.is_stale)

    healthy = sum(1 for l in locks if l.health_status == "healthy")
    warning = sum(1 for l in locks if l.health_status == "warning")
    unhealthy = sum(1 for l in locks if l.health_status == "unhealthy")

    print(_bold(f"Yale locks: {len(locks)} across {len(homes)} homes"))
    print(f"  Health:    {_green(str(healthy)+' healthy')}, "
          f"{_yellow(str(warning)+' warning')}, "
          f"{_red(str(unhealthy)+' unhealthy')}")
    print(f"  Bridges:   {_green(str(online)+' online')}, "
          f"{_red(str(offline)+' offline')}, "
          f"{_yellow(str(unbridged)+' none')}")
    print(f"  Batteries: {batt_ok}/{len(locks)} reporting (rest stale or unknown)")
    print()
```

- [ ] **Step 3: Run the CLI to verify the new line appears**

Run: `just locks status`
Expected: header now shows a `Health:` line above `Bridges:` with the three-tier breakdown.

- [ ] **Step 4: Commit**

```bash
git add locks/locks_cli.py
git commit -m "feat(locks): show health breakdown in status summary"
```

---

## Task 4: Add health glyph column and fix home-name underline

**Files:**
- Modify: `locks/locks_cli.py:103-131` (_format_one_line, _compute_widths), `locks/locks_cli.py:149-155` (_print_home_section)

- [ ] **Step 1: Add `_health_glyph` helper**

In `locks/locks_cli.py`, after the existing color helpers (around line 42), add:

```python
def _health_glyph(lock: YaleLock) -> str:
    status = lock.health_status
    if status == "healthy":
        return _green("✓")
    if status == "warning":
        return _yellow("⚠")
    return _red("✗")
```

- [ ] **Step 2: Update `_format_one_line` to prepend the glyph**

Replace `_format_one_line` (around line 103-121) with:

```python
def _format_one_line(lock: YaleLock, widths: dict) -> str:
    glyph = _health_glyph(lock)
    name = lock.name.ljust(widths["name"])
    state = _lock_state_str(lock).ljust(widths["state"])
    door = _door_state_str(lock).ljust(widths["door"])
    battery = _battery_str(lock).rjust(widths["battery"])
    bridge_lbl, since = _bridge_str(lock.bridge)
    bridge_cell = bridge_lbl.ljust(widths["bridge"])

    # Colorize bridge label independently so the status pops even when the
    # rest of the line is grayed out for staleness.
    if lock.bridge is None:
        bridge_cell = _yellow(bridge_cell)
    elif lock.bridge.connectivity == "online":
        bridge_cell = _green(bridge_cell)
    else:
        bridge_cell = _red(bridge_cell)

    line = f"  {glyph}  {name}  {state}  {door}  {battery}  {bridge_cell}  {since}"
    return _gray(line) if lock.is_stale else line
```

(`_compute_widths` does not need to change, the glyph is always one display cell.)

- [ ] **Step 3: Fix home-name underline character**

In `locks/locks_cli.py`, replace `_print_home_section` (around line 149-155) with:

```python
def _print_home_section(home_name: str, locks: list[YaleLock]) -> None:
    print(_bold(home_name))
    print("═" * len(home_name))
    widths = _compute_widths(locks)
    for lock in sorted(locks, key=lambda l: l.name):
        print(_format_one_line(lock, widths))
    print()
```

- [ ] **Step 4: Run the CLI to verify the new column and underline**

Run: `just locks status`
Expected:
- Each lock row starts with `  ✓ ` / `  ⚠ ` / `  ✗ ` (colored)
- Home name underline is a continuous double line (no gaps)

- [ ] **Step 5: Commit**

```bash
git add locks/locks_cli.py
git commit -m "feat(locks): show per-lock health glyph in status table

Prepend ✓ / ⚠ / ✗ glyph to each row in just locks status. Also
swap = for ═ in home-name underline so it renders continuously
across all monospace fonts."
```

---

## Task 5: Add Health block + WiFi issue line to detail view

**Files:**
- Modify: `locks/locks_cli.py:158-190` (_print_detail)

- [ ] **Step 1: Add `_issue_glyph` helper**

In `locks/locks_cli.py`, after `_health_glyph` (added in Task 4), add:

```python
def _issue_glyph(severity: str) -> str:
    if severity == "warning":
        return _yellow("⚠")
    return _red("✗")
```

- [ ] **Step 2: Replace `_print_detail` with the new layout**

Replace `_print_detail` (around line 158-190) with:

```python
def _print_detail(lock: YaleLock) -> None:
    print(_bold(f"{lock.house_name} > {lock.name}"))

    status = lock.health_status
    if status == "healthy":
        print(f"  Health:    {_green('healthy')}")
    else:
        label = _yellow("WARNING") if status == "warning" else _red("UNHEALTHY")
        print(f"  Health:    {label}")
        for issue in lock.health_issues:
            print(f"    {_issue_glyph(issue.severity)} {issue.message}")

    state = _lock_state_str(lock)
    if lock.is_stale:
        state += " (stale)"
    print(f"  Locked:    {state}")
    if lock.doorsense:
        door = _door_state_str(lock)
        if lock.is_stale:
            door += " (stale)"
        print(f"  Door:      {door}")
    print(f"  Battery:   {_battery_str(lock)}" + (" (stale)" if lock.is_stale and lock.battery_valid else ""))
    print(f"  Lock seen: {_format_ts(lock.status_datetime)}")
    if lock.mac_address:
        print(f"  MAC:       {lock.mac_address}")
    if lock.model:
        print(f"  Model:     {lock.model}")
    print(f"  Firmware:  {lock.firmware_version}")
    print(f"  Serial:    {lock.serial_number}")

    if lock.bridge is None:
        print(f"  Bridge:    {_yellow('none (unbridged lock)')}")
    else:
        b = lock.bridge
        colored = _green("online") if b.connectivity == "online" else _red("offline")
        print(f"  Bridge:")
        print(f"    Status:    {colored}")
        print(f"    Model:     {b.model or 'unknown'}")
        print(f"    Firmware:  {b.firmware or 'unknown'}")
        print(f"    Mfg ID:    {b.mfg_id or 'unknown'}")
        print(f"    Last online:  {_format_ts(b.last_online)}")
        print(f"    Last offline: {_format_ts(b.last_offline)}")
        if b.wifi_issue_at is not None:
            print(f"    WiFi issue:   {_format_ts(b.wifi_issue_at)}")
    print()
```

- [ ] **Step 3: Run the CLI against a healthy lock**

Run: `just locks status office`
Expected: detail view begins with `Health: healthy` (green), then the existing fields.

- [ ] **Step 4: Run against an unhealthy lock**

Run: `just locks status pantry`
Expected: `Health: UNHEALTHY` (red) followed by one or more `✗ <message>` lines (e.g. `✗ lock unreachable`, `✗ battery unknown`).

- [ ] **Step 5: Run against the warning lock**

Run: `just locks status front` (the Marann Front Door, currently at 31%)
Expected: `Health: WARNING` (yellow) with `⚠ low battery (31%)` listed.

- [ ] **Step 6: Run against a bridge that has a WiFi issue logged**

Run: `just locks status storage` (8 Hacker St Storage Door, its bridge had `WifiModuleConnectionIssue` ~92 days ago)
Expected: in the `Bridge:` block, a new `WiFi issue:` line appears with the timestamp.

- [ ] **Step 7: Commit**

```bash
git add locks/locks_cli.py
git commit -m "feat(locks): show health block and WiFi issue in detail view

Add a Health: line at the top of just locks status <name>, listing
each issue with severity glyph. In the Bridge block, surface Yale's
WifiModuleConnectionIssue timestamp when present."
```

---

## Verification

After all five tasks, run the full test suite to make sure nothing else broke:

```bash
uv run pytest -v
```

Expected: all existing tests pass, 15 new tests in `tests/locks/yale/test_client.py` pass.

Then run the CLI end-to-end:

```bash
just locks status            # summary + per-home tables, with glyphs
just locks status office     # healthy detail
just locks status pantry     # unhealthy detail (multiple issues)
just locks status front      # warning detail (low battery)
just locks status garage     # unhealthy detail (no bridge)
```

The aggregate breakdown should match the validation snapshot in the spec: **1 healthy / 1 warning / 5 unhealthy** (subject to live changes since the snapshot was taken).
