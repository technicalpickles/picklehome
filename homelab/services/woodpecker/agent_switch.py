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

from dataclasses import dataclass, field


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
