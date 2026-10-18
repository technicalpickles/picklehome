"""Steer Woodpecker CI work to the laptop VM agent while it is online.

Stateless reconcile: each run reads the agent list, decides the desired
no_schedule/filters for the laptop and picklelab agents from the laptop's
last_contact, and PATCHes whatever differs. Runs from a systemd timer; see
homelab/services/woodpecker/README.md ("Agent switch").

Safety invariant: both agents are never unschedulable at once. The PATCH order
returned by decide() enforces it (enable the target before disabling the other).
Fail open: a missing, never-connected or stale laptop agent means picklelab is
schedulable and the laptop's filters are back at their default.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

_urlopen = urllib.request.urlopen
TIMEOUT = 10


@dataclass(frozen=True)
class Config:
    laptop_name: str
    picklelab_name: str
    stale_after: int = 300
    laptop_filters: dict = field(default_factory=lambda: {"!host": "laptop"})


@dataclass(frozen=True)
class Patch:
    agent_id: int
    # name, no_schedule and filters: PATCH replaces filters wholesale, so the
    # full desired values are always sent.
    body: dict


def _find(agents: list[dict], name: str) -> list[dict]:
    return [a for a in agents if a["name"] == name]


def _patch(a: dict, *, no_schedule: bool, filters: dict) -> Patch | None:
    if a["no_schedule"] == no_schedule and a["filters"] == filters:
        return None
    return Patch(
        a["id"], {"name": a["name"], "no_schedule": no_schedule, "filters": filters}
    )


def decide(agents: list[dict], now: int, cfg: Config) -> list[Patch]:
    """Patches to apply, in order, to reach the desired state. [] if converged."""
    pl = _find(agents, cfg.picklelab_name)
    if len(pl) != 1:
        raise ValueError(
            f"expected exactly one agent named {cfg.picklelab_name!r}, found {len(pl)}"
            f" (agents: {sorted(a['name'] for a in agents)})"
        )
    picklelab = pl[0]

    laptops = _find(agents, cfg.laptop_name)
    if len(laptops) > 1:
        raise ValueError(
            f"expected at most one agent named {cfg.laptop_name!r}, found {len(laptops)}"
        )
    laptop = laptops[0] if laptops else None

    laptop_up = (
        laptop is not None
        and not laptop["no_schedule"]  # drained by hand: it heartbeats but takes no work
        and laptop["last_contact"] > 0
        and now - laptop["last_contact"] <= cfg.stale_after
    )

    laptop_patch = None
    if laptop is not None:
        laptop_patch = _patch(
            laptop,
            no_schedule=laptop["no_schedule"],
            filters={} if laptop_up else dict(cfg.laptop_filters),
        )
    picklelab_patch = _patch(
        picklelab, no_schedule=laptop_up, filters=picklelab["filters"]
    )

    # Enable the target agent before disabling the other.
    ordered = (
        [laptop_patch, picklelab_patch] if laptop_up else [picklelab_patch, laptop_patch]
    )
    return [p for p in ordered if p is not None]


def _request(opener, method: str, url: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with opener(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} -> HTTP {e.code}: {detail}") from e
    except OSError as e:  # URLError, timeouts, connection refused
        raise RuntimeError(f"{method} {url} failed: {e}") from e


def list_agents(base_url: str, token: str, opener=_urlopen) -> list[dict]:
    return json.loads(_request(opener, "GET", f"{base_url}/api/agents", token))


def patch_agent(base_url: str, token: str, patch: Patch, opener=_urlopen) -> None:
    _request(opener, "PATCH", f"{base_url}/api/agents/{patch.agent_id}", token, patch.body)


def run(
    cfg: Config,
    base_url: str,
    token: str,
    *,
    dry_run: bool,
    reset: bool,
    now: int,
    opener=_urlopen,
) -> list[Patch]:
    agents = list_agents(base_url, token, opener)
    if reset:
        # Decide as if the laptop had never connected: defaults everywhere.
        agents = [
            {**a, "last_contact": 0} if a["name"] == cfg.laptop_name else a
            for a in agents
        ]
    patches = decide(agents, now, cfg)
    for p in patches:
        if dry_run:
            print(
                f"would PATCH {p.body['name']}: no_schedule={p.body['no_schedule']}"
                f" filters={p.body['filters']}"
            )
        else:
            patch_agent(base_url, token, p, opener)
            print(f"PATCHed {p.body['name']}: no_schedule={p.body['no_schedule']}"
                  f" filters={p.body['filters']}")
    return patches


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="log patches, send none")
    ap.add_argument("--reset", action="store_true", help="restore defaults now")
    args = ap.parse_args(argv)
    try:
        env = os.environ
        for name in ("WOODPECKER_API_TOKEN", "LAPTOP_AGENT_NAME", "PICKLELAB_AGENT_NAME"):
            if not env.get(name):
                raise RuntimeError(f"{name} is not set")
        cfg = Config(
            laptop_name=env["LAPTOP_AGENT_NAME"],
            picklelab_name=env["PICKLELAB_AGENT_NAME"],
            stale_after=int(env.get("STALE_AFTER_SECONDS", "300")),
        )
        run(
            cfg,
            env.get("WOODPECKER_URL", "http://127.0.0.1:8000").rstrip("/"),
            env["WOODPECKER_API_TOKEN"],
            dry_run=args.dry_run,
            reset=args.reset,
            now=int(time.time()),
            opener=_urlopen,
        )
    except (RuntimeError, ValueError) as e:
        print(f"agent-switch: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
