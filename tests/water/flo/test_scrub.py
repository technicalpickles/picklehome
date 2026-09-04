import copy
import json
import pathlib

from water.flo.scrub import scrub_payload

FIXTURE = json.loads(
    (pathlib.Path(__file__).parents[2] / "fixtures" / "flo-device.json").read_text()
)


def _raw_payload():
    """Build an unredacted payload shaped like fetch_raw()'s return value.

    Starts from the already-scrubbed fixture and reintroduces plausible raw
    values under the keys that should be dropped/redacted/zeroed, so tests
    can assert scrub_payload() removes them without needing a second,
    unredacted fixture checked into the repo.
    """
    raw = copy.deepcopy(FIXTURE)
    device = raw["devices"][0]
    device["macAddress"] = "aa:bb:cc:dd:ee:ff"
    device["serialNumber"] = "SN123456789"
    device["connectivity"]["ssid"] = "MyHomeWifi"
    device["fwProperties"] = {"memfault_project_key": "x" * 32, "some_other_key": "value"}

    location = raw["locations"][0]
    location["address"] = "123 Main St"
    location["city"] = "Atlanta"
    location["state"] = "GA"
    location["postalCode"] = "30301"
    location["geoLocation"] = {"latitude": 33.749, "longitude": -84.388}
    location["actionRules"] = ["rule1"]
    location["hardwareThresholds"] = {"foo": "bar"}
    location["learning"] = {"foo": "bar"}
    location["irrigationSchedule"] = {"foo": "bar"}

    user = raw["user"]
    user["email"] = "josh@example.com"
    user["firstName"] = "Josh"
    user["lastName"] = "Nichols"
    user["phoneMobile"] = "+15555550123"
    user["users"] = [{"id": "other-user"}]
    user["userRoles"] = ["owner"]
    user["account"] = {"id": "acct-1"}
    user["locations"][0]["areas"] = [{"name": "kitchen"}]

    return raw


def test_drops_bulky_subtrees_entirely():
    scrubbed = scrub_payload(_raw_payload())
    device = scrubbed["devices"][0]
    location = scrubbed["locations"][0]
    user = scrubbed["user"]

    assert "fwProperties" not in device
    assert "actionRules" not in location
    assert "hardwareThresholds" not in location
    assert "learning" not in location
    assert "irrigationSchedule" not in location
    assert "users" not in user
    assert "userRoles" not in user
    assert "account" not in user
    assert "areas" not in user["locations"][0]


def test_redacts_identifying_scalars():
    scrubbed = scrub_payload(_raw_payload())
    device = scrubbed["devices"][0]
    location = scrubbed["locations"][0]
    user = scrubbed["user"]

    assert user["email"] == "REDACTED"
    assert user["firstName"] == "REDACTED"
    assert user["lastName"] == "REDACTED"
    assert user["phoneMobile"] == "REDACTED"
    assert location["address"] == "REDACTED"
    assert location["city"] == "REDACTED"
    assert location["state"] == "REDACTED"
    assert location["postalCode"] == "REDACTED"
    assert location["geoLocation"] == "REDACTED"
    assert device["macAddress"] == "REDACTED"
    assert device["serialNumber"] == "REDACTED"
    assert device["connectivity"]["ssid"] == "REDACTED"


def test_zeros_out_numeric_coordinates():
    raw = _raw_payload()
    # Simulate a shape where lat/lng show up as plain numeric siblings rather
    # than nested inside geoLocation (which is fully redacted as a string).
    raw["locations"][0]["lat"] = 33.749
    raw["locations"][0]["lng"] = -84.388
    scrubbed = scrub_payload(raw)
    assert scrubbed["locations"][0]["lat"] == 0
    assert scrubbed["locations"][0]["lng"] == 0


def test_matches_the_shipped_fixture_for_every_category_it_covers():
    # tests/fixtures/flo-device.json is itself a hand-scrubbed real payload.
    # Reintroducing plausible raw values and scrubbing them should reproduce
    # what shipped for every field this module actually redacts.
    #
    # One known exception: the shipped fixture leaves the *device's* own
    # nickname ("Main Shutoff") unredacted -- it's the display name
    # format_status() prints in ordinary `just water status` output, so it
    # isn't actually sensitive on this account, and the fixture predates this
    # module. scrub_payload() redacts it anyway (nickname is listed as
    # sensitive in general -- a location or device name isn't always as
    # generic as "Main Shutoff"), which is a deliberately stricter default
    # than the historical fixture. Excluded here rather than silently
    # asserting a mismatch every run.
    scrubbed = scrub_payload(_raw_payload())
    expected = copy.deepcopy(FIXTURE)
    expected["devices"][0]["nickname"] = "REDACTED"
    assert scrubbed == expected


def test_idempotent():
    once = scrub_payload(_raw_payload())
    twice = scrub_payload(copy.deepcopy(once))
    assert once == twice


def test_leaves_non_sensitive_fields_untouched():
    scrubbed = scrub_payload(_raw_payload())
    device = scrubbed["devices"][0]
    assert device["valve"] == {"target": "open", "lastKnown": "open"}
    assert device["telemetry"]["current"]["gpm"] == FIXTURE["devices"][0]["telemetry"]["current"]["gpm"]
