"""Tests for scripts/deploy-preflight, against a temp repo with a bare origin.

The script's stdout is eval'd by the deploy recipes, so these also check that
awkward branch names survive the quoting.
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy-preflight"

PROD_ENV = """HOMELAB_HOST_KIND=prod
HOMELAB_HOST_ALIASES="picklelab.tail2023b7.ts.net"
"""
DEV_ENV = """HOMELAB_HOST_KIND=dev
HOMELAB_HOST_ALIASES=
"""


def git(cwd, *args, env=None, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=check,
        capture_output=True, text=True,
    )


@pytest.fixture
def repo(tmp_path):
    """Returns (work_dir, origin_dir, env). Test isolation only: an empty global
    git config and no signing, so temp repos never touch the real agent."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(empty),
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    env.pop("HOMELAB_REPO_DIR", None)
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin), env=env)
    git(tmp_path, "init", "-q", "-b", "main", str(work), env=env)
    git(work, "config", "commit.gpgsign", "false", env=env)
    hosts = work / "homelab" / "hosts"
    (hosts / "local").mkdir(parents=True)
    (hosts / "picklelab.env").write_text(PROD_ENV)
    (hosts / "local" / "picklelab-dev.env").write_text(DEV_ENV)
    (work / ".gitignore").write_text("homelab/hosts/local/\n")
    git(work, "add", ".", env=env)
    git(work, "commit", "-q", "-m", "init", env=env)
    git(work, "remote", "add", "origin", str(origin), env=env)
    git(work, "push", "-q", "origin", "main", env=env)
    git(work, "fetch", "-q", "origin", env=env)
    return work, origin, env


def run(repo, host, **kw):
    work, _, env = repo
    return subprocess.run(
        [str(SCRIPT), host], cwd=work, env=env, capture_output=True, text=True, **kw
    )


def commit(work, env, name="f", msg="c"):
    (work / name).write_text(msg)
    git(work, "add", name, env=env)
    git(work, "commit", "-q", "-m", msg, env=env)


def origin_ref(origin, ref, env):
    r = git(origin, "rev-parse", "--verify", "-q", ref, env=env, check=False)
    return r.stdout.strip() or None


def parse(stdout):
    """What a recipe sees after eval."""
    script = f'{stdout}\nprintf "%s\\n%s\\n%s" "$DEPLOY_KIND" "$DEPLOY_REF" "$DEPLOY_UPDATE"'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout
    kind, ref, update = out.split("\n", 2)
    return kind, ref, update


def test_dirty_tree_refused(repo):
    work, _, _ = repo
    (work / "scratch").write_text("x")
    r = run(repo, "picklelab")
    assert r.returncode == 1
    assert "uncommitted" in r.stderr
    assert r.stdout == ""


def test_prod_on_branch_refused(repo):
    work, _, env = repo
    git(work, "checkout", "-q", "-b", "feat", env=env)
    r = run(repo, "picklelab")
    assert r.returncode == 1
    assert "not on main" in r.stderr


def test_prod_pushes_when_behind_origin(repo):
    work, origin, env = repo
    commit(work, env)
    r = run(repo, "picklelab")
    assert r.returncode == 0, r.stderr
    assert "DEPLOY_KIND=prod" in r.stdout
    assert "DEPLOY_REF=main" in r.stdout
    assert origin_ref(origin, "refs/heads/main", env) == git(work, "rev-parse", "HEAD", env=env).stdout.strip()


def test_prod_in_sync_does_not_push(repo):
    work, origin, env = repo
    before = origin_ref(origin, "refs/heads/main", env)
    r = run(repo, "picklelab")
    assert r.returncode == 0, r.stderr
    assert "Pushing" not in r.stderr
    assert origin_ref(origin, "refs/heads/main", env) == before


def test_dev_pushes_branch(repo):
    work, origin, env = repo
    git(work, "checkout", "-q", "-b", "feat", env=env)
    commit(work, env)
    r = run(repo, "picklelab-dev")
    assert r.returncode == 0, r.stderr
    assert "DEPLOY_KIND=dev" in r.stdout
    assert "DEPLOY_REF=feat" in r.stdout
    assert origin_ref(origin, "refs/heads/feat", env) == git(work, "rev-parse", "HEAD", env=env).stdout.strip()


def test_dev_detached_head_refused(repo):
    work, _, env = repo
    git(work, "checkout", "-q", "--detach", env=env)
    r = run(repo, "picklelab-dev")
    assert r.returncode == 1
    assert "detached" in r.stderr


def test_dev_dirty_tree_refused(repo):
    work, _, env = repo
    git(work, "checkout", "-q", "-b", "feat", env=env)
    (work / "scratch").write_text("x")
    r = run(repo, "picklelab-dev")
    assert r.returncode == 1
    assert "uncommitted" in r.stderr


def test_alias_resolves_to_prod(repo):
    r = run(repo, "picklelab.tail2023b7.ts.net")
    assert r.returncode == 0, r.stderr
    assert "DEPLOY_KIND=prod" in r.stdout


