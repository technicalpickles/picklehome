#!/usr/bin/env python3
"""scripts/secret_entry.py -- type secrets from a phone, over the tailnet.

An escape hatch for entering secrets when `op` cannot reach the 1Password desktop
app (a phone-driven session, or the sandbox blocking the socket -- see root
CLAUDE.md's Sandbox section). The alternative is pasting a password into an agent
transcript.

Two sinks: `env` (default) upserts into a .env file; `av` stores Automic Vault
Project Values via `av save --stdin`, approved on the Mac or an enrolled iPhone,
so nothing lands on disk in plaintext.

Values are never printed, logged, or echoed. See
docs/plans/2026-09-04-moen-flo-design.md, Phase 0.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

VALID_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

TAILSCALE_FALLBACK = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
SERVE_PORT = 8443  # not 443: the node's / route on 443 is already in use
IDLE_TIMEOUT_SECONDS = 15 * 60

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>secret entry</title>
<style>
 body{{font:16px/1.5 system-ui;margin:0;padding:2rem;max-width:30rem}}
 label{{display:block;margin:1.25rem 0 .25rem;font-weight:600}}
 input{{width:100%;padding:.75rem;font-size:1rem;box-sizing:border-box}}
 button{{margin-top:1.5rem;padding:.85rem 1.5rem;font-size:1rem;width:100%}}
</style></head>
<body><form method="post"><h1>Enter secrets</h1>{fields}
<button type="submit">Save to {target}</button></form></body></html>
"""


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
    - a value containing a literal newline or carriage return (corrupts file
      structure on next write)

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
        if "\n" in value or "\r" in value:
            # path.read_text() below uses universal newlines, so a lone \r
            # round-trips to \n on the next read and corrupts the file the
            # same way an unescaped \n would -- reject both here, not just \n.
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

    # Write to a sibling temp file (created 0600 from the start, same as
    # before) and os.replace() it into place, rather than truncating path
    # in place. A value entered here may have no other copy (that's the
    # point of an escape hatch for when 1Password is unreachable), and
    # `set dotenv-load` means a malformed .env breaks
    # every recipe in the repo, not just this one -- an interrupt between
    # O_TRUNC and the write used to be able to leave a truncated file with
    # nothing to recover it. os.replace() is atomic on POSIX, so readers
    # only ever see the old complete file or the new complete file.
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(str(tmp_path), str(path))
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    # Ensure permissions even if the file previously existed with looser
    # perms: the temp file is created 0600, and os.replace() carries that
    # mode into place, but chmod again so this holds regardless of platform
    # or umask quirks.
    path.chmod(0o600)


class AvSaveError(Exception):
    """`av save` exited nonzero for one key.

    Carries which keys already landed, because each key is a separate save
    (and a separate Approval), so a failure partway through is a real state
    the person on the phone needs to know about.
    """

    def __init__(self, key: str, saved: list[str], returncode: int, detail: str) -> None:
        self.key = key
        self.saved = saved
        landed = ", ".join(saved) if saved else "none"
        super().__init__(f"av save {key} failed (exit {returncode}): {detail} [saved: {landed}]")


def save_to_av(values: dict[str, str], project_dir: Path) -> None:
    """Store each value as an Automic Vault Project Value, one `av save` per key.

    The value goes over stdin, never argv or env, so it can't show up in `ps`
    or in anything that logs the command line. `--stdin` stores the bytes
    verbatim, so none of upsert_env_vars' python-dotenv restrictions apply.

    Blocks until the Approval is decided (on the Mac, or the iPhone when iPhone
    Approval is enabled). Stops at the first failure.
    """
    for key in values:
        if not VALID_KEY.match(key):
            raise ValueError(f"{key!r} is not a valid env var name")

    saved: list[str] = []
    for key, value in values.items():
        result = subprocess.run(
            ["av", "save", "--stdin", f"--project-directory={project_dir}", key],
            input=value.encode(),
            capture_output=True,
        )
        if result.returncode != 0:
            # av's stderr is shown on the phone; scrub the value in case a
            # future av version ever echoes input back in an error.
            detail = result.stderr.decode(errors="replace").strip().replace(value, "[redacted]")
            raise AvSaveError(key, saved, result.returncode, detail or "no output")
        saved.append(key)


