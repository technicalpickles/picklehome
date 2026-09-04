#!/usr/bin/env python3
"""scripts/secret_entry.py -- type secrets into .env from a phone, over the tailnet.

A temporary bridge for when `op` cannot reach the 1Password desktop app (a
phone-driven session, or the sandbox blocking the socket -- see root CLAUDE.md's
Sandbox section). The alternative is pasting a password into an agent transcript.

Values are never printed, logged, or echoed. See
docs/plans/2026-09-04-moen-flo-design.md, Phase 0.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

VALID_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote(value: str) -> str:
    """Double-quote a value, escaping backslashes and quotes.

    Always quoting (rather than only when the value contains a space) keeps
    passwords with `#`, spaces, or quotes parseable by python-dotenv, which is
    what loads .env for every module in this repo. Mirrors what
    scripts/quote-env-values does to op-injected values.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def upsert_env_vars(path: Path, values: dict[str, str]) -> None:
    """Write KEY=value pairs into an env file, replacing existing keys in place.

    Existing keys keep their original position so a hand-edited .env does not get
    reordered. Comments, blank lines, and unrelated variables are preserved
    verbatim. The file is left owner-readable only.

    Raises ValueError on:
    - a key that is not a legal shell/env identifier
    - a value containing ${...} (python-dotenv interpolates this regardless of quoting)
    - a value containing a literal newline (corrupts file structure on next write)

    No file is written if validation fails.
    """
    for key in values:
        if not VALID_KEY.match(key):
            raise ValueError(f"{key!r} is not a valid env var name")

    for value in values.values():
        if "${" in value:
            raise ValueError(
                f"Value contains '${{...}}' which python-dotenv interpolates "
                f"regardless of quoting. Put the secret in 1Password instead."
            )
        if "\n" in value:
            raise ValueError("Value contains a literal newline, which corrupts the file")

    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict.fromkeys(values)  # Preserves insertion order; acts as ordered set

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            continue

        # Handle optional `export ` prefix and preserve it on rewrite
        prefix = ""
        key_part = stripped
        if key_part.startswith("export "):
            prefix = "export "
            key_part = key_part[7:]

        key = key_part.split("=", 1)[0].strip()
        if key in values:
            lines[i] = f"{prefix}{key}={_quote(values[key])}"
            remaining.pop(key, None)  # Mark as seen; will not re-append

    for key in remaining:
        lines.append(f"{key}={_quote(values[key])}")

    # Create file with 0o600 permissions from the start, then write content
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")

    # Ensure permissions even if file existed with looser perms
    path.chmod(0o600)
