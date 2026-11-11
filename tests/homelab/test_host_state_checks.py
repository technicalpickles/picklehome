"""Tests for homelab/services/host-state/{timer,unit,site}-check, with stub systemctl and curl on PATH.

The stub systemctl answers `show` from tmp_path/units/<unit> (key=value lines),
printing only the requested -p properties like the real one. The stub curl prints
FAKE_CURL_CODE, or exits 28 when FAKE_CURL_TIMEOUT is set.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parents[2] / "homelab" / "services" / "host-state"
NOW = 1_800_000_000


def _stub(path, body):
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    units = tmp_path / "units"
    bindir.mkdir()
    units.mkdir()
    _stub(bindir / "systemctl", f"""\
[ -z "${{FAKE_SYSTEMCTL_FAIL:-}}" ] || {{ echo "Failed to connect to bus" >&2; exit 1; }}
[ "$1" = show ] || exit 64
props=$3
unit=${{@: -1}}
[ -f {units}/$unit ] || {{ printf 'LoadState=not-found\\nActiveState=inactive\\n'; exit 0; }}
grep -E "^($(tr , '|' <<<"$props"))=" {units}/$unit
""")
    _stub(bindir / "curl", """\
case " $* " in *" -L "*) ;; *) echo "curl called without -L" >&2; exit 2;; esac
[ -z "${FAKE_CURL_TIMEOUT:-}" ] || exit 28
printf '%s' "$FAKE_CURL_CODE"
""")
    return {"bin": bindir, "units": units}


def _unit(env, name, **props):
    props.setdefault("LoadState", "loaded")
    (env["units"] / name).write_text("".join(f"{k}={v}\n" for k, v in props.items()))


def _run(env, script, arg, **extra):
    e = {
        "PATH": f"{env['bin']}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", "/"),
        "HOST_STATE_NOW": str(NOW),
        **{k: str(v) for k, v in extra.items()},
    }
    return subprocess.run(
        ["bash", str(DIR / script), arg],
        env=e, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL,
    )


def _timer(env, *, active="active", realtime="@1794000000", monotonic="",
           service="success", svc_state="inactive", changed=""):
    _unit(env, "backup.timer", ActiveState=active, Unit="backup.service",
          NextElapseUSecRealtime=realtime, NextElapseUSecMonotonic=monotonic)
    _unit(env, "backup.service", ActiveState=svc_state, SubState="x", Result=service,
          StateChangeTimestamp=changed)


def _check(r, code, prefix, word=None):
    assert r.returncode == code, r.stdout + r.stderr
    first = r.stdout.splitlines()[0]
    assert first.startswith(prefix), first
    if word:
        assert word in first, first
    assert len(r.stdout.splitlines()) == 1


def test_timer_ok(env):
    _timer(env)
    _check(_run(env, "timer-check", "backup.timer"), 0, "TIMER backup.timer OK - next ")


def test_timer_monotonic_only(env):
    _timer(env, realtime="", monotonic="11h 26min 37.462686s")
    _check(_run(env, "timer-check", "backup.timer"), 0, "TIMER backup.timer OK")


def test_timer_inactive(env):
    _timer(env, active="inactive")
    _check(_run(env, "timer-check", "backup.timer"), 2, "TIMER backup.timer CRITICAL", "inactive")


def test_timer_no_next(env):
    _timer(env, realtime="", monotonic="")
    _check(_run(env, "timer-check", "backup.timer"), 2, "TIMER backup.timer CRITICAL", "next")


def test_timer_last_failed(env):
    _timer(env, service="exit-code")
    _check(_run(env, "timer-check", "backup.timer"), 2, "TIMER backup.timer CRITICAL", "exit-code")


def test_timer_stuck(env):
    _timer(env, svc_state="activating", changed=f"@{NOW - 3600}")
    _check(_run(env, "timer-check", "backup.timer"), 2, "TIMER backup.timer CRITICAL", "activating")


def test_timer_activating_briefly(env):
    _timer(env, svc_state="activating", changed=f"@{NOW - 60}")
    _check(_run(env, "timer-check", "backup.timer"), 0, "TIMER backup.timer OK")


def test_timer_not_found(env):
    _check(_run(env, "timer-check", "backup.timer"), 3, "TIMER backup.timer UNKNOWN", "not-found")


def test_timer_systemctl_fails(env):
    _timer(env)
    _check(_run(env, "timer-check", "backup.timer", FAKE_SYSTEMCTL_FAIL=1), 3,
           "TIMER backup.timer UNKNOWN")


def test_unit_active(env):
    _unit(env, "x.service", ActiveState="active", SubState="running")
    _check(_run(env, "unit-check", "x.service"), 0, "UNIT x.service OK")


def test_unit_failed(env):
    _unit(env, "x.service", ActiveState="failed", SubState="failed")
    _check(_run(env, "unit-check", "x.service"), 2, "UNIT x.service CRITICAL", "failed")


def test_unit_inactive(env):
    _unit(env, "x.service", ActiveState="inactive", SubState="dead")
    _check(_run(env, "unit-check", "x.service"), 2, "UNIT x.service CRITICAL", "inactive")


def test_unit_not_found(env):
    _check(_run(env, "unit-check", "x.service"), 3, "UNIT x.service UNKNOWN", "not-found")


def test_unit_systemctl_fails(env):
    _check(_run(env, "unit-check", "x.service", FAKE_SYSTEMCTL_FAIL=1), 3, "UNIT x.service UNKNOWN")


def test_site_200(env):
    _check(_run(env, "site-check", "https://a.example/", FAKE_CURL_CODE=200), 0,
           "SITE https://a.example/ OK")


def test_site_redirect_200(env):
    # the curl stub exits 2 unless -L is in argv, so a pass proves redirects are followed
    _check(_run(env, "site-check", "https://a.example/", FAKE_CURL_CODE=200), 0,
           "SITE https://a.example/ OK")


def test_site_500(env):
    _check(_run(env, "site-check", "https://a.example/", FAKE_CURL_CODE=500), 2,
           "SITE https://a.example/ CRITICAL", "500")


def test_site_timeout(env):
    _check(_run(env, "site-check", "https://a.example/", FAKE_CURL_TIMEOUT=1), 2,
           "SITE https://a.example/ CRITICAL", "timed out")
