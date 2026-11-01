"""Tests for homelab/scripts/checkout-ref.sh.

checkout_ref is sourced by deploy scripts to put /opt/pickleclaw and
/opt/brineworks on a ref named in the host identity file. These tests build a
bare "origin" with main and feat branches in a temp dir and drive the function
through a throwaway bash.
"""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "homelab" / "scripts" / "checkout-ref.sh"


def _git(cwd, *args, env=None):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


class Fixture:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        empty_cfg = tmp_path / "gitconfig"
        empty_cfg.write_text("")
        # Fake sudo so the clone path's `sudo mkdir -p` / `sudo chown` run as the
        # test user against paths under tmp_path.
        shim = tmp_path / "shim"
        shim.mkdir()
        (shim / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
        (shim / "sudo").chmod(0o755)
        self.env = {
            "PATH": f"{shim}:{os.environ['PATH']}",
            "HOME": str(tmp_path),
            "GIT_CONFIG_GLOBAL": str(empty_cfg),
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        self.origin = tmp_path / "origin.git"
        seed = tmp_path / "seed"
        _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(self.origin), env=self.env)
        _git(tmp_path, "init", "-q", "-b", "main", str(seed), env=self.env)
        self.commit(seed, "base")
        _git(seed, "remote", "add", "origin", str(self.origin), env=self.env)
        _git(seed, "push", "-q", "origin", "main", env=self.env)
        _git(seed, "checkout", "-q", "-b", "feat", env=self.env)
        self.commit(seed, "feat work")
        _git(seed, "push", "-q", "origin", "feat", env=self.env)
        self.seed = seed

    def commit(self, repo, msg):
        (Path(repo) / f"{msg.replace(' ', '_')}.txt").write_text(msg)
        _git(repo, "add", "-A", env=self.env)
        _git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", msg, env=self.env)

    def git(self, repo, *args):
        return _git(repo, *args, env=self.env)

    def call(self, dest, ref, kind="prod", extra_env=None):
        env = dict(self.env, HOMELAB_HOST_KIND=kind, **(extra_env or {}))
        return subprocess.run(
            ["bash", "-c", f'set -euo pipefail; source "{HELPER}"; checkout_ref "{dest}" "{self.origin}" "{ref}"'],
            env=env, capture_output=True, text=True, timeout=60,
        )

    def clone(self, dest):
        _git(self.tmp, "clone", "-q", str(self.origin), str(dest), env=self.env)


def test_clones_then_checks_out_ref(tmp_path):
    fx = Fixture(tmp_path)
    dest = tmp_path / "checkout"
    r = fx.call(dest, "feat")
    assert r.returncode == 0, r.stderr
    assert fx.git(dest, "branch", "--show-current") == "feat"
    assert fx.git(dest, "rev-parse", "HEAD") == fx.git(fx.origin, "rev-parse", "feat")
    assert f"{dest} at " in r.stdout and "(feat)" in r.stdout


def test_switches_ref_on_existing_clone(tmp_path):
    fx = Fixture(tmp_path)
    dest = tmp_path / "checkout"
    fx.clone(dest)
    assert fx.git(dest, "branch", "--show-current") == "main"
    for kind in ("prod", "dev"):
        r = fx.call(dest, "feat", kind=kind)
        assert r.returncode == 0, r.stderr
        assert fx.git(dest, "branch", "--show-current") == "feat"
        r = fx.call(dest, "main", kind=kind)
        assert r.returncode == 0, r.stderr
        assert fx.git(dest, "branch", "--show-current") == "main"


def test_fetch_failure_is_nonzero(tmp_path):
    fx = Fixture(tmp_path)
    dest = tmp_path / "checkout"
    fx.clone(dest)
    before = fx.git(dest, "rev-parse", "HEAD")
    r = fx.call(dest, "nope")
    assert r.returncode != 0
    assert fx.git(dest, "rev-parse", "HEAD") == before


def _diverge(fx, dest):
    """dest has a local commit on main; origin has a different one."""
    fx.clone(dest)
    fx.commit(dest, "local only")
    fx.git(fx.seed, "checkout", "-q", "main")
    fx.commit(fx.seed, "upstream main moved")
    fx.git(fx.seed, "push", "-q", "origin", "main")


def test_prod_refuses_diverged_checkout(tmp_path):
    fx = Fixture(tmp_path)
    dest = tmp_path / "checkout"
    _diverge(fx, dest)
    before = fx.git(dest, "rev-parse", "HEAD")
    r = fx.call(dest, "main", kind="prod")
    assert r.returncode != 0
    assert fx.git(dest, "rev-parse", "HEAD") == before
    assert fx.git(dest, "branch", "--show-current") == "main"


def test_dev_resets_diverged_checkout_to_origin(tmp_path):
    fx = Fixture(tmp_path)
    dest = tmp_path / "checkout"
    _diverge(fx, dest)
    r = fx.call(dest, "main", kind="dev")
    assert r.returncode == 0, r.stderr
    assert fx.git(dest, "rev-parse", "HEAD") == fx.git(fx.origin, "rev-parse", "main")


def test_prod_fast_forwards(tmp_path):
    fx = Fixture(tmp_path)
    dest = tmp_path / "checkout"
    fx.clone(dest)
    fx.git(fx.seed, "checkout", "-q", "main")
    fx.commit(fx.seed, "ahead")
    fx.git(fx.seed, "push", "-q", "origin", "main")
    r = fx.call(dest, "main", kind="prod")
    assert r.returncode == 0, r.stderr
    assert fx.git(dest, "rev-parse", "HEAD") == fx.git(fx.origin, "rev-parse", "main")


def test_unset_kind_fails(tmp_path):
    fx = Fixture(tmp_path)
    env = dict(fx.env)
    r = subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{HELPER}"; checkout_ref "{tmp_path}/c" "{fx.origin}" main'],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode != 0
    assert "HOMELAB_HOST_KIND" in r.stderr


def test_honors_git_ssh_command_for_clone_and_fetch(tmp_path):
    fx = Fixture(tmp_path)
    log = tmp_path / "ssh.log"
    fake = tmp_path / "fake-ssh"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 1\n')
    fake.chmod(0o755)
    # Clone path: a remote URL that needs ssh, nothing on disk yet.
    env = dict(fx.env, HOMELAB_HOST_KIND="prod")
    cmd = f'set -euo pipefail; source "{HELPER}"; GIT_SSH_COMMAND="{fake}" checkout_ref "{tmp_path}/c" ssh://git@example.invalid/x.git main'
    r = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert log.exists() and "example.invalid" in log.read_text()
    # Fetch path: existing clone whose origin is an ssh URL.
    log.unlink()
    fx.clone(tmp_path / "d")
    fx.git(tmp_path / "d", "remote", "set-url", "origin", "ssh://git@example.invalid/x.git")
    cmd = f'set -euo pipefail; source "{HELPER}"; GIT_SSH_COMMAND="{fake}" checkout_ref "{tmp_path}/d" ssh://git@example.invalid/x.git main'
    r = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert log.exists() and "example.invalid" in log.read_text()


def test_executing_helper_is_refused():
    r = subprocess.run(["bash", str(HELPER)], capture_output=True, text=True)
    assert r.returncode == 64
