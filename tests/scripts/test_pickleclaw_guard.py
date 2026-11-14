"""Tests for scripts/pickleclaw-guard, against a throwaway pickleclaw clone
reached through the same kind of symlinks the deploy copies from."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pickleclaw-guard"
JUSTFILE = ROOT / "Justfile"


def git(cwd, *args, env, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=check,
        capture_output=True, text=True,
    )


@pytest.fixture
def setup(tmp_path):
    """Returns (openclaw_dir, clone_dir, origin_dir, env)."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": str(empty),
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    }
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin), env=env)
    git(tmp_path, "init", "-q", "-b", "main", str(seed), env=env)
    cfg = seed / "openclaw-config"
    (cfg / "plugins" / "brineworks-approval").mkdir(parents=True)
    (cfg / "tools.json5").write_text("{}")
    (cfg / "mcp.json5").write_text("{}")
    (cfg / "openclaw.env").write_text("X=1")
    (cfg / "plugins" / "brineworks-approval" / "index.js").write_text("//")
    (seed / "scripts").mkdir()
    (seed / "scripts" / "workspace-git-sync.sh").write_text("#!/bin/sh")
    git(seed, "add", ".", env=env)
    git(seed, "commit", "-q", "-m", "init", env=env)
    git(seed, "remote", "add", "origin", str(origin), env=env)
    git(seed, "push", "-q", "origin", "main", env=env)

    clone = tmp_path / "pickleclaw"
    git(tmp_path, "clone", "-q", str(origin), str(clone), env=env)

    oc = tmp_path / "openclaw"
    (oc / "plugins").mkdir(parents=True)
    links = {
        "openclaw.tools.json5": cfg.name + "/tools.json5",
        "openclaw.mcp.json5": cfg.name + "/mcp.json5",
        "openclaw.image.env": cfg.name + "/openclaw.env",
        "workspace-git-sync.sh": "scripts/workspace-git-sync.sh",
        "plugins/brineworks-approval": cfg.name + "/plugins/brineworks-approval",
    }
    for name, target in links.items():
        (oc / name).symlink_to(clone / target)
    return oc, clone, seed, env


def run(oc, env, cwd=None):
    return subprocess.run(
        [str(SCRIPT), str(oc)], cwd=cwd, env=env, capture_output=True, text=True
    )


def advance_origin(seed, env):
    (seed / "new").write_text("n")
    git(seed, "add", "new", env=env)
    git(seed, "commit", "-q", "-m", "next", env=env)
    git(seed, "push", "-q", "origin", "main", env=env)


def test_clean_on_origin_main_passes(setup):
    oc, _, _, env = setup
    r = run(oc, env)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_modified_tracked_file_refuses(setup):
    oc, clone, _, env = setup
    (clone / "openclaw-config" / "tools.json5").write_text("{ edited: 1 }")
    r = run(oc, env)
    assert r.returncode == 1
    assert "uncommitted changes" in r.stderr


def test_untracked_file_refuses(setup):
    oc, clone, _, env = setup
    (clone / "stray").write_text("x")
    r = run(oc, env)
    assert r.returncode == 1
    assert "uncommitted changes" in r.stderr


def test_feature_branch_ahead_of_main_refuses(setup):
    oc, clone, _, env = setup
    git(clone, "checkout", "-q", "-b", "feature", env=env)
    (clone / "f").write_text("f")
    git(clone, "add", "f", env=env)
    git(clone, "commit", "-q", "-m", "wip", env=env)
    r = run(oc, env)
    assert r.returncode == 1
    assert "feature" in r.stderr
    assert "not origin/main" in r.stderr


def test_feature_branch_at_same_commit_as_main_passes(setup):
    oc, clone, _, env = setup
    git(clone, "checkout", "-q", "-b", "feature", env=env)
    assert run(oc, env).returncode == 0


def test_local_main_behind_origin_refuses_after_fetching(setup):
    oc, _, seed, env = setup
    advance_origin(seed, env)
    r = run(oc, env)
    assert r.returncode == 1
    assert "not origin/main" in r.stderr


def test_local_main_ahead_of_origin_refuses(setup):
    oc, clone, _, env = setup
    (clone / "f").write_text("f")
    git(clone, "add", "f", env=env)
    git(clone, "commit", "-q", "-m", "unpushed", env=env)
    r = run(oc, env)
    assert r.returncode == 1
    assert "not origin/main" in r.stderr


def test_fetch_failure_refuses(setup):
    oc, clone, _, env = setup
    git(clone, "remote", "set-url", "origin", "/nonexistent/origin.git", env=env)
    r = run(oc, env)
    assert r.returncode == 1
    assert "fetch" in r.stderr


def test_no_symlinks_refuses(setup, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    _, _, _, env = setup
    r = run(empty, env)
    assert r.returncode == 1
    assert "no symlinks" in r.stderr


def test_dangling_symlink_refuses(setup):
    oc, clone, _, env = setup
    (clone / "openclaw-config" / "mcp.json5").unlink()
    r = run(oc, env)
    assert r.returncode == 1


def test_plain_file_include_refuses(setup):
    oc, _, _, env = setup
    (oc / "openclaw.tools.json5").unlink()
    (oc / "openclaw.tools.json5").write_text("{ local: 1 }")
    r = run(oc, env)
    assert r.returncode == 1
    assert "openclaw.tools.json5 is a plain file" in r.stderr


def test_plain_directory_plugin_refuses(setup):
    oc, _, _, env = setup
    plugin = oc / "plugins" / "brineworks-approval"
    plugin.unlink()
    plugin.mkdir()
    (plugin / "index.js").write_text("// local copy")
    r = run(oc, env)
    assert r.returncode == 1
    assert "brineworks-approval is a plain file or directory" in r.stderr


def commit_gitignore(clone, env, pattern):
    (clone / ".gitignore").write_text(pattern + "\n")
    git(clone, "add", ".gitignore", env=env)
    git(clone, "commit", "-q", "-m", "ignore", env=env)
    git(clone, "push", "-q", "origin", "main", env=env)


def test_gitignored_file_inside_plugin_refuses(setup):
    oc, clone, _, env = setup
    commit_gitignore(clone, env, "node_modules/")
    deps = clone / "openclaw-config" / "plugins" / "brineworks-approval" / "node_modules"
    deps.mkdir()
    (deps / "dep.js").write_text("//")
    r = run(oc, env)
    assert r.returncode == 1
    assert "gitignored" in r.stderr


def test_gitignored_file_outside_shipped_paths_passes(setup):
    oc, clone, _, env = setup
    commit_gitignore(clone, env, "node_modules/")
    (clone / "node_modules").mkdir()
    (clone / "node_modules" / "dep.js").write_text("//")
    r = run(oc, env)
    assert r.returncode == 0, r.stderr


def test_guard_runs_before_preflight_in_deploy_recipe():
    recipe = JUSTFILE.read_text().split("deploy-openclaw host=", 1)[1]
    assert recipe.index("scripts/pickleclaw-guard") < recipe.index("scripts/deploy-preflight")
