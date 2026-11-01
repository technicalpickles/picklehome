"""Tests for homelab/scripts/host-identity.sh.

The helper is sourced by deploy scripts and exports per-host constants (service
name suffix, secondary vault, ...) read from an identity file. These tests source
it in a throwaway bash with a controlled environment, then inspect what it
exported or how it exited.
"""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "homelab" / "scripts" / "host-identity.sh"

REQUIRED = [
    "HOMELAB_HOST_KIND",
    "HOMELAB_SERVICE_SUFFIX",
    "HOMELAB_ENV_OVERLAY",
    "HOMELAB_SECONDARY_VAULT",
    "BRINEWORKS_REF",
    "PICKLECLAW_REF",
    "HOMELAB_HOST_ALIASES",
]

DEV_FILE = """\
HOMELAB_HOST_KIND=dev
HOMELAB_SERVICE_SUFFIX=-dev
HOMELAB_ENV_OVERLAY=dev
HOMELAB_SECONDARY_VAULT=picklehome-dev
BRINEWORKS_REF=main
PICKLECLAW_REF=main
HOMELAB_HOST_ALIASES=
"""


def _source_raw(tmp_path, host, extra_env=None, snippet="env | grep -E '^(HOMELAB_|BRINEWORKS_REF|PICKLECLAW_REF)'"):
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "HOMELAB_REPO_DIR": str(ROOT),
    }
    if host is not None:
        env["HOMELAB_HOST_NAME"] = host
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "{HELPER}"; {snippet}'],
        env=env, capture_output=True, text=True, timeout=30,
    )


def _source(tmp_path, host, extra_env=None, snippet=None):
    kwargs = {} if snippet is None else {"snippet": snippet}
    r = _source_raw(tmp_path, host, extra_env, **kwargs)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _write_host_file(tmp_path, text=DEV_FILE):
    f = tmp_path / "host.env"
    f.write_text(text)
    return f


def test_picklelab_identity_matches_todays_constants(tmp_path):
    out = _source(tmp_path, "picklelab")
    assert "HOMELAB_HOST_KIND=prod" in out
    assert re.search(r"^HOMELAB_SERVICE_SUFFIX=$", out, re.M)
    assert re.search(r"^HOMELAB_ENV_OVERLAY=$", out, re.M)
    assert "HOMELAB_SECONDARY_VAULT=Brent Pickleclaw" in out
    assert "BRINEWORKS_REF=main" in out and "PICKLECLAW_REF=main" in out
    assert "HOMELAB_HOST_NAME=picklelab" in out
    assert "picklelab.tail2023b7.ts.net" in out


def test_missing_identity_exits_78(tmp_path):
    r = _source_raw(tmp_path, "nope", extra_env={"HOMELAB_HOST_FILE": ""})
    assert r.returncode == 78
    assert "homelab/hosts/nope.env" in r.stderr
    assert "/etc/opt/homelab/host.env" in r.stderr


def test_box_file_is_the_fallback(tmp_path):
    f = _write_host_file(tmp_path)
    out = _source(tmp_path, "zz", extra_env={"HOMELAB_HOST_FILE": str(f)})
    assert "HOMELAB_HOST_KIND=dev" in out
    assert "HOMELAB_SERVICE_SUFFIX=-dev" in out
    assert "HOMELAB_SECONDARY_VAULT=picklehome-dev" in out
    assert "HOMELAB_HOST_NAME=zz" in out


def test_required_key_missing_exits_78(tmp_path):
    f = _write_host_file(tmp_path, DEV_FILE.replace("HOMELAB_SECONDARY_VAULT=picklehome-dev\n", ""))
    r = _source_raw(tmp_path, "zz", extra_env={"HOMELAB_HOST_FILE": str(f)})
    assert r.returncode == 78
    assert "HOMELAB_SECONDARY_VAULT" in r.stderr


