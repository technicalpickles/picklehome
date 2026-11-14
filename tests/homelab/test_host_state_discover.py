"""Tests for homelab/services/host-state/{discover,collect,picklelab.conf}."""
import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parents[2] / "homelab" / "services" / "host-state"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "host_state"


def _stub(path, body):
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def world(tmp_path):
    unit_dir = tmp_path / "etc-systemd"
    unit_dir.mkdir()
    prefix = f"{tmp_path}/opt/homelab/"
    (tmp_path / "opt" / "homelab" / "services").mkdir(parents=True)
    for name in ["backup.timer", "backup.service", "openclaw.service",
                 "notify-failure@.service", "Bad_Name.service"]:
        target = tmp_path / "opt" / "homelab" / "services" / name
        target.write_text("[Timer]\n" if name.endswith(".timer") else "[Service]\n")
        (unit_dir / name).symlink_to(target)
    (unit_dir / "hand.timer").write_text("[Timer]\n")
    (unit_dir / "hand.service").write_text("[Service]\n")
    (unit_dir / "smartd.service").symlink_to("/usr/lib/systemd/system/smartd.service")
    sites = tmp_path / "sites.conf"
    sites.write_text("# comment\n\nalpha https://alpha.example/health\nbeta https://beta.example/\n")
    return {"units": unit_dir, "sites": sites, "wrappers": tmp_path / "wrappers", "tmp": tmp_path,
            "prefix": prefix}


def _discover(world, **extra):
    env = {
        "PATH": os.environ["PATH"],
        "HOST_STATE_UNIT_DIR": str(world["units"]),
        "HOST_STATE_LINK_PREFIX": world["prefix"],
        "HOST_STATE_SITES": str(world["sites"]),
        **extra,
    }
    return subprocess.run(["bash", str(DIR / "discover"), str(world["wrappers"])],
                          env=env, capture_output=True, text=True, timeout=30)


def _listing(world):
    return {p.name: p.read_text() for p in sorted(world["wrappers"].iterdir())}


def test_discovers(world):
    r = _discover(world)
    assert r.returncode == 0 and r.stdout == ""
    listing = _listing(world)
    assert sorted(listing) == ["runtime-docker", "site-alpha", "site-beta", "timer-backup", "unit-openclaw"]
    assert f"exec {DIR}/runtime-check" in listing["runtime-docker"]
    assert f"exec {DIR}/timer-check backup.timer" in listing["timer-backup"]
    assert f"exec {DIR}/unit-check openclaw.service" in listing["unit-openclaw"]
    assert f"exec {DIR}/site-check https://alpha.example/health" in listing["site-alpha"]
    for p in world["wrappers"].iterdir():
        assert p.stat().st_mode & stat.S_IXUSR
    assert not list(world["tmp"].glob("wrappers.*"))


def test_bad_stem(world):
    r = _discover(world)
    assert r.returncode == 0
    assert "skipping Bad_Name" in r.stderr
    assert "unit-Bad_Name" not in _listing(world)


def test_converges(world):
    _discover(world)
    first = _listing(world)
    assert _discover(world).returncode == 0
    assert _listing(world) == first


def test_removed_unit(world):
    _discover(world)
    assert "unit-openclaw" in _listing(world)
    (world["units"] / "openclaw.service").unlink()
    _discover(world)
    assert "unit-openclaw" not in _listing(world)


def test_timer_unit_key(world):
    target = world["tmp"] / "opt" / "homelab" / "services" / "other.service"
    target.write_text("[Service]\n")
    (world["units"] / "other.service").symlink_to(target)
    (world["tmp"] / "opt" / "homelab" / "services" / "backup.timer").write_text(
        "[Timer]\nUnit=other.service\n")
    assert _discover(world).returncode == 0
    listing = _listing(world)
    assert "timer-backup" in listing
    assert "unit-other" not in listing
    assert "unit-backup" in listing


def test_timer_unit_key_default_service(world):
    _discover(world)
    assert "unit-backup" not in _listing(world)


