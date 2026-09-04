#!/usr/bin/env python3
"""scripts/secret_entry.py -- type secrets into .env from a phone, over the tailnet.

A temporary bridge for when `op` cannot reach the 1Password desktop app (a
phone-driven session, or the sandbox blocking the socket -- see root CLAUDE.md's
Sandbox section). The alternative is pasting a password into an agent transcript.

Values are never printed, logged, or echoed. See
docs/plans/2026-09-04-moen-flo-design.md, Phase 0.
"""

from __future__ import annotations

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

    Raises ValueError on a key that is not a legal shell/env identifier, rather
    than writing a line that python-dotenv would silently skip.
    """
    for key in values:
        if not VALID_KEY.match(key):
            raise ValueError(f"{key!r} is not a valid env var name")

    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(values)

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={_quote(remaining.pop(key))}"

    for key, value in remaining.items():
        lines.append(f"{key}={_quote(value)}")

    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
