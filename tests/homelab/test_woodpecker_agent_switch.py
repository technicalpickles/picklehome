"""Unit tests for the Woodpecker agent switch decision logic.

The service dir (homelab/services/woodpecker) is not an importable package, so
the module is loaded by path.
"""

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "homelab"
    / "services"
    / "woodpecker"
    / "agent_switch.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("agent_switch", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sw = load_module()

NOW = 1_000_000
DEFAULT_FILTERS = {"!host": "laptop"}


def cfg(**kw):
    return sw.Config(laptop_name="laptop-vm", picklelab_name="picklelab", **kw)


def agent(id_, name, *, last_contact=NOW - 10, no_schedule=False, filters=None):
    return {
        "id": id_,
        "name": name,
        "last_contact": last_contact,
        "no_schedule": no_schedule,
        "filters": dict(filters) if filters is not None else {},
    }


def defaults(laptop_contact=NOW - 10):
    return [
        agent(1, "laptop-vm", last_contact=laptop_contact, filters=DEFAULT_FILTERS),
        agent(2, "picklelab"),
    ]


def laptop_preferred(laptop_contact=NOW - 10):
    return [
        agent(1, "laptop-vm", last_contact=laptop_contact, filters={}),
        agent(2, "picklelab", no_schedule=True),
    ]


def test_laptop_fresh_prefers_laptop():
    patches = sw.decide(defaults(), NOW, cfg())
    assert [p.agent_id for p in patches] == [1, 2]
    assert patches[0].body["filters"] == {}
    assert patches[0].body["no_schedule"] is False
    assert patches[1].body["no_schedule"] is True


def test_laptop_stale_restores_defaults_in_safe_order():
    patches = sw.decide(laptop_preferred(laptop_contact=NOW - 301), NOW, cfg())
    assert [p.agent_id for p in patches] == [2, 1]
    assert patches[0].body["no_schedule"] is False
    assert patches[1].body["filters"] == DEFAULT_FILTERS


def test_boundary_is_fresh():
    patches = sw.decide(defaults(laptop_contact=NOW - 300), NOW, cfg())
    assert [p.agent_id for p in patches] == [1, 2]


def test_never_connected_is_stale():
    assert sw.decide(defaults(laptop_contact=0), NOW, cfg()) == []


def test_laptop_missing_is_stale():
    agents = [agent(2, "picklelab", no_schedule=True)]
    patches = sw.decide(agents, NOW, cfg())
    assert [p.agent_id for p in patches] == [2]
    assert patches[0].body["no_schedule"] is False


def test_converged_is_noop():
    assert sw.decide(laptop_preferred(), NOW, cfg()) == []
    assert sw.decide(defaults(laptop_contact=NOW - 9999), NOW, cfg()) == []


def test_picklelab_missing_raises():
    with pytest.raises(ValueError, match="picklelab"):
        sw.decide([agent(1, "laptop-vm")], NOW, cfg())


def test_picklelab_duplicate_raises():
    agents = [agent(2, "picklelab"), agent(3, "picklelab")]
    with pytest.raises(ValueError, match="picklelab"):
        sw.decide(agents, NOW, cfg())


def test_patch_body_carries_name():
    patches = sw.decide(defaults(), NOW, cfg())
    assert [p.body["name"] for p in patches] == ["laptop-vm", "picklelab"]
