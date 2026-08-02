import os
import sys

import aiohttp

API_BASE_URL_TEMPLATE = "https://api-{region}.vicohome.io"


def get_credentials() -> tuple[str, str, str]:
    email = os.environ.get("VICOHOME_EMAIL")
    password = os.environ.get("VICOHOME_PASSWORD")
    region = os.environ.get("VICOHOME_REGION", "us")

    missing = []
    if not email:
        missing.append("VICOHOME_EMAIL")
    if not password:
        missing.append("VICOHOME_PASSWORD")
    if missing:
        print(f"{', '.join(missing)} not set. Run 'just dotenv' to generate .env.")
        sys.exit(1)

    return email, password, region


async def login(session: aiohttp.ClientSession, email: str, password: str) -> str:
    """Authenticate against /account/login and return the bearer token."""
    payload = {"email": email, "password": password, "loginType": 0}
    async with session.post("/account/login", json=payload) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    if data.get("result") != 0:
        raise RuntimeError(f"VicoHome login failed: {data.get('msg', 'unknown error')}")
    return data["data"]["token"]["token"]
