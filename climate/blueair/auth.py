import os
import sys


def store_credentials(username: str, password: str, region: str) -> None:
    """Store credentials hint. With env-var auth, credentials live in 1Password/.env."""
    print("BlueAir credentials are managed via 1Password and .env.template.")
    print("Update the BlueAir item in 1Password, then run 'just dotenv'.")


def get_credentials() -> tuple[str, str, str]:
    username = os.environ.get("BLUEAIR_USERNAME")
    password = os.environ.get("BLUEAIR_PASSWORD")
    region = os.environ.get("BLUEAIR_REGION", "us")

    if not username or not password:
        print("BLUEAIR_USERNAME/BLUEAIR_PASSWORD not set. Run 'just dotenv' to generate .env.")
        sys.exit(1)

    return username, password, region
