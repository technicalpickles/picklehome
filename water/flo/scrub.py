"""Redact PII from Moen Flo raw API payloads.

`fetch_raw` returns Moen's payload unmodified: account email, device MAC,
serial number, street address, city/state/postal, GPS coordinates, WiFi SSID,
and ~180 keys of `fwProperties` (including a 32-char `memfault_project_key`)
all come straight through. `just water device --raw` is documented as "the
first thing to reach for" when debugging the API, which means it's also the
first thing someone pastes into a GitHub issue or an agent session -- so the
CLI redacts by default (see `water/water_cli.py`) rather than trusting every
future caller to remember to scrub by hand.

This must reproduce exactly what was hand-scrubbed into
`tests/fixtures/flo-device.json`; keep the two in sync (see
`tests/water/flo/test_scrub.py`, which asserts scrubbing the unredacted
fixture reproduces it).
"""

from __future__ import annotations

# Whole subtrees dropped rather than redacted: bulky, and none of their
# content (firmware internals, per-account rule/threshold config, other
# users on the account) is useful for debugging a field format.
DROP_KEYS = frozenset(
    {
        "fwProperties",
        "actionRules",
        "hardwareThresholds",
        "learning",
        "users",
        "userRoles",
        "account",
        "areas",
        "irrigationSchedule",
    }
)

# Identifying scalars, replaced with the string "REDACTED" in place.
REDACT_KEYS = frozenset(
    {
        "email",
        "firstName",
        "lastName",
        "phoneMobile",
        "address",
        "address2",
        "city",
        "state",
        "postalCode",
        "country",
        "nickname",
        "macAddress",
        "serialNumber",
        "ssid",
        "id",
        "locationId",
        "accountId",
        "deviceId",
        "timezone",
        "geoLocation",
    }
)

# Numeric coordinates zeroed out rather than replaced with a string, so a
# consumer expecting a float doesn't choke on "REDACTED".
ZERO_KEYS = frozenset({"latitude", "longitude", "lat", "lng"})


def scrub_payload(node):
    """Recursively redact a Moen Flo payload.

    Idempotent: every replacement value (a dropped key, "REDACTED", or 0) is
    stable under a second pass, so scrubbing already-scrubbed output is a
    no-op.
    """
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in DROP_KEYS:
                continue
            if key in REDACT_KEYS:
                result[key] = "REDACTED"
            elif key in ZERO_KEYS and isinstance(value, (int, float)) and not isinstance(
                value, bool
            ):
                result[key] = 0
            else:
                result[key] = scrub_payload(value)
        return result
    if isinstance(node, list):
        return [scrub_payload(v) for v in node]
    return node
