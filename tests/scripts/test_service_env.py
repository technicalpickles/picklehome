"""Tests for scripts/service-env, focused on the --overlay option.

service-env picks the wanted keys (from a .env.vars file) out of a base
template. An overlay file lets a dev host swap individual keys for its own
references while every other key resolves from the same base.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "service-env"
DEV_OVERLAY = ROOT / "homelab" / "hosts" / "overlays" / "dev.env.template"
BASE_TEMPLATE = ROOT / ".env.template"
OPENCLAW_VARS = ROOT / "homelab" / "services" / "openclaw" / ".env.vars"

# The vault whose entries a dev host's service account cannot read.
BLOCKED_VAULT = "Brent Pickleclaw"


def _run(tmp_path, *, base, overlay=None, wanted, template=True, overlay_path=None):
    base_f = tmp_path / "base"
    base_f.write_text(base)
    vars_f = tmp_path / "vars"
    vars_f.write_text("".join(f"{k}\n" for k in wanted))
    cmd = [str(SCRIPT), str(vars_f), "--template" if template else "--env", str(base_f)]
    if overlay is not None:
        overlay_f = tmp_path / "overlay"
        overlay_f.write_text(overlay)
        cmd += ["--overlay", str(overlay_f)]
    if overlay_path is not None:
        cmd += ["--overlay", str(overlay_path)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def test_overlay_key_wins(tmp_path):
    r = _run(
        tmp_path,
        base="A=op://picklehome/x/a\nB=op://picklehome/x/b\n",
        overlay="A=op://picklehome-dev/x/a\n",
        wanted=["A", "B"],
        template=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "A=op://picklehome-dev/x/a\nB=op://picklehome/x/b\n"


def test_overlay_absent_key_falls_through(tmp_path):
    r = _run(
        tmp_path,
        base="A=op://picklehome/x/a\nB=op://picklehome/x/b\n",
        overlay="B=op://picklehome-dev/x/b\n",
        wanted=["A", "B"],
        template=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "A=op://picklehome/x/a\nB=op://picklehome-dev/x/b\n"
    assert r.stderr == ""


def test_overlay_unknown_key_warns(tmp_path):
    r = _run(
        tmp_path,
        base="A=op://picklehome/x/a\n",
        overlay="C=op://picklehome-dev/x/c\n",
        wanted=["A"],
        template=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "A=op://picklehome/x/a\n"
    assert "WARNING: overlay key C" in r.stderr


def test_overlay_key_in_base_but_not_vars_does_not_warn(tmp_path):
    # Shared overlay: brineworks-server's vars list doesn't include openclaw's
    # keys, but they exist in the base template, so that is not a typo.
    r = _run(
        tmp_path,
        base="A=op://picklehome/x/a\nB=op://picklehome/x/b\n",
        overlay="B=op://picklehome-dev/x/b\n",
        wanted=["A"],
        template=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "A=op://picklehome/x/a\n"
    assert r.stderr == ""


def test_overlay_key_in_vars_but_not_base_is_emitted(tmp_path):
    r = _run(
        tmp_path,
        base="A=op://picklehome/x/a\n",
        overlay="B=op://picklehome-dev/x/b\n",
        wanted=["A", "B"],
        template=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "A=op://picklehome/x/a\nB=op://picklehome-dev/x/b\n"
    assert r.stderr == ""


def test_overlay_missing_file_fails(tmp_path):
    r = _run(
        tmp_path,
        base="A=op://picklehome/x/a\n",
        wanted=["A"],
        template=False,
        overlay_path=tmp_path / "does-not-exist",
    )
    assert r.returncode == 1
    assert "overlay file not found" in r.stderr


def test_overlay_mustache_stripped(tmp_path):
    r = _run(
        tmp_path,
        base="A={{ op://picklehome/x/a }}\nB={{ op://picklehome/x/b }}\n",
        overlay="A={{ op://picklehome-dev/x/a }}\n",
        wanted=["A", "B"],
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "A=op://picklehome-dev/x/a\nB=op://picklehome/x/b\n"


def test_overlay_comments_and_blank_lines_ignored(tmp_path):
    r = _run(
        tmp_path,
        base="A=op://picklehome/x/a\n",
        overlay="# a comment mentioning A=oops\n\nA=op://picklehome-dev/x/a\n",
        wanted=["A"],
        template=False,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "A=op://picklehome-dev/x/a\n"
    assert r.stderr == ""


def test_no_overlay_output_unchanged(tmp_path):
    r = _run(
        tmp_path,
        base="A={{ op://picklehome/x/a }}\n",
        wanted=["A", "MISSING"],
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "A=op://picklehome/x/a\n"
    assert "WARNING: MISSING not found" in r.stderr


def _keys_with_vault(text, vault):
    """Keys whose template value references `vault`."""
    pattern = re.compile(r"^([A-Z0-9_]+)=\{\{\s*op://" + re.escape(vault) + r"/", re.M)
    return set(pattern.findall(text))


def _wanted_keys(path):
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def test_dev_overlay_covers_every_blocked_vault_key_openclaw_uses():
    """A dev host's service account can't read the blocked vault, so every
    openclaw key whose base reference points there must be overridden."""
    base = BASE_TEMPLATE.read_text()
    blocked = _keys_with_vault(base, BLOCKED_VAULT) & _wanted_keys(OPENCLAW_VARS)
    assert blocked, "expected openclaw to use some keys from the blocked vault"
    overlay_keys = set(re.findall(r"^([A-Z0-9_]+)=", DEV_OVERLAY.read_text(), re.M))
    assert blocked <= overlay_keys, sorted(blocked - overlay_keys)


def test_dev_overlay_only_references_dev_vault():
    for line in DEV_OVERLAY.read_text().splitlines():
        if re.match(r"^[A-Z0-9_]+=", line):
            assert "picklehome-dev/" in line, line
            assert BLOCKED_VAULT not in line, line


def test_dev_overlay_has_no_literal_reference_scheme_in_comments():
    for line in DEV_OVERLAY.read_text().splitlines():
        if line.lstrip().startswith("#"):
            assert "op://" not in line, line
            assert "{{" not in line, line


def test_dev_overlay_keys_all_exist_in_base_template():
    base_keys = set(re.findall(r"^([A-Z0-9_]+)=", BASE_TEMPLATE.read_text(), re.M))
    overlay_keys = set(re.findall(r"^([A-Z0-9_]+)=", DEV_OVERLAY.read_text(), re.M))
    assert overlay_keys <= base_keys, sorted(overlay_keys - base_keys)


def test_dev_overlay_against_real_openclaw_has_no_warnings():
    r = subprocess.run(
        [str(SCRIPT), str(OPENCLAW_VARS), "--template", str(BASE_TEMPLATE), "--overlay", str(DEV_OVERLAY)],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "overlay key" not in r.stderr
    # Nothing readable only by the prod service account may remain on the
    # secondary-vault side of a dev host.
    assert f"/{BLOCKED_VAULT}/" not in r.stdout
