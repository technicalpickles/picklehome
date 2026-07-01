"""Tests for picklehome.locations: PICKLEHOME_LOCATIONS parsing + legacy fallback."""

import json

import pytest

from picklehome.locations import Location, load_locations, resolve_locations


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start each test with no location env vars set."""
    for key in ("PICKLEHOME_LOCATIONS", "HOME_LAT", "HOME_LON", "AMBIENT_STATION_MACS"):
        monkeypatch.delenv(key, raising=False)


def _set_locations(monkeypatch, data):
    monkeypatch.setenv("PICKLEHOME_LOCATIONS", json.dumps(data))


def test_json_path_parses_all_fields(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "label": "Main House", "lat": 33.77, "lon": -84.38,
         "station_macs": ["AA:BB"], "comfort_mode": True,
         "yale_houses": ["Home", "Main House"], "nest_structures": ["Atlanta"]},
    ])
    locs = load_locations()
    assert locs == [Location("home", "Main House", 33.77, -84.38, ["AA:BB"],
                             comfort_mode=True, yale_houses=["Home", "Main House"],
                             nest_structures=["Atlanta"])]


def test_nest_structures_defaults_empty(monkeypatch):
    _set_locations(monkeypatch, [{"slug": "beachhouse", "lat": 41.9, "lon": -70.6}])
    assert load_locations()[0].nest_structures == []


def test_nest_structures_parsed(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "beachhouse", "lat": 41.9, "lon": -70.6,
         "nest_structures": ["8 Hacker St"]},
    ])
    assert load_locations()[0].nest_structures == ["8 Hacker St"]


def test_comfort_mode_defaults_false(monkeypatch):
    _set_locations(monkeypatch, [{"slug": "beachhouse", "lat": 41.9, "lon": -70.6}])
    assert load_locations()[0].comfort_mode is False


def test_yale_houses_defaults_empty(monkeypatch):
    _set_locations(monkeypatch, [{"slug": "beachhouse", "lat": 41.9, "lon": -70.6}])
    assert load_locations()[0].yale_houses == []


def test_yale_houses_parsed(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "beachhouse", "lat": 41.9, "lon": -70.6,
         "yale_houses": ["Beach House"]},
    ])
    assert load_locations()[0].yale_houses == ["Beach House"]


def test_label_defaults_to_slug(monkeypatch):
    _set_locations(monkeypatch, [{"slug": "beachhouse", "lat": 41.9, "lon": -70.6}])
    assert load_locations()[0].label == "beachhouse"


def test_lat_lon_coerced_from_strings(monkeypatch):
    _set_locations(monkeypatch, [{"slug": "home", "lat": "33.77", "lon": "-84.38"}])
    loc = load_locations()[0]
    assert (loc.lat, loc.lon) == (33.77, -84.38)


def test_legacy_fallback_synthesizes_home(monkeypatch):
    monkeypatch.setenv("HOME_LAT", "33.77")
    monkeypatch.setenv("HOME_LON", "-84.38")
    monkeypatch.setenv("AMBIENT_STATION_MACS", "AA:BB, CC:DD")
    locs = load_locations()
    assert locs == [Location("home", "Home", 33.77, -84.38, ["AA:BB", "CC:DD"], comfort_mode=True)]


def test_empty_json_array_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("PICKLEHOME_LOCATIONS", "[]")
    monkeypatch.setenv("HOME_LAT", "33.77")
    monkeypatch.setenv("HOME_LON", "-84.38")
    assert load_locations()[0].slug == "home"


def test_json_takes_precedence_over_legacy(monkeypatch):
    _set_locations(monkeypatch, [{"slug": "beachhouse", "lat": 41.9, "lon": -70.6}])
    monkeypatch.setenv("HOME_LAT", "33.77")
    monkeypatch.setenv("HOME_LON", "-84.38")
    assert [loc.slug for loc in load_locations()] == ["beachhouse"]


def test_nothing_configured_returns_empty(monkeypatch):
    assert load_locations() == []


def test_invalid_json_raises(monkeypatch):
    monkeypatch.setenv("PICKLEHOME_LOCATIONS", "{not json")
    with pytest.raises(RuntimeError, match="not valid JSON"):
        load_locations()


def test_legacy_bad_floats_raise(monkeypatch):
    monkeypatch.setenv("HOME_LAT", "nope")
    monkeypatch.setenv("HOME_LON", "-84.38")
    with pytest.raises(RuntimeError, match="not valid floats"):
        load_locations()


def test_resolve_all(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "lat": 1, "lon": 2},
        {"slug": "beachhouse", "lat": 3, "lon": 4},
    ])
    assert [loc.slug for loc in resolve_locations()] == ["home", "beachhouse"]


def test_resolve_by_slug_case_insensitive(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "lat": 1, "lon": 2},
        {"slug": "beachhouse", "lat": 3, "lon": 4},
    ])
    assert [loc.slug for loc in resolve_locations("BEACHHOUSE")] == ["beachhouse"]


def test_resolve_unknown_slug_raises_with_available(monkeypatch):
    _set_locations(monkeypatch, [{"slug": "home", "lat": 1, "lon": 2}])
    with pytest.raises(RuntimeError, match="Unknown location 'nope'. Available: home"):
        resolve_locations("nope")


def test_resolve_nothing_configured_raises(monkeypatch):
    with pytest.raises(RuntimeError, match="No locations configured"):
        resolve_locations()
