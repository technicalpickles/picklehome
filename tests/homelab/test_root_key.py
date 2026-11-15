import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEYS = ROOT / "homelab" / "config" / "root-authorized-keys"
SETUP = ROOT / "homelab" / "scripts" / "setup-root-key.sh"
AUDIT = ROOT / "homelab" / "config" / "root-ssh-audit"


def _pinned_fp():
    m = re.search(r'^EXPECTED_FP="([^"]+)"', SETUP.read_text(), re.MULTILINE)
    assert m, "setup-root-key.sh lost its EXPECTED_FP line"
    return m.group(1)


def _key_lines():
    return [l for l in KEYS.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]


def test_key_file_matches_pinned_fingerprint():
    r = subprocess.run(["ssh-keygen", "-lf", str(KEYS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split()[1] == _pinned_fp()


def test_key_is_the_only_one_and_fully_restricted():
    lines = _key_lines()
    assert len(lines) == 1
    options = lines[0].split(" ssh-")[0]
    for required in ("restrict", "pty", 'from="100.114.32.22"', 'command="/usr/local/sbin/root-ssh-audit"'):
        assert required in options.split(","), f"missing {required}"


def _run_audit(tmp_path, original_command):
    log = tmp_path / "logger.out"
    fake = tmp_path / "logger"
    fake.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    fake.chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "SSH_CONNECTION": "100.114.32.22 5000 100.123.122.68 22"}
    if original_command is not None:
        env["SSH_ORIGINAL_COMMAND"] = original_command
    r = subprocess.run([str(AUDIT)], capture_output=True, text=True, env=env, timeout=30, input="exit\n")
    return r, log.read_text()


def test_audit_logs_then_runs_the_command(tmp_path):
    r, logged = _run_audit(tmp_path, "echo ran-as-asked")
    assert r.stdout.strip() == "ran-as-asked"
    assert "-t root-ssh" in logged
    assert "from=100.114.32.22 cmd=echo ran-as-asked" in logged


def test_audit_logs_interactive_shell(tmp_path):
    r, logged = _run_audit(tmp_path, None)
    assert r.returncode == 0
    assert "from=100.114.32.22 interactive shell" in logged
