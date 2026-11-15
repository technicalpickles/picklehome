"""Tests for homelab/scripts/docker-credential-picklehome-ghcr, with a stub `op`.

The stub echoes the reference it was asked for, so the tests can check that the
helper reads the token file, asks 1Password for the right item, and speaks the
docker credential-helper protocol (JSON on get, "not found" for other hosts).
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "homelab" / "scripts" / "docker-credential-picklehome-ghcr"


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    op = bindir / "op"
    op.write_text('#!/usr/bin/env bash\n[ -n "$OP_SERVICE_ACCOUNT_TOKEN" ] || exit 9\necho -n "tok-for:${@: -1}"\n')
    op.chmod(op.stat().st_mode | stat.S_IEXEC)
    token_file = tmp_path / "op-token"
    token_file.write_text("OP_SERVICE_ACCOUNT_TOKEN=sa-test\n")
    return {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "HOMELAB_OP_TOKEN_FILE": str(token_file),
    }


def _run(env, *args, stdin=""):
    return subprocess.run([str(HELPER), *args], input=stdin, capture_output=True, text=True, env=env)


def test_get_returns_credentials_for_ghcr(env):
    result = _run(env, "get", stdin="ghcr.io\n")
    assert result.returncode == 0, result.stderr
    cred = json.loads(result.stdout)
    assert cred == {
        "ServerURL": "ghcr.io",
        "Username": "technicalpickles",
        "Secret": "tok-for:op://picklehome/GHCR Pull/credential",
    }


def test_get_for_another_registry_is_not_found(env):
    result = _run(env, "get", stdin="registry.example.com\n")
    assert result.returncode == 1
    assert "not found" in result.stderr


def test_store_refuses_so_login_cannot_write_the_token(env):
    assert _run(env, "store", stdin="{}").returncode == 1


def test_missing_token_file_fails_instead_of_returning_empty_secret(env):
    env["HOMELAB_OP_TOKEN_FILE"] = "/nonexistent/op-token"
    result = _run(env, "get", stdin="ghcr.io\n")
    assert result.returncode != 0
    assert result.stdout == ""
