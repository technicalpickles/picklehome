import sys
import time

import keyring
from pyecobee import Ecobee

KEYCHAIN_SERVICE = "picklehome-ecobee"
# Standard Ecobee PIN auth values (not exposed by library after request_pin())
PIN_EXPIRY_SECONDS = 9 * 60   # 9 minutes
PIN_POLL_INTERVAL = 30        # seconds between request_tokens() calls


class KeychainEcobee(Ecobee):
    # The parent Ecobee class calls _write_config() after every token refresh.
    # We override it to persist tokens to Keychain instead of a JSON file,
    # so any API call that triggers a refresh automatically saves new tokens.
    def _write_config(self) -> None:
        if self.access_token:
            keyring.set_password(KEYCHAIN_SERVICE, "access_token", self.access_token)
        if self.refresh_token:
            keyring.set_password(KEYCHAIN_SERVICE, "refresh_token", self.refresh_token)


def get_credential(key: str) -> str | None:
    return keyring.get_password(KEYCHAIN_SERVICE, key)


def save_credential(key: str, value: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, key, value)


def require_credential(key: str, missing_message: str) -> str:
    value = get_credential(key)
    if value is None:
        print(missing_message)
        sys.exit(1)
    return value


def get_api_key() -> str:
    return require_credential("api_key", "Ecobee API key not found. See docs/climate-setup.md.")



def make_ecobee() -> KeychainEcobee:
    api_key = get_api_key()
    refresh_token = get_credential("refresh_token")
    if not refresh_token:
        print("Ecobee tokens not found. Run 'just climate-auth' to authorize.")
        sys.exit(1)
    access_token = get_credential("access_token")
    return KeychainEcobee(config={
        "API_KEY": api_key,
        "ACCESS_TOKEN": access_token or "",
        "REFRESH_TOKEN": refresh_token,
    })


def _print_thermostat_info(ecobee: KeychainEcobee) -> None:
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


def pin_auth_flow(api_key: str) -> None:
    ecobee = KeychainEcobee(config={"API_KEY": api_key})
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
    print("\nSetup complete! Tokens saved to Keychain. Add thermostat IDs to schedule.yaml.")
