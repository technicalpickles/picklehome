"""Tests for homelab/scripts/wait-for-health.sh, using a stub curl on PATH.

The stub counts its calls and only succeeds from call N onward, so we can check
that the helper keeps polling until the service answers, and gives up (return 1)
once the wall-clock budget runs out. Budgets are tiny and the interval is 1s, so
each test finishes in a few seconds.
"""
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "homelab" / "scripts" / "wait-for-health.sh"


@pytest.fixture
def stub_curl(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    counter = tmp_path / "calls"
    argv_log = tmp_path / "argv"
    curl = bindir / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {argv_log}\n'
        f'n=$(( $(cat {counter} 2>/dev/null || echo 0) + 1 ))\n'
        f'echo $n > {counter}\n'
        '[ "$n" -ge "${CURL_SUCCEEDS_ON:-1}" ]\n'
    )
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return {"bin": bindir, "counter": counter, "argv": argv_log}


def _run(stub, snippet, **env_extra):
    env = {
        "PATH": f"{stub['bin']}:{os.environ['PATH']}",
        "HEALTH_WAIT_INTERVAL": "1",
        **{k: str(v) for k, v in env_extra.items()},
    }
    return subprocess.run(
        ["bash", "-c", f'source "{HELPER}"; {snippet}'],
        env=env, capture_output=True, text=True, timeout=30,
    )


def _calls(stub):
    return int(stub["counter"].read_text())


def test_passes_immediately_when_healthy(stub_curl):
    r = _run(stub_curl, 'wait_for_health svc http://127.0.0.1:1/health 5')
    assert r.returncode == 0
    # $SECONDS is whole seconds, so a call straddling a tick reads 1s.
    assert re.search(r"passed after [01]s", r.stdout)
    assert _calls(stub_curl) == 1


def test_keeps_polling_until_service_answers(stub_curl):
    r = _run(stub_curl, 'wait_for_health svc http://127.0.0.1:1/health 10',
             CURL_SUCCEEDS_ON=3)
    assert r.returncode == 0
    assert _calls(stub_curl) == 3
    assert r.stdout.count("Waiting for svc to start") == 2
    # Two 1s sleeps, but bash's $SECONDS is a whole-second counter that floors
    # from wherever the start landed inside a second, so it reads 2s or 3s.
    assert re.search(r"passed after [23]s", r.stdout)


def test_gives_up_after_deadline_with_clear_message(stub_curl):
    r = _run(stub_curl, 'wait_for_health svc http://127.0.0.1:1/health 2',
             CURL_SUCCEEDS_ON=999)
    assert r.returncode == 1
    assert "WARNING: local health check failed" in r.stdout
    assert re.search(r"svc not answering at http://127\.0\.0\.1:1/health after [23]s \(budget 2s\)", r.stdout)


def test_env_var_overrides_the_budget(stub_curl):
    # The 3rd arg says 100s; HEALTH_WAIT_SECS=1 must win, or this would run ~100s.
    r = _run(stub_curl, 'wait_for_health svc http://127.0.0.1:1/health 100',
             CURL_SUCCEEDS_ON=999, HEALTH_WAIT_SECS=1)
    assert r.returncode == 1
    assert "(budget 1s)" in r.stdout


def test_curl_is_bounded_so_a_wedged_listener_cannot_outlast_the_deadline(stub_curl):
    _run(stub_curl, 'wait_for_health svc http://127.0.0.1:1/health 5')
    argv = stub_curl["argv"].read_text()
    assert "--connect-timeout" in argv and "--max-time" in argv


def test_safe_under_set_e_when_caller_handles_failure(stub_curl):
    # deploy.sh runs under `set -euo pipefail`; a timeout must reach the `if !`, not abort.
    r = _run(stub_curl,
             'set -euo pipefail; if ! wait_for_health svc http://127.0.0.1:1/health 1; then echo caller-handled; fi',
             CURL_SUCCEEDS_ON=999)
    assert r.returncode == 0
    assert "caller-handled" in r.stdout
