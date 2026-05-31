# Locks health aggregation

Date: 2026-05-24
Status: design

## Problem

`just locks status` shows raw fields per lock (bridge connectivity, lock state, door state, battery, staleness) but doesn't aggregate them into a single "is this lock OK?" judgment. The result: a lock can appear "online" while the Yale app says "device unavailable" (bridge online but BLE link silently dead), or display a battery reading while Yale itself is flagging it as low.

We want two surfaces:

1. **Glance view**: every lock with a health verdict, scannable at a glance
2. **Diagnostic view**: per-lock breakdown of *why* an unhealthy lock is unhealthy

## Health model

A lock is evaluated against five checks. Each failed check produces a `HealthIssue` with a severity. The aggregate `health_status` is:

- `healthy`: no issues
- `warning`: only warning-level issues
- `unhealthy`: any critical issue (critical trumps warning)

### Checks

| Check | Issue message | Severity | Notes |
|---|---|---|---|
| `bridge is None` | `no bridge` | critical | Short-circuits remaining checks |
| `bridge.connectivity != "online"` | `bridge offline` | critical | Short-circuits remaining checks |
| `lock_status not in (LOCKED, UNLOCKED)` | `lock unreachable` | critical | BLE link from bridge to lock is broken |
| `not battery_valid` | `battery unknown` | critical | No usable reading from Yale |
| `battery_level < 25` | `low battery (NN%)` | critical | Below `HEALTH_BATTERY_CRITICAL` |
| `25 <= battery_level < 40` | `low battery (NN%)` | warning | Below `HEALTH_BATTERY_WARNING` |
| `status_datetime` is None or > 6h old | `data stale (Nh old)` | critical | Above `HEALTH_MAX_DATA_AGE` |

### Short-circuit semantics

When a deep cause is present, downstream symptoms it would cause aren't actionable info, they're noise.

- `bridge is None` → return `[HealthIssue("critical", "no bridge")]` only. Battery and lock-state checks are skipped.
- `bridge.connectivity != "online"` → return `[HealthIssue("critical", "bridge offline")]` only. Same reason.
- Otherwise → evaluate all four downstream conditions; return every failure.

A lock can therefore have multiple issues (e.g. `lock unreachable` + `low battery`), but unbridged and offline-bridged locks always have exactly one.

### Why these thresholds

