"""Tests for the brineworks-server post-deploy checks, using stub executables on PATH.

Covers homelab/services/brineworks-server/verify.sh (runs on picklelab) and
scripts/brineworks-skills-check (runs on the Mac after a deploy). Both must only
read state, so the stubs log every call and a test asserts nothing mutating ran.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "homelab" / "services" / "brineworks-server" / "verify.sh"
SKILLS_CHECK = ROOT / "scripts" / "brineworks-skills-check"

HEALTH_OK = '{"status":"ok","env":"production","sha":"abc1234"}'


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def host(tmp_path):
    """A fake picklelab: stub curl/op/docker/git/systemctl, a service dir and a token file."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    service_dir = tmp_path / "svc"
    service_dir.mkdir()
    (service_dir / ".env.build").write_text("BRINEWORKS_SERVER_PORT=9999\n")
    token = tmp_path / "op-token"
    token.write_text("OP_SERVICE_ACCOUNT_TOKEN=fake\n")

    _stub(bindir / "curl", f'echo "curl $*" >> {log}\n'
          '[ -n "$CURL_FAIL" ] && { echo "curl: (22) 503" >&2; exit 22; }\n'
          "if [ -n \"$HEALTH_BODY\" ]; then echo \"$HEALTH_BODY\"; else echo '" + HEALTH_OK + "'; fi\n")
    # op run --env-file=X -- <cmd...>: run the command, as the real one does.
    _stub(bindir / "op", f'echo "op $*" >> {log}\nwhile [ "$1" != "--" ]; do shift; done; shift\nexec "$@"\n')
    _stub(bindir / "docker", f'echo "docker $*" >> {log}\n'
          'case "$*" in\n'
          '  *" exec "*) [ -n "$ALEMBIC_FAIL" ] && exit 1; echo "${ALEMBIC_OUT:-0010 (head)}" ;;\n'
          '  *" logs "*) [ -n "$LOGS_FAIL" ] && { echo "no such service" >&2; exit 1; }; printf "%s\\n" "${LOGS_OUT:-INFO started}" ;;\n'
          'esac\n')
    _stub(bindir / "git", f'echo "git $*" >> {log}\necho "${{DEPLOYED_SHA:-abc1234}}"\n')
    _stub(bindir / "systemctl", f'echo "systemctl $*" >> {log}\n')
    return {"bin": bindir, "log": log, "svc": service_dir, "token": token}


def _run_verify(host, *args, **env_extra):
    env = {
        "PATH": f"{host['bin']}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/"),
        "SERVICE_DIR": str(host["svc"]),
        "TOKEN_FILE": str(host["token"]),
        "BRINEWORKS_REPO": "/opt/brineworks",
        **env_extra,
    }
    # Feed the script on stdin the way `just brineworks-server-verify` does over ssh.
    return subprocess.run(["bash", "-s", "--", *args], input=VERIFY.read_text(),
                          env=env, capture_output=True, text=True, timeout=30)


def test_all_checks_pass(host):
    r = _run_verify(host)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "http://127.0.0.1:9999/health" in r.stdout  # port comes from .env.build
    assert "running sha matches" in r.stdout
    assert "alembic is at head" in r.stdout
    assert "no Gmail/credential errors" in r.stdout
    assert "All brineworks-server checks passed." in r.stdout


def test_health_failure_fails_the_run(host):
    r = _run_verify(host, CURL_FAIL="1")
    assert r.returncode == 1
    assert "FAIL: /health did not answer" in r.stdout


def test_sha_mismatch_fails(host):
    r = _run_verify(host, DEPLOYED_SHA="def5678")
    assert r.returncode == 1
    assert "doesn't match" in r.stdout


def test_alembic_not_at_head_fails(host):
    r = _run_verify(host, ALEMBIC_OUT="0009")
    assert r.returncode == 1
    assert "alembic is not at head" in r.stdout


def test_credential_errors_in_logs_fail_and_are_shown(host):
    r = _run_verify(host, LOGS_OUT="ERROR Gmail credentials unavailable in production: AuthError: no token")
    assert r.returncode == 1
    assert "Gmail credentials unavailable in production" in r.stdout
    assert "FAIL: Gmail/credential errors" in r.stdout


def test_unreadable_logs_is_a_failure_not_a_pass(host):
    r = _run_verify(host, LOGS_FAIL="1")
    assert r.returncode == 1
    assert "could not read the server logs" in r.stdout


def test_since_argument_reaches_docker_logs(host):
    _run_verify(host, "2h")
    assert "--since 2h" in host["log"].read_text()


def test_only_reads_state(host):
    _run_verify(host)
    calls = host["log"].read_text()
    assert "systemctl" not in calls
    docker_calls = [line for line in calls.splitlines() if line.startswith("docker ")]
    assert docker_calls, "expected docker to be called"
    for line in docker_calls:
        assert " exec -T server alembic current" in line or " logs " in line, line
        for verb in (" up", " down", " restart", " build", " stop", " rm ", " run "):
            assert verb not in line, line


# --- scripts/brineworks-skills-check -------------------------------------------------

@pytest.fixture
def checkout(tmp_path):
    """A fake brineworks checkout whose sync-skills.sh exits with $SYNC_RC."""
    bw = tmp_path / "brineworks"
    (bw / "scripts").mkdir(parents=True)
    _stub(bw / "scripts" / "sync-skills.sh",
          'echo "args: $*" >> "$SYNC_LOG"\n'
          'case "$SYNC_RC" in\n'
          '  0) echo "brineworks-tasks: in sync" ;;\n'
          '  1) echo "--- big diff ---"; echo "brineworks-tasks: in sync"; echo "triage: DRIFT" >&2 ;;\n'
          '  2) echo "no openclaw-workspace checkout at /nope (set OPENCLAW_WORKSPACE)" >&2 ;;\n'
          'esac\n'
          'exit "$SYNC_RC"\n')
    return {"bw": bw, "log": tmp_path / "sync.log"}


def _run_check(checkout, **env_extra):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"),
           "BRINEWORKS_DIR": str(checkout["bw"]), "SYNC_LOG": str(checkout["log"]),
           **env_extra}
    return subprocess.run([str(SKILLS_CHECK)], env=env, capture_output=True, text=True, timeout=30)


def test_skills_in_sync(checkout):
    r = _run_check(checkout, SYNC_RC="0")
    assert r.returncode == 0
    assert "Skills in sync" in r.stdout
    assert checkout["log"].read_text().strip() == "args: --check"  # read-only mode only


def test_drift_warns_but_never_fails(checkout):
    r = _run_check(checkout, SYNC_RC="1")
    assert r.returncode == 0
    assert "WARNING" in r.stdout and "stale" in r.stdout
    assert "triage: DRIFT" in r.stdout
    assert "big diff" not in r.stdout  # drift names, not the whole diff


def test_missing_brineworks_checkout_is_skipped(checkout, tmp_path):
    r = _run_check(checkout, SYNC_RC="0", BRINEWORKS_DIR=str(tmp_path / "nowhere"))
    assert r.returncode == 0
    assert "Skipping" in r.stdout and "BRINEWORKS_DIR" in r.stdout


def test_missing_workspace_checkout_is_skipped(checkout):
    # sync-skills.sh exits 2 when it can't find the openclaw-workspace checkout.
    r = _run_check(checkout, SYNC_RC="2")
    assert r.returncode == 0
    assert "Skipping" in r.stdout and "OPENCLAW_WORKSPACE" in r.stdout
