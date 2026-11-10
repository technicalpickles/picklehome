"""Tests for homelab/services/bugsink/verify.sh, using stub executables on PATH.

The script runs on picklelab and must only read state, so the stubs log every call
and a test asserts nothing mutating ran.
"""
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "homelab" / "services" / "bugsink"
VERIFY = SERVICE / "verify.sh"


def _pinned_version() -> str:
    m = re.search(r"image: bugsink/bugsink:([^@\s]+)@sha256:", (SERVICE / "compose.yaml").read_text())
    assert m, "compose.yaml must pin bugsink/bugsink by version and digest"
    return m.group(1)


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def host(tmp_path):
    """A fake picklelab: stub curl/docker/systemctl and a service dir with the real compose.yaml."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    service_dir = tmp_path / "svc"
    service_dir.mkdir()
    (service_dir / ".env.build").write_text("BUGSINK_PORT=9999\nBUGSINK_BASE_URL=https://bugsink.example\n")
    shutil.copy(SERVICE / "compose.yaml", service_dir / "compose.yaml")

    _stub(bindir / "curl", f'echo "curl $*" >> {log}\n'
          '[ -n "$CURL_FAIL" ] && { echo "curl: (7) refused" >&2; exit 7; }\nexit 0\n')
    _stub(bindir / "docker", f'echo "docker $*" >> {log}\n'
          'case "$*" in\n'
          '  "exec "*) [ -n "$VERSION_FAIL" ] && { echo "No such container" >&2; exit 1; }; echo "${RUNNING_VERSION}" ;;\n'
          '  "inspect "*) echo "${DB_HEALTH:-healthy}" ;;\n'
          'esac\n')
    _stub(bindir / "systemctl", f'echo "systemctl $*" >> {log}\necho "${{TIMER_STATE:-active}}"\n')
    return {"bin": bindir, "log": log, "svc": service_dir}


def _run_verify(host, **env_extra):
    env = {
        "PATH": f"{host['bin']}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/"),
        "SERVICE_DIR": str(host["svc"]),
        "RUNNING_VERSION": _pinned_version(),
        **env_extra,
    }
    # Feed the script on stdin the way `just bugsink-verify` does over ssh.
    return subprocess.run(["bash", "-s"], input=VERIFY.read_text(),
                          env=env, capture_output=True, text=True, timeout=30)


def test_all_checks_pass(host):
    r = _run_verify(host)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "http://127.0.0.1:9999/health/ready" in r.stdout  # port comes from .env.build
    assert f"pinned: {_pinned_version()}" in r.stdout
    assert "All bugsink checks passed." in r.stdout


def test_health_failure_fails_the_run(host):
    r = _run_verify(host, CURL_FAIL="1")
    assert r.returncode == 1
    assert "FAIL: /health/ready did not answer" in r.stdout


def test_version_drift_fails(host):
    r = _run_verify(host, RUNNING_VERSION="2.5.0")
    assert r.returncode == 1
    assert "running version 2.5.0 is not the pinned" in r.stdout


def test_missing_container_fails(host):
    r = _run_verify(host, VERSION_FAIL="1")
    assert r.returncode == 1
    assert "could not run bugsink-show-version" in r.stdout


def test_unhealthy_db_fails(host):
    r = _run_verify(host, DB_HEALTH="unhealthy")
    assert r.returncode == 1
    assert "Postgres health is 'unhealthy'" in r.stdout


def test_inactive_vacuum_timer_fails(host):
    r = _run_verify(host, TIMER_STATE="inactive")
    assert r.returncode == 1
    assert "vacuum timer is not active" in r.stdout


def test_only_reads_state(host):
    _run_verify(host)
    calls = host["log"].read_text().splitlines()
    assert "docker exec bugsink-web-1 bugsink-show-version" in calls
    for line in calls:
        if line.startswith("docker "):
            assert line.startswith(("docker exec bugsink-web-1 bugsink-show-version", "docker inspect ")), line
        if line.startswith("systemctl "):
            assert line.startswith("systemctl is-active "), line
    assert not any(" op " in f" {c}" or "compose" in c for c in calls)


def test_vacuum_unit_and_backup_target_the_same_names_compose_creates():
    # compose.yaml fixes the project name, so the containers are bugsink-web-1 and
    # bugsink-db-1. The vacuum unit and verify.sh use the first; backup.sh finds the
    # second by project label and service name.
    compose = (SERVICE / "compose.yaml").read_text()
    assert re.search(r"^name: bugsink$", compose, re.M)
    assert re.search(r"^  db:$", compose, re.M) and re.search(r"^  web:$", compose, re.M)
    assert "docker exec bugsink-web-1 " in (SERVICE / "bugsink-vacuum.service").read_text()
    backup = (ROOT / "homelab" / "services" / "backup" / "backup.sh").read_text()
    assert 'dump_postgres "bugsink" "bugsink"' in backup
    assert '--exclude "$DATA_DIR/bugsink/db"' in backup


def test_every_env_var_compose_needs_is_listed_or_written_by_deploy():
    compose = (SERVICE / "compose.yaml").read_text()
    required = set(re.findall(r"\$\{(BUGSINK_[A-Z_]+):\?", compose))
    listed = {line.strip() for line in (SERVICE / ".env.vars").read_text().splitlines()
              if line.strip() and not line.startswith("#")}
    from_deploy = {"BUGSINK_PORT", "BUGSINK_BASE_URL"}
    assert required == listed | from_deploy
    template = (ROOT / ".env.template").read_text()
    for var in listed:
        assert re.search(rf"^{var}=\{{\{{ op://picklehome/Bugsink/", template, re.M), var