def test_collect_end_to_end(world):
    bindir = world["tmp"] / "bin"
    bindir.mkdir()
    _stub(bindir / "systemctl", """\
printf 'LoadState=loaded\\nActiveState=active\\nSubState=running\\nResult=success\\n'
printf 'NextElapseUSecRealtime=Wed 2026-11-11 03:03:27 UTC\\nNextElapseUSecMonotonic=0\\n'
printf 'Unit=backup.service\\n'
printf 'MainPID=0\\nActiveEnterTimestampMonotonic=1\\n'
""")
    _stub(bindir / "curl", "printf 200\n")
    checks = world["tmp"] / "checks"
    assert _discover(world, PATH=f"{bindir}:{os.environ['PATH']}").returncode == 0
    world["wrappers"].rename(checks)
    out = world["tmp"] / "out" / "picklelab.json"
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/"),
        "HOST_STATE_OUT": str(out),
        "HOST_STATE_CHECK_DIR": str(checks),
    }
    r = subprocess.run(["bash", str(DIR / "collect"), str(DIR / "picklelab.conf")],
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    report = json.loads(out.read_text())
    assert report["host"] == "picklelab"
    assert report["interval_seconds"] == 300
    assert [c["name"] for c in report["checks"]] == sorted(p.name for p in checks.iterdir())
    assert len(report["checks"]) == 5
    assert all(c["status"] == 0 for c in report["checks"]), report


def test_collect_is_a_copy():
    commit = re.search(r"^SOURCE_COMMIT=(\S+)$", (FIXTURES / "collect.upstream.commit").read_text(), re.M).group(1)
    lines = (DIR / "collect").read_text().splitlines(keepends=True)
    assert lines[0].startswith("#!")
    header = []
    rest = lines[1:]
    while rest and rest[0].startswith("#"):
        header.append(rest.pop(0))
    assert commit in "".join(header)
    assert lines[0] + "".join(rest) == (FIXTURES / "collect.upstream").read_text()


def test_dangling_timer_link(world):
    (world["units"] / "gone.timer").symlink_to(world["tmp"] / "opt" / "homelab" / "services" / "gone.timer")
    r = _discover(world)
    assert r.returncode == 0, r.stderr
    assert f"exec {DIR}/timer-check gone.timer" in _listing(world)["timer-gone"]


def test_url_with_ampersand_is_quoted(world):
    world["sites"].write_text("amp https://x.example/a?b=1&c=2\n")
    bindir = world["tmp"] / "bin"
    bindir.mkdir()
    _stub(bindir / "site-check", 'printf "%s\\n" "$@"; exit 2\n')
    assert _discover(world).returncode == 0
    wrapper = world["wrappers"] / "site-amp"
    text = wrapper.read_text().replace(str(DIR / "site-check"), str(bindir / "site-check"))
    wrapper.write_text(text)
    r = subprocess.run(["bash", str(wrapper)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2
    assert r.stdout == "https://x.example/a?b=1&c=2\n"


def test_sites_line_without_url_skipped(world):
    world["sites"].write_text("lonely\nbeta https://beta.example/\n")
    r = _discover(world)
    assert r.returncode == 0
    assert "discover: skipping lonely: no url" in r.stderr
    assert sorted(p for p in _listing(world) if p.startswith("site-")) == ["site-beta"]


def test_sites_last_line_without_newline(world):
    world["sites"].write_text("alpha https://alpha.example/")
    assert _discover(world).returncode == 0
    assert "site-alpha" in _listing(world)


def _service(world, name, body):
    target = world["tmp"] / "opt" / "homelab" / "services" / f"{name}.service"
    target.write_text(body)
    (world["units"] / f"{name}.service").symlink_to(target)


def test_oneshot_without_remain_after_exit_skipped(world):
    _service(world, "job", "[Service]\nType=oneshot\nExecStart=/bin/true\n")
    r = _discover(world)
    assert r.returncode == 0 and "job" not in r.stderr
    assert "unit-job" not in _listing(world)


@pytest.mark.parametrize("value", ["yes", "true", "1", "on", "YES", "True"])
def test_oneshot_with_remain_after_exit_kept(world, value):
    _service(world, "stack", f"[Service]\nType=oneshot\nRemainAfterExit={value}\n")
    assert _discover(world).returncode == 0
    assert "unit-stack" in _listing(world)


def test_oneshot_remain_after_exit_no_skipped(world):
    _service(world, "job", "[Service]\nType=oneshot\nRemainAfterExit=no\n")
    assert _discover(world).returncode == 0
    assert "unit-job" not in _listing(world)


def test_service_without_type_kept(world):
    _service(world, "daemon", "[Service]\nExecStart=/bin/true\n")
    assert _discover(world).returncode == 0
    assert "unit-daemon" in _listing(world)


def test_oneshot_keys_outside_service_section_ignored(world):
    _service(world, "odd", "[Unit]\nType=oneshot\n[Service]\nExecStart=/bin/true\n")
    assert _discover(world).returncode == 0
    assert "unit-odd" in _listing(world)


def test_dangling_service_link_kept(world):
    (world["units"] / "gone.service").symlink_to(world["tmp"] / "opt" / "homelab" / "services" / "gone.service")
    r = _discover(world)
    assert r.returncode == 0 and "gone" not in r.stderr
    assert "unit-gone" in _listing(world)
