"""Read-only fetches against the Moen Flo API.

Read-only by design. aioflo also exposes open_valve/close_valve and the
home/away/sleep system-mode setters; none are called here and none should be
added without a deliberate decision. This valve is the house water supply.

aioflo collapses every failure into a single RequestError with no vendor error
code (unlike thinqconnect, which lg/thinq/client.py can classify on). The only
honest signal available is *when* the failure happened: during authentication,
or after it. connect() raising means the credentials or the auth flow are wrong;
anything later is an ordinary request failure.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from aioflo.api import API
from aioflo.errors import FloError as AioFloError

from water.flo.auth import ONEPASSWORD_ITEM, connect, use_sso


class MoenFloError(RuntimeError):
    """A Flo API call failed."""


class MoenFloAuthError(MoenFloError):
    """Flo rejected the credentials, or the wrong auth flow was used."""


@asynccontextmanager
async def with_api():
    """Yield an authenticated API, closing the session on the way out.

    Classifies an authentication-time failure as MoenFloAuthError, naming both
    plausible causes -- because with a single untyped RequestError there is no
    way to tell a bad password from the wrong auth flow, and the FLO_USE_SSO
    toggle is the first thing to try.
    """
    try:
        api, session = await connect()
    except AioFloError as err:
        flow = "SSO (Cognito)" if use_sso() else "legacy users/auth"
        other = "0" if use_sso() else "1"
        raise MoenFloAuthError(
            f"Flo rejected authentication via the {flow} flow. Either the password is "
            f"wrong, or this account needs the other flow -- try FLO_USE_SSO={other}. "
            f"Credentials come from {ONEPASSWORD_ITEM} (or 'just secret-entry')."
        ) from err

    try:
        yield api
    finally:
        await session.close()


async def fetch_raw(api: API) -> dict:
    """Return the unmassaged user, location, and device payloads.

    Three calls because each layer holds different things: the user record names
    the locations, the location record carries system mode (home/away/sleep) and
    the device ids, and only the per-device record has live telemetry.
    """
    try:
        user = await api.user.get_info(include_location_info=True)
        locations, devices = [], []
        for location_stub in user.get("locations", []):
            location = await api.location.get_info(
                location_stub["id"], include_device_info=True
            )
            locations.append(location)
            for device_stub in location.get("devices", []):
                devices.append(await api.device.get_info(device_stub["id"]))
    except AioFloError as err:
        raise MoenFloError(f"Flo API request failed: {err}") from err

    return {"user": user, "locations": locations, "devices": devices}


@dataclass(frozen=True)
class FloValve:
    """One Flo shutoff valve, flattened from its device payload.

    Every telemetry field is optional. The Flo reports telemetry only while it
    has a recent reading; absent is meaningfully different from zero, and 0.0 gpm
    ("no water moving") must not be confused with "no reading" (see root
    CLAUDE.md, Coding Conventions).

    Mode comes from the device's own `systemMode.lastKnown`, not the location's
    `systemMode` -- the location payload carries only a `target`, no observed
    value, so the device is the only source with an actual last-known mode.

    `telemetry_updated` is the timestamp the *current* telemetry reading was
    taken, not when this object was built. On this account it has been seen
    over five hours stale while `gpm`/`psi`/`temp_f` still read out normally --
    rendering those numbers without this timestamp presents stale data as live.
    """

    name: str
    state: str          # "open" | "closed" | "unknown"
    mode: str | None    # home | away | sleep
    gpm: float | None
    psi: float | None
    temp_f: float | None
    telemetry_updated: str | None
    rssi: int | None
    connected: bool | None
    pending_alerts: int | None


def _dig(node: dict, *keys, default=None):
    """Walk nested dict keys, returning default the moment one is missing."""
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def parse_valve(device: dict) -> FloValve:
    """Flatten a device payload into a FloValve.

    Takes only the device, not the location: mode comes from the device's own
    `systemMode.lastKnown`, which the location payload doesn't have (see
    FloValve's docstring).
    """
    pending = _dig(device, "notifications", "pending", default={})
    alert_count = None
    if isinstance(pending, dict):
        # alarmCount is a list on this account, not an int like the other
        # *Count fields (infoCount, warningCount, criticalCount) -- the
        # isinstance guard is load-bearing, not defensive boilerplate.
        alert_count = sum(
            v for k, v in pending.items() if k.endswith("Count") and isinstance(v, int)
        )

    return FloValve(
        name=_dig(device, "nickname", default="Flo"),
        state=_dig(device, "valve", "lastKnown", default="unknown"),
        mode=_dig(device, "systemMode", "lastKnown"),
        gpm=_dig(device, "telemetry", "current", "gpm"),
        psi=_dig(device, "telemetry", "current", "psi"),
        temp_f=_dig(device, "telemetry", "current", "tempF"),
        telemetry_updated=_dig(device, "telemetry", "current", "updated"),
        rssi=_dig(device, "connectivity", "rssi"),
        connected=_dig(device, "isConnected"),
        pending_alerts=alert_count,
    )
