"""Tests for nest.locations: grouping SDM structures onto canonical locations."""

import json

import pytest

from nest.locations import group_devices
from nest.sdm.client import NestDevice


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("PICKLEHOME_LOCATIONS", "HOME_LAT", "HOME_LON", "AMBIENT_STATION_MACS"):
        monkeypatch.delenv(key, raising=False)


def _set_locations(monkeypatch, data):
    monkeypatch.setenv("PICKLEHOME_LOCATIONS", json.dumps(data))


def _make_device(name: str, structure_id: str, device_type: str = "CAMERA") -> NestDevice:
    return NestDevice(
        name=f"enterprises/proj/devices/{name}",
        device_type=device_type,
        custom_name=name,
        structure_id=structure_id,
    )


def _labels(groups):
    return [g.label for g in groups]


def test_no_registry_groups_by_raw_structure_name(monkeypatch):
    devices = [_make_device("Front Cam", "s-zeta"), _make_device("Back Cam", "s-alpha")]
    names = {"s-zeta": "Zeta House", "s-alpha": "Alpha House"}
    groups = group_devices(devices, names)
    assert _labels(groups) == ["Alpha House", "Zeta House"]


def test_mapped_groups_use_labels_in_registry_order(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "label": "Main House", "lat": 1, "lon": 2,
         "nest_structures": ["Atlanta"]},
        {"slug": "beachhouse", "label": "Beach House", "lat": 3, "lon": 4,
         "nest_structures": ["8 Hacker St"]},
    ])
    devices = [_make_device("Deck Cam", "s-beach"), _make_device("Front Cam", "s-atl")]
    names = {"s-beach": "8 Hacker St", "s-atl": "Atlanta"}
    groups = group_devices(devices, names)
    assert _labels(groups) == ["Main House", "Beach House"]
    assert [d.custom_name for d in groups[0].devices] == ["Front Cam"]


def test_structure_matching_is_case_insensitive(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "label": "Main House", "lat": 1, "lon": 2,
         "nest_structures": ["Atlanta"]},
    ])
    groups = group_devices([_make_device("Front Cam", "s-atl")], {"s-atl": "  atlanta "})
    assert _labels(groups) == ["Main House"]


def test_unmapped_structures_sort_after_mapped(monkeypatch):
    _set_locations(monkeypatch, [
        {"slug": "home", "label": "Main House", "lat": 1, "lon": 2,
         "nest_structures": ["Atlanta"]},
    ])
    devices = [_make_device("Cabin Cam", "s-cabin"), _make_device("Front Cam", "s-atl")]
    names = {"s-cabin": "Cabin", "s-atl": "Atlanta"}
    groups = group_devices(devices, names)
    assert _labels(groups) == ["Main House", "Cabin"]


def test_missing_structure_name_falls_back_to_id(monkeypatch):
    devices = [_make_device("Front Cam", "s-unknown")]
    groups = group_devices(devices, {})
    assert _labels(groups) == ["s-unknown"]
