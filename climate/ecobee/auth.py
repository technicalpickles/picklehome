import json
import os
import sys
import time
from pathlib import Path

from pyecobee import Ecobee

DEFAULT_TOKEN_PATH = Path.home() / ".local" / "state" / "picklehome" / "ecobee-tokens.json"

# Standard Ecobee PIN auth values (not exposed by library after request_pin())
PIN_EXPIRY_SECONDS = 9 * 60   # 9 minutes
PIN_POLL_INTERVAL = 30        # seconds between request_tokens() calls


def get_api_key() -> str:
    api_key = os.environ.get("ECOBEE_API_KEY")
    if not api_key:
        print("ECOBEE_API_KEY not set. Run 'just dotenv' to generate .env.")
        sys.exit(1)
    return api_key


def load_tokens(token_path: Path = DEFAULT_TOKEN_PATH) -> dict | None:
    if not token_path.exists():
        return None
    with open(token_path) as f:
        return json.load(f)


def save_tokens(access_token: str, refresh_token: str, token_path: Path = DEFAULT_TOKEN_PATH) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"access_token": access_token, "refresh_token": refresh_token}
    with open(token_path, "w") as f:
        json.dump(data, f, indent=2)
    token_path.chmod(0o600)


class FileTokenEcobee(Ecobee):
    """Ecobee subclass that persists refreshed tokens to a local JSON file.

    The parent class calls _write_config() after every token refresh.
    """

    def __init__(self, config: dict, token_path: Path = DEFAULT_TOKEN_PATH):
        super().__init__(config=config)
        self._token_path = token_path

    def _write_config(self) -> None:
        if self.access_token and self.refresh_token:
            save_tokens(self.access_token, self.refresh_token, self._token_path)


def make_ecobee(token_path: Path = DEFAULT_TOKEN_PATH) -> FileTokenEcobee:
    api_key = get_api_key()
    tokens = load_tokens(token_path)
    if not tokens or not tokens.get("refresh_token"):
        print("Ecobee tokens not found. Run 'just climate-auth' to authorize.")
        sys.exit(1)
    return FileTokenEcobee(
        config={
            "API_KEY": api_key,
            "ACCESS_TOKEN": tokens.get("access_token", ""),
            "REFRESH_TOKEN": tokens["refresh_token"],
        },
        token_path=token_path,
    )


def _print_thermostat_info(ecobee: FileTokenEcobee) -> None:
    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        print("Failed to fetch thermostat list from Ecobee.")
        sys.exit(2)

    print("\nThermostats on this account (add these to schedule.yaml):")
    for thermostat in ecobee.thermostats:
        identifier = thermostat["identifier"]
        name = thermostat["name"]
        climates = thermostat.get("program", {}).get("climates", [])
        print(f"\n  {name}")
        print(f"    thermostat_id: \"{identifier}\"")
        print(f"    Available climates: {', '.join(c['climateRef'] for c in climates)}")


def list_thermostats() -> None:
    ecobee = make_ecobee()
    _print_thermostat_info(ecobee)


def pin_auth_flow(api_key: str, token_path: Path = DEFAULT_TOKEN_PATH) -> None:
    ecobee = FileTokenEcobee(config={"API_KEY": api_key}, token_path=token_path)
    result = ecobee.request_pin()
    if result is False:
        print("Failed to get PIN from Ecobee. Check your API key and network connection.")
        sys.exit(1)

    print(f"""Authorization required!
  PIN: {ecobee.pin}
  1. Go to https://www.ecobee.com → My Apps → Add Application
  2. Enter PIN above. You have approximately 9 minutes.

Waiting for authorization (Ctrl-C to cancel)...""")

    deadline = time.time() + PIN_EXPIRY_SECONDS
    try:
        while True:
            time.sleep(PIN_POLL_INTERVAL)
            result = ecobee.request_tokens()
            if result is True:
                break
            print(".", end="", flush=True)
            if time.time() >= deadline:
                print("\nTimed out waiting for authorization. Re-run 'just climate-auth'.")
                sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled. Re-run 'just climate-auth'.")
        sys.exit(0)

    _print_thermostat_info(ecobee)
    print(f"\nSetup complete! Tokens saved to {token_path}")
