"""Tests for locks.locations: grouping Yale homes onto canonical locations."""

import json
from datetime import datetime, timezone

import pytest
from yalexs.lock import LockDoorStatus, LockStatus

from locks.locations import group_locks
from locks.yale.client import YaleLock


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("PICKLEHOME_LOCATIONS", "HOME_LAT", "HOME_LON", "AMBIENT_STATION_MACS"):
        monkeypatch.delenv(key, raising=False)


def _set_locations(monkeypatch, data):
    monkeypatch.setenv("PICKLEHOME_LOCATIONS", json.dumps(data))


def _make_lock(name: str, house_name: str) -> YaleLock:
    return YaleLock(
        lock_id=f"id-{name}",
        name=name,
        house_id=f"house-{house_name}",
        house_name=house_name,
        lock_status=LockStatus.LOCKED,
        door_state=LockDoorStatus.CLOSED,
        doorsense=True,
        battery_level=90,
        status_datetime=datetime.now(timezone.utc),
        mac_address="00:00:00:00:00:00",
        firmware_version="1.0",
        model="AUG-MDY1",
        serial_number="SER",
        bridge=None,
    )


def _labels(groups):
    return [g.label for g in groups]


def test_no_registry_groups_by_raw_house_name(monkeypatch):
    locks = [_make_lock("Front", "Zeta House"), _make_lock("Back", "Alpha House")]
    groups = group_locks(locks)
    # Unmapped homes sort alphabetically.
    assert _labels(groups) == ["Alpha House", "Zeta House"]


def test_mapped_groups_use_labels_in_registry_order(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "label": "Main House", "lat": 1, "lon": 2,
         "yale_houses": ["Home"]},
        {"slug": "beachhouse", "label": "Beach House", "lat": 3, "lon": 4,
         "yale_houses": ["Beach House"]},
    ])
    locks = [_make_lock("Deck", "Beach House"), _make_lock("Front", "Home")]
    groups = group_locks(locks)
    # Registry order wins: home (index 0) before beachhouse (index 1).
    assert _labels(groups) == ["Main House", "Beach House"]
    assert [l.name for l in groups[0].locks] == ["Front"]


def test_house_matching_is_case_insensitive(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "label": "Main House", "lat": 1, "lon": 2,
         "yale_houses": ["Home"]},
    ])
    groups = group_locks([_make_lock("Front", "  home ")])
    assert _labels(groups) == ["Main House"]


def test_multiple_yale_names_map_to_one_location(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "label": "Main House", "lat": 1, "lon": 2,
         "yale_houses": ["Home", "Nichols Residence"]},
    ])
    locks = [_make_lock("Front", "Home"), _make_lock("Garage", "Nichols Residence")]
    groups = group_locks(locks)
    assert _labels(groups) == ["Main House"]
    assert len(groups[0].locks) == 2


def test_unmapped_homes_sort_after_mapped(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "label": "Main House", "lat": 1, "lon": 2,
         "yale_houses": ["Home"]},
    ])
    locks = [_make_lock("Cabin Door", "Cabin"), _make_lock("Front", "Home")]
    groups = group_locks(locks)
    # Mapped "Main House" first, then unmapped "Cabin".
    assert _labels(groups) == ["Main House", "Cabin"]
