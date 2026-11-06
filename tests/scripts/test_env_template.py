"""Guards for .env.template, the single file both secret paths read.

service-env filters it by name for deploys, and `op inject` parses all of it
for `just dotenv`. A key that drifts out of it, a duplicate, or a literal
reference scheme in a comment breaks one of those paths quietly or loudly.
"""
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / ".env.template"
VARS_FILES = sorted((ROOT / "homelab" / "services").glob("*/.env.vars"))

# Built from pieces so this file never contains the scheme literally.
REF_SCHEME = "op:" + "//"
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")


def _template_keys():
    keys = []
    for line in TEMPLATE.read_text().splitlines():
        m = KEY_RE.match(line)
        if m:
            keys.append(m.group(1))
    return keys


def _vars_keys(path):
    keys = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keys.append(line)
    return keys


def test_vars_files_found():
    assert VARS_FILES, "no homelab/services/*/.env.vars files found"


def test_every_env_vars_key_exists_in_template():
    template = set(_template_keys())
    missing = {
        str(p.relative_to(ROOT)): sorted(k for k in _vars_keys(p) if k not in template)
        for p in VARS_FILES
    }
    missing = {p: ks for p, ks in missing.items() if ks}
    assert not missing, f"keys in .env.vars but not in .env.template: {missing}"


def test_template_has_no_duplicate_keys():
    # service-env takes the first match (grep -m1) while op inject keeps the
    # last, so a duplicate can resolve to different items per path.
    dupes = sorted(k for k, n in Counter(_template_keys()).items() if n > 1)
    assert not dupes, f"duplicate keys in .env.template: {dupes}"


def test_no_reference_scheme_in_comments():
    # op inject parses comments too and fails the whole run on prose that looks
    # like a reference.
    bad = [
        i
        for i, line in enumerate(TEMPLATE.read_text().splitlines(), 1)
        if line.lstrip().startswith("#") and REF_SCHEME in line
    ]
    assert not bad, f"literal reference scheme in comment lines: {bad}"
