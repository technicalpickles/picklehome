"""Scenario tests: the agent switch over real HTTP against FakeWoodpecker.

Binds a loopback port. If the sandbox refuses the bind (PermissionError), run
these with the sandbox off; they touch only 127.0.0.1.
"""

import json
from pathlib import Path

import pytest

from tests.homelab.fake_woodpecker import FakeWoodpecker
from tests.homelab.test_woodpecker_agent_switch import sw

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "woodpecker" / "agents.json"
DEFAULTS = {"!host": "laptop"}
T0 = 1_000_000
STALE = 300


def seed(laptop_contact):
    return [
        {"id": 1, "name": "laptop-vm", "last_contact": laptop_contact,
         "no_schedule": False, "filters": dict(DEFAULTS)},
        {"id": 2, "name": "picklelab", "last_contact": T0,
         "no_schedule": False, "filters": {}},
    ]


@pytest.fixture
def server():
    made = []

    def make(agents):
        fw = FakeWoodpecker(agents)
        fw.base = fw.start()
        made.append(fw)
        return fw

    yield make
    for fw in made:
        fw.stop()


def tick(fw, now, **kw):
    cfg = sw.Config("laptop-vm", "picklelab", stale_after=STALE)
    return sw.run(cfg, fw.base, "tok", dry_run=kw.get("dry_run", False),
                  reset=kw.get("reset", False), now=now)


def state(fw):
    return (
        fw.agents[1]["filters"], fw.agents[1]["no_schedule"], fw.agents[2]["no_schedule"]
    )


def test_laptop_wakes_then_sleeps(server):
    fw = server(seed(0))
    tick(fw, T0)
    assert state(fw) == (DEFAULTS, False, False)  # never connected: defaults

    fw.agents[1]["last_contact"] = T0 + 60  # laptop connects
    tick(fw, T0 + 60)
    assert state(fw) == ({}, False, True)
    n = len(fw.patch_log)
    tick(fw, T0 + 120)  # laptop keeps pinging: steady state, no patches
    fw.agents[1]["last_contact"] = T0 + 120
    tick(fw, T0 + 180)
    assert len(fw.patch_log) == n

    # laptop sleeps: last_contact frozen at T0+120
    tick(fw, T0 + 120 + STALE)  # boundary, still fresh
    assert state(fw) == ({}, False, True)
    tick(fw, T0 + 120 + STALE + 1)
    assert state(fw) == (DEFAULTS, False, False)
    assert fw.invariant_violations == []


def test_converges_within_one_tick_of_a_change(server):
    fw = server(seed(T0))
    tick(fw, T0 + 5)
    assert state(fw) == ({}, False, True)
    tick(fw, T0 + 5 + STALE + 1)
    assert state(fw) == (DEFAULTS, False, False)


def test_no_flap_inside_stale_window(server):
    fw = server(seed(T0))
    tick(fw, T0)
    n = len(fw.patch_log)
    for i in range(1, 10):
        fw.agents[1]["last_contact"] = T0 + i * 100  # jittery but within window
        tick(fw, T0 + i * 100 + 50)
    assert len(fw.patch_log) == n


def test_midrun_failure_then_recovery(server):
    fw = server(seed(T0))
    tick(fw, T0)  # -> laptop preferred
    fw.agents[1]["last_contact"] = T0
    # laptop stale: transition is [picklelab enable, laptop restore]; let the
    # first PATCH through and fail the second
    stale_now = T0 + STALE + 1
    cfg = sw.Config("laptop-vm", "picklelab", stale_after=STALE)
    patches = sw.decide(list(fw.agents.values()), stale_now, cfg)
    sw.patch_agent(fw.base, "tok", patches[0])
    fw.fail_next("PATCH", 500)
    with pytest.raises(RuntimeError, match="500"):
        sw.patch_agent(fw.base, "tok", patches[1])
    assert fw.agents[2]["no_schedule"] is False  # half-applied: picklelab schedulable
    tick(fw, stale_now + 60)  # next tick completes
    assert state(fw) == (DEFAULTS, False, False)
    assert fw.invariant_violations == []


def test_bad_token_exits_1_and_changes_nothing(server, monkeypatch, capsys):
    fw = server(seed(T0))
    monkeypatch.setenv("WOODPECKER_API_TOKEN", "wrong")
    monkeypatch.setenv("WOODPECKER_URL", fw.base)
    monkeypatch.setenv("LAPTOP_AGENT_NAME", "laptop-vm")
    monkeypatch.setenv("PICKLELAB_AGENT_NAME", "picklelab")
    assert sw.main([]) == 1
    assert "401" in capsys.readouterr().err
    assert fw.patch_log == []


def test_reset_from_laptop_preferred(server):
    fw = server(seed(T0))
    tick(fw, T0)
    assert state(fw) == ({}, False, True)
    tick(fw, T0, reset=True)
    assert state(fw) == (DEFAULTS, False, False)
    assert fw.invariant_violations == []


def test_dry_run_leaves_server_untouched(server, capsys):
    fw = server(seed(T0))
    tick(fw, T0, dry_run=True)
    assert fw.patch_log == []
    assert "would PATCH" in capsys.readouterr().out


@pytest.mark.skipif(not FIXTURE.exists(), reason="real-API fixture captured in verify-api-fields")
def test_fixture_roundtrip():
    agents = json.loads(FIXTURE.read_text())
    names = [a["name"] for a in agents]
    cfg = sw.Config(laptop_name=names[0], picklelab_name=names[-1])
    sw.decide(agents, T0, cfg)  # no KeyError on the real shape
