"""Tests for homelab/scripts/pull-images.sh, using a stub docker on PATH.

The stub fails until call N, so we can check the script keeps retrying until the
image exists and gives up with a message naming the SHA once attempts run out.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "homelab" / "scripts" / "pull-images.sh"


@pytest.fixture
def stub_docker(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    counter = tmp_path / "calls"
    docker = bindir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f'n=$(( $(cat {counter} 2>/dev/null || echo 0) + 1 ))\n'
        f'echo $n > {counter}\n'
        f'echo "$@" >> {tmp_path / "args"}\n'
        '[ "$n" -ge "${DOCKER_SUCCEEDS_ON:-1}" ]\n'
    )
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    return {"bin": bindir, "counter": counter, "args": tmp_path / "args"}


def _run(stub, **env_extra):
    env = {"PATH": f"{stub['bin']}:{os.environ['PATH']}", "PULL_INTERVAL": "0", **env_extra}
    return subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=env)


def test_retries_until_the_image_exists(stub_docker):
    result = _run(stub_docker, IMAGE_SHA="abc1234def", DOCKER_SUCCEEDS_ON="3")
    assert result.returncode == 0
    assert stub_docker["counter"].read_text().strip() == "3"


def test_gives_up_and_names_the_missing_sha(stub_docker):
    result = _run(stub_docker, IMAGE_SHA="abc1234def", DOCKER_SUCCEEDS_ON="99", PULL_ATTEMPTS="3")
    assert result.returncode == 1
    assert "abc1234" in result.stderr
    assert stub_docker["counter"].read_text().strip() == "3"


def test_requires_image_sha(stub_docker):
    result = _run(stub_docker)
    assert result.returncode != 0
    assert "IMAGE_SHA" in result.stderr


def test_exports_placeholders_for_vars_listed_in_env_vars(stub_docker, tmp_path):
    work = tmp_path / "svc"
    work.mkdir()
    (work / ".env.vars").write_text("# comment\nFOO\n\nBAR\n")
    dump = tmp_path / "env.out"
    docker = stub_docker["bin"] / "docker"
    docker.write_text(f'#!/usr/bin/env bash\nenv > {dump}\n')
    env = {"PATH": f"{stub_docker['bin']}:{os.environ['PATH']}", "IMAGE_SHA": "abc1234def"}
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, env=env, cwd=work)
    assert result.returncode == 0, result.stderr
    pulled_env = dump.read_text()
    assert "FOO=pull-placeholder" in pulled_env
    assert "BAR=pull-placeholder" in pulled_env


def test_passes_the_project_directory_when_set(stub_docker):
    result = _run(stub_docker, IMAGE_SHA="abc1234def", PULL_PROJECT_DIR="/srv/svc")
    assert result.returncode == 0
    assert stub_docker["args"].read_text().strip() == "compose --project-directory /srv/svc pull --quiet"


def test_no_project_directory_flag_by_default(stub_docker):
    result = _run(stub_docker, IMAGE_SHA="abc1234def")
    assert result.returncode == 0
    assert stub_docker["args"].read_text().strip() == "compose pull --quiet"