- **Battery 40% warning / 25% critical**: Yale's own app surfaces low-battery warnings around 30%; bracketing it lets us warn slightly earlier and escalate slightly later, giving a clear "replace soon" vs "replace now" signal.
- **Data age 6h**: empirical observation shows healthy bridges update lock data on a ~30-minute cadence. 6h is ~12x normal, large headroom against false positives, while still catching the "bridge online but BLE link silently dead" case. Provisional; revisit once we have alerting data.
- **`WifiModuleConnectionIssue`**: captured for diagnostic display (Yale tells us when the bridge's WiFi flapped), but **not** a health gate in v1. The signal is real but low-rate and we don't yet know how predictive it is.

## Implementation

### Data model (`locks/yale/client.py`)

```python
HEALTH_BATTERY_WARNING  = 40
HEALTH_BATTERY_CRITICAL = 25
HEALTH_MAX_DATA_AGE     = timedelta(hours=6)


@dataclass
class HealthIssue:
    severity: Literal["warning", "critical"]
    message: str


@dataclass
class BridgeStatus:
    connectivity: BridgeConnectivity
    last_online: datetime | None
    last_offline: datetime | None
    model: str | None
    firmware: str | None
    mfg_id: str | None
    wifi_issue_at: datetime | None   # NEW: from enhancedStatus.WifiModuleConnectionIssue


@dataclass
class YaleLock:
    # ...existing fields unchanged...

    @property
    def is_stale(self) -> bool: ...        # existing, unchanged

    @property
    def battery_valid(self) -> bool: ...   # existing, unchanged

    @property
    def health_issues(self) -> list[HealthIssue]: ...   # NEW

    @property
    def health_status(self) -> Literal["healthy", "warning", "unhealthy"]: ...   # NEW
```

`_parse_bridge` gains one line:

```python
es = raw_bridge.get("enhancedStatus") or {}
wifi_issue_ms = es.get("WifiModuleConnectionIssue")
wifi_issue_at = (
    datetime.fromtimestamp(wifi_issue_ms / 1000, tz=timezone.utc)
    if wifi_issue_ms else None
)
```

Pattern matches the existing `is_stale` and `battery_valid` properties (computed on read, no caching).

### CLI display (`locks/locks_cli.py`)

**Summary header**: add one line above existing breakdowns:

```
Yale locks: 7 across 2 homes
  Health:    1 healthy, 1 warning, 5 unhealthy
  Bridges:   4 online, 2 offline, 1 none
  Batteries: 3/7 reporting (rest stale or unknown)
```

**Per-home table**: leading status glyph column, existing columns retained:

```
2108 Marann Dr NE
═════════════════
  ✗  Basement Door     unknown   unknown   97%  online     34m
  ✗  Garage Side Door  unknown   n/a        --  no bridge
  ⚠  Front Door        unlocked  closed    31%  online     34m
  ✓  Office Door       locked    unknown   97%  online     33m
  ✗  Pantry Door       unknown   n/a        --  online     34m
```

- `✓` green / `⚠` yellow / `✗` red using existing `_green`/`_yellow`/`_red` helpers
- Glyph at the start of the row so the eye lands consistently
- Existing gray-when-stale treatment stays, orthogonal to health
- Home-name underline switches from `=` to `═` (U+2550) so the line renders continuously across all monospace fonts

**Detail view**: add a Health block at the top of `_print_detail`:

```
2108 Marann Dr NE > Pantry Door
  Health:    UNHEALTHY
    ✗ lock unreachable
    ✗ battery unknown
  Locked:    unknown
  Door:      unknown
  ...
```

Healthy locks render just:

```
  Health:    healthy
```

Warning locks render:

```
  Health:    WARNING
    ⚠ low battery (31%)
```

WiFi issue timestamp appears in the existing Bridge block as a new line (diagnostic, not health gate):

```
  Bridge:
    Status:       online
    ...
    WiFi issue:   2025-08-23 14:30 EDT (92d ago)
```

Omitted when `wifi_issue_at is None`.

## Validation against current data

Snapshot taken 2026-05-24 against the live Yale account:

| Lock | Bridge | Lock state | Battery | Data age | Verdict | Issues |
|---|---|---|---|---|---|---|
| Front Door (Marann) | online | unlocked | 31% | 34m | warning | low battery (31%) |
| Office Door | online | locked | 97% | 33m | healthy | n/a |
| Basement Door | online | unknown | 97% | 34m | unhealthy | lock unreachable |
| Pantry Door | online | unknown | -100% | 34m | unhealthy | lock unreachable, battery unknown |
| Garage Side Door | (none) | n/a | n/a | n/a | unhealthy | no bridge |
| Front Door (8 Hacker) | offline | n/a | n/a | n/a | unhealthy | bridge offline |
| Storage Door (8 Hacker) | offline | n/a | n/a | n/a | unhealthy | bridge offline |

Aggregate: **1 healthy / 1 warning / 5 unhealthy**.

### Observations from validation

- All seven `lock_status_datetime` values cluster at 33-34 minutes. This strongly suggests Yale's API updates this field on a polling cadence, not per-lock telemetry. Implication: staleness check effectively asks "did Yale's poller skip this lock for hours," which is still a useful signal.
- Two locks at Marann (Pantry, Basement) show `lock_status=unknown`; both BLE links are intermittent. Same hardware generation (78:9C:85:1x MAC prefix). Worth tracking as a separate diagnostic thread, not addressed by this design.
- `WifiModuleConnectionIssue` ages range from 92d to 387d, a low-rate event, confirming it's not viable as a real-time health gate.

## Testing

Tests live in `tests/locks/yale/test_client.py` (mirrors source layout per project convention; `tests/locks/` is created).

All tests construct `YaleLock` directly with controlled inputs, no API mocking. Health logic is a pure function of the dataclass.

| Scenario | Expected |
|---|---|
| Fully healthy | `[]`, `"healthy"` |
| Unbridged | `["no bridge"]` critical only, `"unhealthy"` |
| Bridge offline | `["bridge offline"]` only, `"unhealthy"` |
| BLE link dead (lock_status unknown) | `["lock unreachable"]`, `"unhealthy"` |
| Battery invalid (e.g. -100) | `["battery unknown"]`, `"unhealthy"` |
| Battery 39% | `["low battery (39%)"]` warning, `"warning"` |
| Battery 25% | `["low battery (25%)"]` warning, `"warning"` |
| Battery 24% | `["low battery (24%)"]` critical, `"unhealthy"` |
| Stale data (7h old) | `["data stale (7h old)"]`, `"unhealthy"` |
| Stale + low battery | both issues, `"unhealthy"` (critical wins) |
| Short-circuit: unbridged + would-also-be-low | `["no bridge"]` only |

Helper: `_make_lock(**overrides)` factory at file top with healthy defaults so each test passes only the fields that differ.

Parser test: one case asserting `WifiModuleConnectionIssue` (Unix ms) → `datetime` (UTC-aware) conversion in `_parse_bridge`.

### Out of scope for tests

- CLI string formatting (no logic, just `.format()` calls)
- Real Yale API integration (project convention: no network tests)
- Timezone math beyond "UTC-aware comparison works"; a naive datetime would raise immediately

## Out of scope for this design

- Alerting / push notifications when health transitions
- Tracking health history over time (would require a sqlite or jsonl log)
- Diagnosing the BLE flap pattern on Marann locks (separate thread)
- Promoting `WifiModuleConnectionIssue` from diagnostic to health gate
- Tightening the staleness threshold once we have more data

## Open questions

None blocking implementation. The 6h staleness threshold is provisional and may be tightened once we have alerting data showing what "normal lag" actually looks like on the longer tail.
