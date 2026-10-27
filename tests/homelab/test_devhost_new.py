"""Tests for homelab/devhost/{new,rm,ls}.sh, using a stub orb on PATH.

The stub logs every orb argv line to one file and every stdin it is handed
(tee and the tailscale `read`) to another, and answers `orb list` from fixtures.
So we can check which orb calls the scripts make, in what order, and that the
secrets only ever travel on stdin. HOME and DEVHOST_LOCAL_DIR point into tmp_path:
nothing here touches the real ~/.ssh or homelab/hosts/local.
"""
import os
import stat
import subprocess
from pathlib import Path

import pytest

DEVHOST = Path(__file__).resolve().parents[2] / "homelab" / "devhost"
NEW = DEVHOST / "new.sh"
RM = DEVHOST / "rm.sh"
LS = DEVHOST / "ls.sh"
IDENTITY = DEVHOST.parent / "hosts" / "dev-identity.env"

TOKEN = "ops_eyJ-not-a-real-token-0001"
AUTH_KEY = "tskey-auth-notarealkey-0002"

FOREIGN_BLOCK = (
    "Host picklelab-dev\n"
    "    HostName picklelab-dev.tail2023b7.ts.net\n"
    "    User josh\n"
)


@pytest.fixture
def stub(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    local_dir = tmp_path / "local"
    argv_log = tmp_path / "argv"
    stdin_log = tmp_path / "stdin"
    machines = tmp_path / "machines"
    machines.write_text("")
    table = tmp_path / "table"
    table.write_text("")
    orb = bindir / "orb"
    # `orb list -q` prints names; `orb list` prints `name state distro ...`.
    # stdin is only read for the calls that are handed a secret or a file.
    orb.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$*" >> {argv_log}\n'
        f'if [ "$1 $2" = "list -q" ]; then cat {machines}; exit 0; fi\n'
        f'if [ "$1" = "list" ]; then cat {table}; exit 0; fi\n'
        'case "$*" in\n'
        f'  *tee*|*"read -r"*) {{ echo "## $*"; cat; }} >> {stdin_log};;\n'
        "esac\n"
        f'if [ -n "${{STUB_FAIL_ON:-}}" ]; then case "$*" in *"$STUB_FAIL_ON"*) exit 9;; esac; fi\n'
        "exit 0\n"
    )
    orb.chmod(orb.stat().st_mode | stat.S_IEXEC)
    return {
        "bin": bindir,
        "home": home,
        "local": local_dir,
        "argv": argv_log,
        "stdin": stdin_log,
        "machines": machines,
        "table": table,
        "ssh": home / ".ssh" / "config.d" / "hosts",
    }


def _run(script, stub, *args, env_extra=None, secrets=True):
    env = {
        "PATH": f"{stub['bin']}:{os.environ['PATH']}",
        "HOME": str(stub["home"]),
        "DEVHOST_LOCAL_DIR": str(stub["local"]),
    }
    if secrets:
        env["DEVHOST_OP_TOKEN"] = TOKEN
        env["DEVHOST_TS_AUTH_KEY"] = AUTH_KEY
    env.update({k: str(v) for k, v in (env_extra or {}).items()})
    return subprocess.run(
        ["bash", str(script), *args], env=env, capture_output=True, text=True, timeout=30
    )


def _argv(stub):
    return stub["argv"].read_text().splitlines() if stub["argv"].exists() else []


def _stdin(stub):
    return stub["stdin"].read_text() if stub["stdin"].exists() else ""


def _index(lines, needle):
    return next(i for i, line in enumerate(lines) if needle in line)


def _write_ssh(stub, text):
    stub["ssh"].parent.mkdir(parents=True, exist_ok=True)
    stub["ssh"].write_text(text)


def test_new_refuses_protected_and_existing_names(stub):
    stub["machines"].write_text("picklelab-golden\nopenclaw\nalready-there\n")
    for name in ("picklelab", "picklelab-golden", "already-there"):
        stub["argv"].unlink(missing_ok=True)
        r = _run(NEW, stub, name)
        assert r.returncode == 1, (name, r.stderr)
        assert not any("clone" in line for line in _argv(stub)), name
        assert not stub["local"].exists()


@pytest.mark.parametrize("name", ["", "Bad Name", "../etc", "UPPER", "-lead"])
def test_new_refuses_unsafe_names(stub, name):
    r = _run(NEW, stub, *([name] if name else []))
    assert r.returncode == 1
    assert _argv(stub) == []


@pytest.mark.parametrize("var", ["DEVHOST_OP_TOKEN", "DEVHOST_TS_AUTH_KEY"])
@pytest.mark.parametrize("how", ["unset", "empty"])
def test_new_fails_before_clone_when_a_secret_is_missing(stub, var, how):
    env = {"DEVHOST_OP_TOKEN": TOKEN, "DEVHOST_TS_AUTH_KEY": AUTH_KEY}
    if how == "empty":
        env[var] = ""
    else:
        del env[var]
    r = _run(NEW, stub, "dev1", env_extra=env, secrets=False)
    assert r.returncode == 1
    assert var in r.stderr
    assert not any("clone" in line for line in _argv(stub))
    assert TOKEN not in r.stderr and AUTH_KEY not in r.stderr


