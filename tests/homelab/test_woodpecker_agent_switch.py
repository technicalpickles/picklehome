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


# --- api client and cli ---------------------------------------------------

import io
import json
import urllib.error

BASE = "http://wp.test"
TOKEN = "tok"


class FakeOpener:
    """Records requests; serves the agent list and accepts PATCHes."""

    def __init__(self, agents, fail_patch_on=None, raise_on_get=None):
        self.agents = agents
        self.requests = []
        self.fail_patch_on = fail_patch_on  # 1-based PATCH count that errors
        self.raise_on_get = raise_on_get
        self._patches = 0

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        assert timeout == 10
        assert req.get_header("Authorization") == f"Bearer {TOKEN}"
        if req.get_method() == "GET":
            if self.raise_on_get:
                raise self.raise_on_get
            return _Resp(json.dumps(self.agents))
        self._patches += 1
        if self.fail_patch_on == self._patches:
            raise urllib.error.HTTPError(
                req.full_url, 500, "boom", {}, io.BytesIO(b"server exploded")
            )
        return _Resp("{}")


class _Resp:
    def __init__(self, text):
        self._b = text.encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def patch_requests(op):
    return [r for r in op.requests if r.get_method() == "PATCH"]


def test_run_applies_patches_in_order():
    op = FakeOpener(defaults())
    applied = sw.run(cfg(), BASE, TOKEN, dry_run=False, reset=False, now=NOW, opener=op)
    ps = patch_requests(op)
    assert [r.full_url for r in ps] == [f"{BASE}/api/agents/1", f"{BASE}/api/agents/2"]
    assert json.loads(ps[0].data) == applied[0].body
    assert json.loads(ps[1].data) == applied[1].body


def test_dry_run_sends_no_patch(capsys):
    op = FakeOpener(defaults())
    sw.run(cfg(), BASE, TOKEN, dry_run=True, reset=False, now=NOW, opener=op)
    assert patch_requests(op) == []
    assert "would PATCH" in capsys.readouterr().out


def test_reset_forces_defaults_even_when_laptop_fresh():
    op = FakeOpener(laptop_preferred(laptop_contact=NOW - 1))
    applied = sw.run(cfg(), BASE, TOKEN, dry_run=False, reset=True, now=NOW, opener=op)
    assert [p.agent_id for p in applied] == [2, 1]
    assert applied[0].body["no_schedule"] is False
    assert applied[1].body["filters"] == DEFAULT_FILTERS


def test_http_error_raises_with_status_endpoint_and_body():
    err = urllib.error.HTTPError(f"{BASE}/api/agents", 401, "no", {}, io.BytesIO(b"bad token"))
    op = FakeOpener(defaults(), raise_on_get=err)
    with pytest.raises(RuntimeError) as e:
        sw.run(cfg(), BASE, TOKEN, dry_run=False, reset=False, now=NOW, opener=op)
    msg = str(e.value)
    assert "401" in msg and "/api/agents" in msg and "bad token" in msg


def test_partial_failure_propagates_after_first_patch():
    op = FakeOpener(defaults(), fail_patch_on=2)
    with pytest.raises(RuntimeError, match="500"):
        sw.run(cfg(), BASE, TOKEN, dry_run=False, reset=False, now=NOW, opener=op)
    assert len(patch_requests(op)) == 2  # first applied, second attempted


def _env(monkeypatch, **extra):
    base = {
        "WOODPECKER_API_TOKEN": TOKEN,
        "WOODPECKER_URL": BASE,
        "LAPTOP_AGENT_NAME": "laptop-vm",
        "PICKLELAB_AGENT_NAME": "picklelab",
    }
    base.update(extra)
    for k, v in base.items():
        monkeypatch.setenv(k, v)


def test_main_exit_1_on_error_and_0_on_success(monkeypatch, capsys):
    _env(monkeypatch)
    err = urllib.error.URLError("unreachable")
    monkeypatch.setattr(sw, "_urlopen", FakeOpener(defaults(), raise_on_get=err))
    assert sw.main([]) == 1
    assert "unreachable" in capsys.readouterr().err
    monkeypatch.setattr(sw, "_urlopen", FakeOpener(defaults(laptop_contact=0)))
    assert sw.main([]) == 0


def test_main_requires_token(monkeypatch, capsys):
    _env(monkeypatch)
    monkeypatch.delenv("WOODPECKER_API_TOKEN")
    assert sw.main([]) == 1
    assert "WOODPECKER_API_TOKEN" in capsys.readouterr().err