def default_project_dir() -> Path:
    """The main checkout's root, so one Project Value covers every worktree.

    Worktrees live under <root>/.claude/worktrees/, and av selects the nearest
    physical parent directory holding a Project Value. `--show-toplevel` would
    give the worktree itself, scoping the secret to a directory that gets
    deleted when the branch merges.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip()).parent


def _tailscale_binary() -> str:
    """Locate the tailscale CLI, which the macOS GUI app does not put on PATH."""
    found = shutil.which("tailscale")
    if found:
        return found
    if os.path.exists(TAILSCALE_FALLBACK):
        return TAILSCALE_FALLBACK
    raise RuntimeError(
        f"tailscale not found on PATH or at {TAILSCALE_FALLBACK}. "
        "Is the Tailscale app installed?"
    )


def _make_handler(
    token: str,
    names: list[str],
    save: Callable[[dict[str, str]], None],
    target: str,
    done: threading.Event,
):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            """Silence the default access log; it would record the URL token."""

        def _authorized(self) -> bool:
            path = urlparse(self.path).path.strip("/")
            return secrets.compare_digest(path, token)

        def do_GET(self) -> None:
            if not self._authorized():
                self.send_error(404)
                return
            fields = "".join(
                f'<label for="{html.escape(n)}">{html.escape(n)}</label>'
                f'<input id="{html.escape(n)}" name="{html.escape(n)}" '
                f'type="password" autocomplete="off" autocapitalize="off" '
                f'autocorrect="off" spellcheck="false" required>'
                for n in names
            )
            self._respond(200, PAGE.format(fields=fields, target=html.escape(target)))

        def do_POST(self) -> None:
            if not self._authorized():
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)
            values = {n: form.get(n, [""])[0] for n in names}
            blank = [n for n, v in values.items() if not v]
            if blank:
                self._respond(400, f"<p>Blank: {html.escape(', '.join(blank))}. Go back.</p>")
                return
            try:
                save(values)
            except (ValueError, AvSaveError) as exc:
                # upsert_env_vars raises on unsafe values (e.g. "${" which
                # python-dotenv would interpolate, or literal newlines) or an
                # invalid key; save_to_av raises when av exits nonzero (denied
                # Approval, locked Keychain). Render the message, but never the
                # submitted value, so the person on their phone knows what to
                # fix without a stack trace or their password on screen.
                self._respond(
                    400,
                    f"<h1>Could not save</h1><p>{html.escape(str(exc))}</p>"
                    f"<p>Go back and try again.</p>",
                )
                return
            self._respond(200, "<h1>Saved.</h1><p>You can close this tab.</p>")
            done.set()

        def _respond(self, status: int, body: str) -> None:
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve a one-shot form over the tailnet to save secrets to .env or Automic Vault"
    )
    parser.add_argument("names", nargs="+", metavar="VAR", help="Env var names to prompt for")
    parser.add_argument(
        "--sink", choices=["env", "av"], default="env", help="Where values go (default: env)"
    )
    parser.add_argument("--env-file", default=".env", type=Path, help="Target env file (env sink)")
    parser.add_argument(
        "--project-directory",
        type=Path,
        help="av Project Value directory (av sink; default: main checkout root)",
    )
    parser.add_argument(
        "--timeout", type=int, default=IDLE_TIMEOUT_SECONDS, help="Give up after N seconds"
    )
    args = parser.parse_args()

    for name in args.names:
        if not VALID_KEY.match(name):
            sys.exit(f"error: {name!r} is not a valid env var name")

    if args.sink == "av":
        if not shutil.which("av"):
            sys.exit("error: `av` not found on PATH. Is Automic Vault installed?")
        project_dir = args.project_directory or default_project_dir()
        save = lambda values: save_to_av(values, project_dir)
        target = f"Automic Vault ({project_dir})"
    else:
        save = lambda values: upsert_env_vars(args.env_file, values)
        target = str(args.env_file)

    tailscale = _tailscale_binary()
    try:
        hostname = subprocess.run(
            [tailscale, "status", "--json"], capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() if exc.stderr else str(exc)
        sys.exit(
            "error: `tailscale status` failed. Is Tailscale running and are you "
            f"logged in?\n{detail}"
        )

    try:
        dns_name = json.loads(hostname.stdout)["Self"]["DNSName"].rstrip(".")
    except (json.JSONDecodeError, KeyError) as exc:
        sys.exit(
            "error: could not read this node's tailnet hostname from "
            f"`tailscale status --json` ({exc}). Is Tailscale set up correctly?"
        )

    token = secrets.token_urlsafe(24)
    done = threading.Event()
    handler = _make_handler(token, args.names, save, target, done)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]

    # Start the accept loop before the try/finally below so that
    # server.shutdown() in finally is always guaranteed to return: shutdown()
    # blocks on an internal Event that only gets set once serve_forever() has
    # run and exited, so if the thread were never started, an early failure
    # (e.g. the tailscale serve call below raising) would hang the process
    # forever inside finally instead of tearing down cleanly.
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # The `tailscale serve --bg` call must be the first statement inside this
    # try block: everything from route creation onward must be guarded by the
    # matching finally, or an exception (e.g. a BrokenPipeError from print()
    # if stdout closes) could leave the tailnet route up with nothing behind
    # it after the process exits.
    try:
        subprocess.run(
            [tailscale, "serve", "--bg", f"--https={SERVE_PORT}", f"http://127.0.0.1:{port}"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        print(f"Open on your phone:\n\n  https://{dns_name}:{SERVE_PORT}/{token}\n", flush=True)
        print(f"Waiting up to {args.timeout}s for: {', '.join(args.names)}", flush=True)
        if args.sink == "av":
            print("Each key needs its own av Approval after you submit.", flush=True)

        if not done.wait(timeout=args.timeout):
            sys.exit("\nerror: timed out, nothing written")
    finally:
        # The `serve ... off` call below must run even if shutdown() or the
        # sleep is interrupted (e.g. a second Ctrl-C) -- otherwise the
        # tailnet route is left pointing at this process's ephemeral
        # 127.0.0.1 port. That port returns to the OS pool the moment the
        # process exits, so whatever unrelated service binds it next
        # inherits an unauthenticated tailnet-wide proxy to itself, since
        # the token that gated it died with this process. Nesting the
        # try/finally guarantees the route teardown runs regardless of what
        # happens in the drain.
        try:
            server.shutdown()
            # Give the "Saved." response time to reach the client before the
            # proxy route disappears out from under the connection.
            time.sleep(0.5)
        finally:
            subprocess.run(
                [tailscale, "serve", f"--https={SERVE_PORT}", "off"],
                check=False,
                stdout=subprocess.DEVNULL,
            )

    for name in args.names:
        print(f"  {name} written", flush=True)
    print(f"Wrote {len(args.names)} value(s) to {target}", flush=True)


if __name__ == "__main__":
    main()