def test_new_refuses_foreign_host_block_before_clone(stub):
    _write_ssh(stub, FOREIGN_BLOCK)
    r = _run(NEW, stub, "picklelab-dev")
    assert r.returncode == 1
    assert str(stub["ssh"]) in r.stderr
    assert not any("clone" in line for line in _argv(stub))
    assert stub["ssh"].read_text() == FOREIGN_BLOCK


def test_new_foreign_check_ignores_hosts_with_other_names(stub):
    _write_ssh(stub, "Host picklelab-dev-two\n    HostName x\n")
    r = _run(NEW, stub, "picklelab-dev")
    assert r.returncode == 0, r.stderr


def test_new_happy_path_order(stub):
    _write_ssh(stub, FOREIGN_BLOCK)
    r = _run(NEW, stub, "dev1")
    assert r.returncode == 0, r.stderr
    lines = _argv(stub)

    steps = [
        "clone picklelab-golden dev1",
        "config set machine.dev1.isolated true",
        "config set machine.dev1.isolate_network true",
        "config set machine.dev1.forward_ssh_agent true",
        "start dev1",
        "-m dev1 sudo tee /etc/opt/homelab/host.env",
        "/etc/opt/homelab/op-token-picklehome",
        "/etc/opt/homelab/op-token-pickleclaw",
        "-m dev1 sudo systemctl stop tailscaled",
        "-m dev1 sudo find /var/lib/tailscale -mindepth 1 -delete",
        "-m dev1 sudo systemctl start tailscaled",
        "tailscale up",
    ]
    positions = [_index(lines, s) for s in steps]
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)

    # The tailscale state wipe sits between stopping and starting the daemon, and
    # all of it happens before `tailscale up`.
    up = lines[_index(lines, "tailscale up")]
    assert "--hostname" in up and "dev1" in up
    assert "--advertise-tags=tag:devhost" in up

    # Every orb call after the list check names the machine it acts on.
    for line in lines:
        assert (
            line.startswith("list")
            or line.startswith("clone picklelab-golden dev1")
            or line.startswith("config set machine.dev1.")
            or line.startswith("start dev1")
            or line.startswith("-m dev1 ")
        ), line

    # The foreign block survives, ours follows it, marked.
    ssh = stub["ssh"].read_text()
    assert ssh.startswith(FOREIGN_BLOCK)
    assert ssh.endswith(
        "# devhost dev1 begin\nHost dev1\n    HostName dev1.orb.local\n# devhost dev1 end\n"
    )


def test_new_writes_identity_and_tokens_on_stdin_only(stub):
    r = _run(NEW, stub, "dev1")
    assert r.returncode == 0, r.stderr

    local = (stub["local"] / "dev1.env").read_text()
    assert local == IDENTITY.read_text() + "HOMELAB_HOST_NAME=dev1\n"

    sections = _stdin(stub).split("## ")[1:]
    by_target = {}
    for sec in sections:
        header, _, body = sec.partition("\n")
        by_target[header] = body
    host_env = next(v for k, v in by_target.items() if "/etc/opt/homelab/host.env" in k)
    assert host_env == local
    for path in ("op-token-picklehome", "op-token-pickleclaw"):
        body = next(v for k, v in by_target.items() if path in k)
        assert body == f"OP_SERVICE_ACCOUNT_TOKEN={TOKEN}\n"
        header = next(k for k in by_target if path in k)
        # Created under umask 077 and chmod 0600, never world-readable.
        assert "umask 077" in header and "chmod 0600" in header
    key_section = next(v for k, v in by_target.items() if "tailscale up" in k)
    assert key_section == f"{AUTH_KEY}\n"


def test_new_never_leaks_secrets_into_argv_or_output(stub):
    r = _run(NEW, stub, "dev1")
    assert r.returncode == 0, r.stderr
    for secret in (TOKEN, AUTH_KEY):
        assert secret not in stub["argv"].read_text()
        assert secret not in r.stdout
        assert secret not in r.stderr
        assert secret not in (stub["local"] / "dev1.env").read_text()
        assert secret not in stub["ssh"].read_text()


def test_new_children_do_not_inherit_the_secrets(stub):
    envdump = stub["home"].parent / "envdump"
    orb = stub["bin"] / "orb"
    orb.write_text(orb.read_text().replace("exit 0\n", f"env >> {envdump}\nexit 0\n"))
    r = _run(NEW, stub, "dev1")
    assert r.returncode == 0, r.stderr
    dumped = envdump.read_text()
    assert "DEVHOST_OP_TOKEN" not in dumped
    assert "DEVHOST_TS_AUTH_KEY" not in dumped


