"""Tests for scripts/seed-brineworks-gmail, using stub executables on PATH.

The stubs record their argv (never the password) so we can assert ordering,
argument shape, and that a failed verification stops before anything is copied.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed-brineworks-gmail"
PASSWORD = "s3cret-keyring-password"


def _stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def stubs(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    _stub(bindir / "op", f'echo "op $*" >> {log}\necho {PASSWORD}\n')
    # bw: `email auth` writes a keyring file; `email auth --check` succeeds unless BW_CHECK_FAIL.
    _stub(
        bindir / "bw",
        f'echo "bw $*" >> {log}\n'
        f'echo "env password=$KEYRING_CRYPTFILE_PASSWORD prefix=$PF_KEYCHAIN_PREFIX" >> {tmp_path}/bw-env.log\n'
        'if [ "$*" = "email auth" ]; then echo fake-keyring > "$BRINEWORKS_KEYRING_FILE"; fi\n'
        'if [ "$*" = "email auth --check" ] && [ -n "$BW_CHECK_FAIL" ]; then exit 1; fi\n',
    )
    _stub(bindir / "ssh", f'echo "ssh $*" >> {log}\nif [[ "$*" == *mktemp* ]]; then echo /tmp/tmp.remote123; fi\n')
    _stub(bindir / "scp", f'echo "scp $*" >> {log}\n')
    return {"bin": bindir, "log": log, "tmp": tmp_path}


def _run(stubs, *args, **env_extra):
    env = {
        "PATH": f"{stubs['bin']}:{os.environ['PATH']}",
        "TMPDIR": str(stubs["tmp"]),
        "HOME": str(stubs["tmp"]),
        **env_extra,
    }
    return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, env=env)


def test_happy_path_order_and_target(stubs):
    result = _run(stubs, "picklelab")
    assert result.returncode == 0, result.stderr
    calls = stubs["log"].read_text().splitlines()
    kinds = [c.split()[0] + (" --check" if c.endswith("--check") else "") for c in calls]
    assert kinds == ["op", "bw", "bw --check", "ssh", "scp", "ssh"]
    assert "picklelab:/tmp/tmp.remote123" in calls[4]
    final_ssh = calls[5]
    assert "/srv/data/brineworks-server/keyring/cryptfile.cfg" in final_ssh
    assert "chmod 600" in final_ssh and "chown root:root" in final_ssh
    assert ".bak" in final_ssh  # re-seed keeps the previous keyring


def test_password_reaches_bw_env_but_never_argv_or_output(stubs):
    result = _run(stubs)
    assert result.returncode == 0, result.stderr
    assert f"password={PASSWORD}" in (stubs["tmp"] / "bw-env.log").read_text()
    assert "prefix=agent" in (stubs["tmp"] / "bw-env.log").read_text()
    assert PASSWORD not in stubs["log"].read_text()
    assert PASSWORD not in result.stdout + result.stderr


def test_failed_verification_copies_nothing(stubs):
    result = _run(stubs, BW_CHECK_FAIL="1")
    assert result.returncode != 0
    calls = stubs["log"].read_text()
    assert "scp" not in calls and "ssh" not in calls


def test_temp_keyring_is_removed(stubs):
    _run(stubs)
    assert not list(stubs["tmp"].glob("tmp.*/cryptfile.cfg"))
    assert not [p for p in stubs["tmp"].glob("brineworks-seed.*")]


def test_missing_bw_is_a_clear_error(stubs, tmp_path):
    (stubs["bin"] / "bw").unlink()
    result = _run(stubs, BW="/nonexistent/bw")
    assert result.returncode != 0
    assert "bw" in result.stderr and "BW=" in result.stderr
