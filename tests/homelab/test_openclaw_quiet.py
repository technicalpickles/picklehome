"""Tests for homelab/scripts/openclaw-quiet.sh, using stub docker and openclaw on PATH.

The stub docker drops `exec <container>` and runs the rest locally, so the real
in-container `sh -c` pipeline (openclaw | node) runs against a stub openclaw that
prints canned session JSON. Needs node on PATH, as the real image has it.
"""
import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "homelab" / "scripts" / "openclaw-quiet.sh"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _stub(path, body):
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def stubs(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    sessions = tmp_path / "sessions.json"
    docker_args = tmp_path / "docker_args"
    _stub(bindir / "docker", (
        f'echo "$*" > {docker_args}\n'
        '[ -z "${FAKE_DOCKER_FAIL:-}" ] || { echo "Error: No such container: $2" >&2; exit 1; }\n'
        'shift 2\n'
        'exec "$@"\n'
    ))
    openclaw_args = tmp_path / "openclaw_args"
    _stub(bindir / "openclaw", f'echo "$*" > {openclaw_args}\ncat {sessions}\n')
    return {"bin": bindir, "sessions": sessions, "docker_args": docker_args,
            "openclaw_args": openclaw_args}


def _session(key, age_s, kind="direct", status="done"):
    updated = int((time.time() - age_s) * 1000)
    return {"key": key, "kind": kind, "status": status, "updatedAt": updated,
            "lastInteractionAt": updated, "agentId": "main"}


def _run(stubs, sessions, *args, **env_extra):
    stubs["sessions"].write_text(json.dumps(
        {"sessions": sessions, "activeMinutes": 5, "count": len(sessions)}))
    env = {
        "PATH": f"{stubs['bin']}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/"),
        **{k: str(v) for k, v in env_extra.items()},
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
    )


def test_quiet_with_no_sessions(stubs):
    r = _run(stubs, [])
    assert r.returncode == 0
    assert r.stdout.strip() == "quiet: no Brent session activity in the last 5 min"


def test_heartbeat_sessions_count_as_quiet(stubs):
    r = _run(stubs, [_session("agent:main:heartbeat:main", 20, status=None)])
    assert r.returncode == 0
    assert r.stdout.startswith("quiet:")


def test_busy_exits_75_and_lists_newest_first(stubs):
    sessions = [
        _session("agent:main:telegram:direct:old", 200),
        _session("agent:main:heartbeat:main", 5, status=None),
        _session("agent:main:telegram:direct:new", 30, status="running"),
    ]
    r = _run(stubs, sessions)
    assert r.returncode == 75
    lines = r.stdout.splitlines()
    assert lines[0] == "BUSY: 2 session(s) active in the last 5 min:"
    assert lines[1].startswith("    agent:main:telegram:direct:new  kind=direct  status=running  last activity ")
    assert lines[2].startswith("    agent:main:telegram:direct:old  kind=direct  status=done  last activity ")
    assert "heartbeat" not in r.stdout
    assert "HOMELAB_DEPLOY_EVEN_IF_BUSY=1 just deploy-<service>" in r.stderr


def test_override_prints_busy_block_and_exits_0(stubs):
    r = _run(stubs, [_session("agent:main:telegram:direct:x", 10)], HOMELAB_DEPLOY_EVEN_IF_BUSY=1)
    assert r.returncode == 0
    assert r.stdout.startswith("BUSY: 1 session(s)")
    assert r.stdout.rstrip().endswith("proceeding anyway (HOMELAB_DEPLOY_EVEN_IF_BUSY=1)")


def test_empty_override_does_not_override(stubs):
    r = _run(stubs, [_session("agent:main:telegram:direct:x", 10)], HOMELAB_DEPLOY_EVEN_IF_BUSY="")
    assert r.returncode == 75


def test_docker_failure_warns_and_exits_0(stubs):
    r = _run(stubs, [], FAKE_DOCKER_FAIL=1, OPENCLAW_CONTAINER="gone-1")
    assert r.returncode == 0
    assert r.stdout.strip() == (
        "WARNING: could not list openclaw sessions in gone-1 (gateway down?); treating as quiet")


@pytest.mark.parametrize("args, env, expected", [
    (["12"], {}, "12"),
    ([], {"HOMELAB_DEPLOY_QUIET_MINUTES": 7}, "7"),
    ([], {}, "5"),
])
def test_window_comes_from_arg_then_env_then_default(stubs, args, env, expected):
    _run(stubs, [], *args, **env)
    assert stubs["openclaw_args"].read_text().split() == [
        "sessions", "--json", "--all-agents", "--active", expected]


def test_container_name_is_configurable(stubs):
    _run(stubs, [], OPENCLAW_CONTAINER="dev-vm-openclaw-1")
    assert stubs["docker_args"].read_text().startswith("exec dev-vm-openclaw-1 ")