def test_new_rerun_replaces_its_own_block_and_keeps_the_rest(stub):
    _write_ssh(
        stub,
        FOREIGN_BLOCK
        + "# devhost dev1 begin\nHost dev1\n    HostName stale.orb.local\n# devhost dev1 end\n"
        + "Host other\n    HostName other.example\n",
    )
    r = _run(NEW, stub, "dev1")
    assert r.returncode == 0, r.stderr
    ssh = stub["ssh"].read_text()
    assert ssh.count("Host dev1\n") == 1
    assert "stale.orb.local" not in ssh
    assert "Host picklelab-dev\n" in ssh and "Host other\n" in ssh


def test_new_leaves_a_cleanable_host_when_a_later_step_fails(stub):
    r = _run(NEW, stub, "dev1", env_extra={"STUB_FAIL_ON": "start dev1"})
    assert r.returncode != 0
    assert "just devhost-rm dev1" in r.stderr
    assert (stub["local"] / "dev1.env").exists()
    assert not any("tailscale up" in line for line in _argv(stub))
    assert not stub["ssh"].exists()


def test_rm_removes_machine_local_file_and_ssh_block(stub):
    stub["machines"].write_text("openclaw\ndev1\n")
    stub["local"].mkdir()
    (stub["local"] / "dev1.env").write_text("HOMELAB_HOST_NAME=dev1\n")
    (stub["local"] / "dev2.env").write_text("HOMELAB_HOST_NAME=dev2\n")
    _write_ssh(
        stub,
        FOREIGN_BLOCK
        + "# devhost dev1 begin\nHost dev1\n    HostName dev1.orb.local\n# devhost dev1 end\n"
        + "# devhost dev2 begin\nHost dev2\n    HostName dev2.orb.local\n# devhost dev2 end\n",
    )
    r = _run(RM, stub, "dev1", secrets=False)
    assert r.returncode == 0, r.stderr
    assert "delete -f dev1" in _argv(stub)
    assert not (stub["local"] / "dev1.env").exists()
    assert (stub["local"] / "dev2.env").exists()
    ssh = stub["ssh"].read_text()
    assert "dev1" not in ssh
    assert "Host dev2\n" in ssh and ssh.startswith(FOREIGN_BLOCK)


def test_rm_leaves_a_foreign_host_block_intact(stub):
    # A hand-written block with the same name as the dev host, no markers.
    stub["machines"].write_text("picklelab-dev\n")
    stub["local"].mkdir()
    (stub["local"] / "picklelab-dev.env").write_text("HOMELAB_HOST_NAME=picklelab-dev\n")
    _write_ssh(stub, FOREIGN_BLOCK)
    r = _run(RM, stub, "picklelab-dev", secrets=False)
    assert r.returncode == 0, r.stderr
    assert stub["ssh"].read_text() == FOREIGN_BLOCK


def test_rm_works_when_there_is_no_ssh_file(stub):
    stub["machines"].write_text("dev1\n")
    stub["local"].mkdir()
    (stub["local"] / "dev1.env").write_text("x=1\n")
    r = _run(RM, stub, "dev1", secrets=False)
    assert r.returncode == 0, r.stderr
    assert not stub["ssh"].exists()


def test_rm_skips_delete_when_the_machine_is_already_gone(stub):
    stub["local"].mkdir()
    (stub["local"] / "dev1.env").write_text("x=1\n")
    r = _run(RM, stub, "dev1", secrets=False)
    assert r.returncode == 0, r.stderr
    assert not any(" delete " in f" {line} " for line in _argv(stub))
    assert not (stub["local"] / "dev1.env").exists()


@pytest.mark.parametrize("name", ["picklelab", "picklelab-golden"])
def test_rm_refuses_protected_names(stub, name):
    stub["machines"].write_text(f"{name}\n")
    stub["local"].mkdir()
    (stub["local"] / f"{name}.env").write_text("x=1\n")
    r = _run(RM, stub, name, secrets=False)
    assert r.returncode == 1
    assert "refus" in r.stderr.lower()
    assert not any("delete" in line for line in _argv(stub))


def test_rm_refuses_machines_devhost_new_did_not_make(stub):
    stub["machines"].write_text("openclaw\n")
    r = _run(RM, stub, "openclaw", secrets=False)
    assert r.returncode == 1
    assert "openclaw.env" in r.stderr
    assert not any("delete" in line for line in _argv(stub))


def test_ls_lists_each_local_file_with_the_machine_state(stub):
    stub["local"].mkdir()
    for n in ("alpha", "beta", "gone"):
        (stub["local"] / f"{n}.env").write_text("x=1\n")
    stub["table"].write_text(
        "alpha     running  ubuntu  noble  arm64  4.1 GB  192.168.139.9\n"
        "beta      stopped  ubuntu  noble  arm64  4.1 GB\n"
        "openclaw  running  ubuntu  resolute  arm64  6.6 GB  192.168.139.74\n"
    )
    r = _run(LS, stub, secrets=False)
    assert r.returncode == 0, r.stderr
    rows = [line.split() for line in r.stdout.splitlines()]
    assert rows == [["alpha", "running"], ["beta", "stopped"], ["gone", "missing"]]


def test_ls_with_no_dev_hosts(stub):
    r = _run(LS, stub, secrets=False)
    assert r.returncode == 0
    assert "no dev hosts" in r.stdout
