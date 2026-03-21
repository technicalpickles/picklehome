import sys

import keyring

KEYCHAIN_SERVICE = "picklehome-blueair"


def store_credentials(username: str, password: str, region: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, "username", username)
    keyring.set_password(KEYCHAIN_SERVICE, "password", password)
    keyring.set_password(KEYCHAIN_SERVICE, "region", region)


def get_credentials() -> tuple[str, str, str]:
    username = keyring.get_password(KEYCHAIN_SERVICE, "username")
    password = keyring.get_password(KEYCHAIN_SERVICE, "password")
    region = keyring.get_password(KEYCHAIN_SERVICE, "region")

    if username is None or password is None:
        print("BlueAir credentials not found. Run 'just blueair-auth' to set up.")
        sys.exit(1)

    if region is None:
        region = "us"

    return username, password, region