def test_unknown_host_refused(repo):
    work, origin, env = repo
    git(work, "checkout", "-q", "-b", "feat", env=env)
    commit(work, env)
    r = run(repo, "nope")
    assert r.returncode == 1
    assert "no identity for host nope" in r.stderr
    assert origin_ref(origin, "refs/heads/feat", env) is None, "must not push for an unknown host"


def test_committed_alias_beats_local_file_of_same_name(repo):
    work, _, env = repo
    (work / "homelab" / "hosts" / "local" / "picklelab.tail2023b7.ts.net.env").write_text(DEV_ENV)
    git(work, "checkout", "-q", "-b", "feat", env=env)
    r = run(repo, "picklelab.tail2023b7.ts.net")
    assert r.returncode == 1, "alias must stay prod, which refuses a non-main branch"
    assert "not on main" in r.stderr
    git(work, "checkout", "-q", "main", env=env)
    r = run(repo, "picklelab.tail2023b7.ts.net")
    assert r.returncode == 0, r.stderr
    assert "DEPLOY_KIND=prod" in r.stdout


def test_dev_identity_template_is_not_a_host(repo):
    work, origin, env = repo
    (work / "homelab" / "hosts" / "dev-identity.env").write_text(DEV_ENV)
    git(work, "add", "-A", env=env)
    git(work, "commit", "-q", "-m", "template", env=env)
    r = run(repo, "dev-identity")
    assert r.returncode == 1
    assert "no identity for host dev-identity" in r.stderr
    assert origin_ref(origin, "refs/heads/main", env) != git(work, "rev-parse", "HEAD", env=env).stdout.strip(), "must not push"


def test_host_with_path_chars_refused(repo):
    r = run(repo, "../picklelab")
    assert r.returncode == 1
    assert "no identity for host" in r.stderr


def test_repo_dir_env_points_lookup_elsewhere(repo, tmp_path):
    work, _, env = repo
    other = tmp_path / "elsewhere"
    other.mkdir()
    r = subprocess.run(
        [str(SCRIPT), "picklelab"], cwd=other, capture_output=True, text=True,
        env={**env, "HOMELAB_REPO_DIR": str(work)},
    )
    assert r.returncode == 0, r.stderr
    assert "DEPLOY_KIND=prod" in r.stdout


# --- DEPLOY_UPDATE (controller ruling R11) -------------------------------------


def test_prod_update_is_ff_only_and_never_resets(repo):
    r = run(repo, "picklelab")
    _, ref, update = parse(r.stdout)
    assert ref == "main"
    assert "--ff-only" in update
    assert " -B" not in update
    assert "reset" not in update
    assert "origin/main" in update


def test_dev_update_force_checks_out_branch(repo):
    work, _, env = repo
    git(work, "checkout", "-q", "-b", "feat", env=env)
    commit(work, env)
    r = run(repo, "picklelab-dev")
    _, ref, update = parse(r.stdout)
    assert ref == "feat"
    assert " -B" in update
    assert "feat" in update
    assert "origin/feat" in update
    assert "--ff-only" not in update


# git allows these in branch names but they mean something to a shell.
AWKWARD = ["feat$(echo>pwned)", "a$b", "x;y", "has`tick`", "amp&er", "br(ace)"]


@pytest.mark.parametrize("branch", AWKWARD)
def test_awkward_branch_survives_eval_and_remote_update(repo, tmp_path, branch):
    work, origin, env = repo
    if git(work, "check-ref-format", "--branch", branch, env=env, check=False).returncode != 0:
        pytest.skip("git refuses this branch name")
    git(work, "checkout", "-q", "-b", branch, env=env)
    commit(work, env)
    r = run(repo, "picklelab-dev")
    assert r.returncode == 0, r.stderr
    kind, ref, update = parse(r.stdout)
    assert (kind, ref) == ("dev", branch)

    # Run the update the way the remote login shell would, in a "host" clone.
    host = tmp_path / "host"
    git(tmp_path, "clone", "-q", str(origin), str(host), env=env)
    done = subprocess.run(["bash", "-c", update], cwd=host, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert git(host, "branch", "--show-current", env=env).stdout.strip() == branch
    assert not (host / "pwned").exists()
    assert not (work / "pwned").exists()


def test_prod_update_runs_on_host_and_fails_loudly_when_diverged(repo, tmp_path):
    work, origin, env = repo
    commit(work, env, "a", "one")
    r = run(repo, "picklelab")
    _, _, update = parse(r.stdout)

    host = tmp_path / "host"
    git(tmp_path, "clone", "-q", str(origin), str(host), env=env)
    git(host, "config", "commit.gpgsign", "false", env=env)
    ok = subprocess.run(["bash", "-c", update], cwd=host, env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr

    # Host grows a local-only commit; origin moves on. Update must refuse, not reset.
    commit(host, env, "hostonly", "local")
    local_head = git(host, "rev-parse", "HEAD", env=env).stdout.strip()
    commit(work, env, "b", "two")
    git(work, "push", "-q", "origin", "main", env=env)
    bad = subprocess.run(["bash", "-c", update], cwd=host, env=env, capture_output=True, text=True)
    assert bad.returncode != 0
    assert git(host, "rev-parse", "HEAD", env=env).stdout.strip() == local_head