def test_every_required_key_is_enforced(tmp_path):
    for key in REQUIRED:
        lines = [ln for ln in DEV_FILE.splitlines(keepends=True) if not ln.startswith(key + "=")]
        f = _write_host_file(tmp_path, "".join(lines))
        r = _source_raw(tmp_path, "zz", extra_env={"HOMELAB_HOST_FILE": str(f)})
        assert r.returncode == 78, key
        assert key in r.stderr, key


def test_inherited_environment_cannot_satisfy_a_required_key(tmp_path):
    # A stray prod value in the caller's environment must not paper over a file
    # that forgot the key.
    f = _write_host_file(tmp_path, DEV_FILE.replace("HOMELAB_SERVICE_SUFFIX=-dev\n", ""))
    r = _source_raw(tmp_path, "zz", extra_env={"HOMELAB_HOST_FILE": str(f), "HOMELAB_SERVICE_SUFFIX": ""})
    assert r.returncode == 78
    assert "HOMELAB_SERVICE_SUFFIX" in r.stderr


def test_explicit_host_file_that_does_not_exist_exits_78(tmp_path):
    r = _source_raw(tmp_path, "picklelab", extra_env={"HOMELAB_HOST_FILE": str(tmp_path / "gone.env")})
    assert r.returncode == 78
    assert "gone.env" in r.stderr


def test_host_name_from_environment_wins_over_file(tmp_path):
    f = _write_host_file(tmp_path, DEV_FILE + "HOMELAB_HOST_NAME=from-file\n")
    out = _source(tmp_path, "from-env", extra_env={"HOMELAB_HOST_FILE": str(f)})
    assert "HOMELAB_HOST_NAME=from-env" in out


def test_host_name_from_file_when_environment_unset(tmp_path):
    f = _write_host_file(tmp_path, DEV_FILE + "HOMELAB_HOST_NAME=from-file\n")
    out = _source(tmp_path, None, extra_env={"HOMELAB_HOST_FILE": str(f)})
    assert "HOMELAB_HOST_NAME=from-file" in out


def test_host_name_falls_back_to_hostname_and_is_exported(tmp_path):
    f = _write_host_file(tmp_path)
    expected = subprocess.run(["hostname", "-s"], capture_output=True, text=True).stdout.strip()
    out = _source(tmp_path, None, extra_env={"HOMELAB_HOST_FILE": str(f)},
                  snippet="bash -c 'echo got=$HOMELAB_HOST_NAME'")
    assert f"got={expected}" in out


def test_executing_instead_of_sourcing_is_refused(tmp_path):
    r = subprocess.run(["bash", str(HELPER)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 64
    assert "source" in r.stderr


def test_dev_identity_template_satisfies_the_helper(tmp_path):
    template = ROOT / "homelab" / "hosts" / "dev-identity.env"
    out = _source(tmp_path, "some-dev-box", extra_env={"HOMELAB_HOST_FILE": str(template)})
    assert "HOMELAB_HOST_KIND=dev" in out
    assert "HOMELAB_SERVICE_SUFFIX=-dev" in out
    assert "HOMELAB_ENV_OVERLAY=dev" in out
    assert "HOMELAB_SECONDARY_VAULT=picklehome-dev" in out
    assert "HOMELAB_HOST_NAME=some-dev-box" in out


def test_every_deploy_sh_that_uses_identity_sources_it():
    for f in (ROOT / "homelab" / "services").glob("*/deploy.sh"):
        text = f.read_text()
        if "HOMELAB_" in text:
            assert "host-identity.sh" in text, f


def test_deploy_scripts_have_no_bare_service_names_left():
    # Every svc: name must carry the suffix, so a dev box can't serve a prod name.
    bare = re.compile(r"svc:(openclaw-widgets|openclaw|brineworks)(?!-widgets)(?!\$\{HOMELAB_SERVICE_SUFFIX\?\})")
    for name in ("openclaw", "brineworks-server"):
        f = ROOT / "homelab" / "services" / name / "deploy.sh"
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            assert not bare.search(line), f"{f}:{n}: {line}"
