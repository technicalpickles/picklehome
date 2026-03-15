import sys
import time

import keyring
from pyecobee import Ecobee

KEYCHAIN_SERVICE = "picklehome-ecobee"
# Standard Ecobee PIN auth values (not exposed by library after request_pin())
PIN_EXPIRY_SECONDS = 9 * 60   # 9 minutes
PIN_POLL_INTERVAL = 30        # seconds between request_tokens() calls


class KeychainEcobee(Ecobee):
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
    return require_credential("api_key", "Ecobee API key not found. See docs/ecobee-setup.md.")


def get_thermostat_id() -> str:
    return require_credential("thermostat_id", "Thermostat ID not found. Run 'just ecobee-auth' first.")


def make_ecobee() -> KeychainEcobee:
    api_key = get_api_key()
    refresh_token = get_credential("refresh_token")
    if not refresh_token:
        print("Ecobee tokens not found. Run 'just ecobee-auth' to authorize.")
        sys.exit(1)
    access_token = get_credential("access_token")
    return KeychainEcobee(config={
        "API_KEY": api_key,
        "ACCESS_TOKEN": access_token or "",
        "REFRESH_TOKEN": refresh_token,
    })


def _discover_and_save_thermostat(ecobee: KeychainEcobee) -> str:
    success = ecobee.get_thermostats()
    if not success or not ecobee.thermostats:
        print("Failed to fetch thermostat list from Ecobee.")
        sys.exit(2)

    thermostats = ecobee.thermostats
    if len(thermostats) == 1:
        index = 0
    else:
        for i, t in enumerate(thermostats, 1):
            print(f"  {i}. {t['name']} (ID: {t['identifier']})")
        while True:
            try:
                choice = int(input("Select [1-{}]: ".format(len(thermostats))))
                if 1 <= choice <= len(thermostats):
                    index = choice - 1
                    break
                print("Invalid selection, try again.")
            except ValueError:
                print("Invalid selection, try again.")

    thermostat = thermostats[index]
    identifier = thermostat["identifier"]
    name = thermostat["name"]
    save_credential("thermostat_id", identifier)

    climates = thermostat.get("program", {}).get("climates", [])
    print(f"Thermostat: {name} (ID: {identifier})")
    print("Available climates (use these in schedule.yaml):")
    for climate in climates:
        print(f"  - {climate['climateRef']}")

    return identifier


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
                print("\nTimed out waiting for authorization. Re-run 'just ecobee-auth'.")
                sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled. Re-run 'just ecobee-auth'.")
        sys.exit(0)

    _discover_and_save_thermostat(ecobee)
    print("\nSetup complete! Tokens and thermostat saved to Keychain.")
