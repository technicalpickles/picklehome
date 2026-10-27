"""Tests for homelab/devhost/golden.sh, using a stub orb on PATH.

The stub logs every argv line to a file and answers `orb list -q` from a
fixture, so we can check which orb calls golden.sh makes (and in what order)
without touching OrbStack. golden-inside.sh is only checked for shape here; its
real run is the Step 5 build.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

DEVHOST = Path(__file__).resolve().parents[2] / "homelab" / "devhost"
GOLDEN = DEVHOST / "golden.sh"
INSIDE = DEVHOST / "golden-inside.sh"


@pytest.fixture
def stub(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    argv_log = tmp_path / "argv"
    machines = tmp_path / "machines"
    machines.write_text("")
    image_env = tmp_path / "openclaw.image.env"
    image_env.write_text("OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:9999.1.1\n")
    orb = bindir / "orb"
    # `orb list -q` prints one machine name per line (the real format).
    orb.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {argv_log}\n'
        f'if [ "$1 $2" = "list -q" ]; then cat {machines}; fi\n'
        "exit 0\n"
    )
    orb.chmod(orb.stat().st_mode | stat.S_IEXEC)
    return {"bin": bindir, "argv": argv_log, "machines": machines, "image_env": image_env}


def _run(stub, **env_extra):
    env = {
        "PATH": f"{stub['bin']}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/"),
        "OPENCLAW_IMAGE_ENV_FILE": str(stub["image_env"]),
        **{k: str(v) for k, v in env_extra.items()},
    }
    return subprocess.run(
        ["bash", str(GOLDEN)], env=env, capture_output=True, text=True, timeout=30
    )


def _argv(stub):
    return stub["argv"].read_text().splitlines() if stub["argv"].exists() else []


def _index(lines, needle):
    return next(i for i, line in enumerate(lines) if needle in line)


def test_golden_creates_when_absent_and_stops(stub):
    stub["machines"].write_text("woodpecker-agent\nopenclaw\n")
    r = _run(stub)
    assert r.returncode == 0, r.stderr
    lines = _argv(stub)
    create = _index(lines, "create ubuntu:noble picklelab-golden")
    inside = _index(lines, "-m picklelab-golden")
    stop = _index(lines, "stop picklelab-golden")
    assert create < inside < stop
    # Isolation flags land on the golden so clones inherit them.
    assert "--isolated" in lines[create]
    assert "--isolate-network" in lines[create]
    assert "--forward-ssh-agent" in lines[create]
    # The pinned image reaches the machine, and the inside script rides along.
    assert "OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:9999.1.1" in lines[inside]
    assert "docker pull" in stub["argv"].read_text()
    # Stop must name the machine: a bare `orb stop` stops all of OrbStack.
    assert lines[stop].strip() == "stop picklelab-golden"


def test_golden_reuses_when_present(stub):
    stub["machines"].write_text("openclaw\npicklelab-golden\n")
    r = _run(stub)
    assert r.returncode == 0, r.stderr
    lines = _argv(stub)
    assert not any(" create " in f" {line} " for line in lines)
    assert any("-m picklelab-golden" in line for line in lines)
    assert any(line.strip() == "stop picklelab-golden" for line in lines)


def test_golden_does_not_mistake_a_prefix_match_for_present(stub):
    stub["machines"].write_text("picklelab-golden-old\n")
    r = _run(stub)
    assert r.returncode == 0, r.stderr
    assert any("create ubuntu:noble picklelab-golden" in line for line in _argv(stub))


@pytest.mark.parametrize("name", ["picklelab", "woodpecker-agent", "openclaw", ""])
def test_golden_refuses_names_that_are_not_a_golden(stub, name):
    r = _run(stub, GOLDEN_NAME=name)
    assert r.returncode == 1
    assert "refus" in r.stderr.lower()
    assert _argv(stub) == []


def test_golden_fails_when_image_env_missing(stub):
    r = _run(stub, OPENCLAW_IMAGE_ENV_FILE=stub["image_env"].with_name("nope.env"))
    assert r.returncode == 1
    assert "openclaw.image.env" in r.stderr or "nope.env" in r.stderr
    assert _argv(stub) == []


def test_golden_fails_when_image_var_empty(stub):
    stub["image_env"].write_text("# nothing here\n")
    r = _run(stub)
    assert r.returncode == 1
    assert "OPENCLAW_IMAGE" in r.stderr
    assert _argv(stub) == []


def test_golden_stops_even_when_inside_script_fails(stub):
    stub["machines"].write_text("picklelab-golden\n")
    orb = stub["bin"] / "orb"
    orb.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {stub["argv"]}\n'
        f'if [ "$1 $2" = "list -q" ]; then cat {stub["machines"]}; fi\n'
        'case "$*" in *"-m picklelab-golden"*) exit 7;; esac\n'
        "exit 0\n"
    )
    r = _run(stub)
    assert r.returncode == 7
    assert any(line.strip() == "stop picklelab-golden" for line in _argv(stub))


def test_inside_script_runs_the_brief_steps_in_order():
    text = "\n".join(
        line for line in INSIDE.read_text().splitlines() if not line.lstrip().startswith("#")
    )
    order = [
        "apt-get install -y jq git curl nodejs",
        "https://github.com/technicalpickles/picklehome.git",
        "setup-docker.sh",
        "https://tailscale.com/install.sh",
        "setup-deploy-access.sh",
        "docker pull",
        "ssh -T",
        "SKIP: no github ssh, first deploy builds",
    ]
    positions = [text.index(s) for s in order]
    assert positions == sorted(positions)
    # Install only: bringing tailscale up belongs to the clone, not the golden.
    assert "tailscale up" not in text
    assert "setup-tailscale.sh" not in text
