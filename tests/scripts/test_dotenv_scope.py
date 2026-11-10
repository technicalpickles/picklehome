"""The local .env resolves only the keys local code reads.

.env.local.vars is the allowlist `just dotenv` applies to .env.template. These
tests pin the two ways it goes wrong: a typo that names a key the template lacks,
and a local module that reads a template key the list omits (which shows up later
as "X not set" at runtime).
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".env.template"
LOCAL_VARS = ROOT / ".env.local.vars"

# Code that runs on the Mac. homelab/ runs on the host and docs/ and tests/ only
# mention keys, so none of them need a local value.
LOCAL_CODE = [
    "climate", "lighting", "network", "garage", "locks", "nest", "sonos",
    "lg", "water", "picklehome", "Justfile",
]


def _keys(path):
    return {
        line.split()[0]
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _template_keys():
    return set(re.findall(r"^([A-Z0-9_]+)=", TEMPLATE.read_text(), re.M))


def _local_sources():
    for name in LOCAL_CODE:
        p = ROOT / name
        if p.is_file():
            yield p
        else:
            yield from (f for f in p.rglob("*") if f.suffix in {".py", ".sh"} and ".venv" not in f.parts)


def test_every_listed_key_exists_in_template():
    assert _keys(LOCAL_VARS) <= _template_keys()


def test_local_code_reads_only_listed_keys():
    template = _template_keys()
    listed = _keys(LOCAL_VARS)
    # PICKLEHOME_LOCATIONS and the Lutron cert paths are written by scripts/dotenv itself.
    read = {}
    for src in _local_sources():
        text = src.read_text(errors="ignore")
        for key in template:
            if re.search(rf"\b{key}\b", text):
                read.setdefault(key, src.relative_to(ROOT))
    # Justfile mentions of deploy keys sit in comments and remote ssh strings.
    ignore_in_justfile = {
        k for k, src in read.items() if str(src) == "Justfile" and k not in listed
    }
    missing = {k: str(s) for k, s in read.items() if k not in listed and k not in ignore_in_justfile}
    assert not missing, f"local code reads keys absent from .env.local.vars: {missing}"


def test_dotenv_filter_keeps_only_listed_keys(tmp_path):
    template = tmp_path / "t"
    template.write_text("# comment\nKEEP=op://v/i/f\nDROP=op://v/i/g\n")
    vars_f = tmp_path / "v"
    vars_f.write_text("# local\nKEEP\n")
    # Run a copy of the scripts inside tmp_path so the cert step writes there, not
    # into the real lighting/.certs.
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("dotenv", "quote-env-values", "locations-filter.jq"):
        (scripts / name).write_bytes((ROOT / "scripts" / name).read_bytes())
        (scripts / name).chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    op = bin_dir / "op"
    op.write_text(
        "#!/usr/bin/env bash\n"
        'case "$1" in\n'
        '  inject) cp "$4" "$6" ;;\n'
        "  item) echo '[]' ;;\n"
        "  read) echo placeholder ;;\n"
        "esac\n"
    )
    op.chmod(0o755)
    out = tmp_path / "out"
    r = subprocess.run(
        [str(scripts / "dotenv"), "--template", str(template), "--vars", str(vars_f), "--output", str(out)],
        capture_output=True, text=True, timeout=30, cwd=tmp_path,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(tmp_path)},
    )
    content = out.read_text() if out.exists() else ""
    assert "KEEP=" in content and "DROP=" not in content, (r.stdout, r.stderr)
