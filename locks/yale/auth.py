import os
import sys
from dataclasses import replace
from pathlib import Path

import aiohttp
from yalexs.api_async import ApiAsync
from yalexs.api_common import BRAND_CONFIG, _get_brand_config
from yalexs.authenticator_async import AuthenticatorAsync
from yalexs.authenticator_common import AuthenticationState, ValidationResult
from yalexs.const import Brand, HEADER_VALUE_API_KEY_OLD

# The newer API key in yalexs (d9984f29...) was rotated by August as of 2026-04
# and now returns 403 "API key is not valid". The old key (7cab4bbd...) still
# works and is still defined in the library as HEADER_VALUE_API_KEY_OLD.
# Patch the brand config before any ApiAsync is created.
BRAND_CONFIG[Brand.AUGUST] = replace(
    BRAND_CONFIG[Brand.AUGUST],
    api_key=HEADER_VALUE_API_KEY_OLD,
)
_get_brand_config.cache_clear()

# Yale Access uses the August cloud backend (same API, same base URL).
YALE_BRAND = Brand.AUGUST


def _default_token_path() -> Path:
    env_path = os.environ.get("YALE_TOKEN_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "state" / "picklehome" / "yale-tokens.json"


DEFAULT_TOKEN_PATH = _default_token_path()


def get_credentials() -> tuple[str, str]:
    email = os.environ.get("YALE_EMAIL")
    password = os.environ.get("YALE_PASSWORD")
    missing = []
    if not email:
        missing.append("YALE_EMAIL")
    if not password:
        missing.append("YALE_PASSWORD")
    if missing:
        print(f"{', '.join(missing)} not set. Run 'just dotenv' to generate .env.")
        sys.exit(1)
    return email, password


def load_access_token(token_path: Path = DEFAULT_TOKEN_PATH) -> str | None:
    """Load the cached access token, or None if not present."""
    if not token_path.exists():
        return None
    import json
    with open(token_path) as f:
        data = json.load(f)
    return data.get("access_token")


async def login(email: str, password: str, token_path: Path = DEFAULT_TOKEN_PATH) -> str:
    """Authenticate with Yale Access and cache the token.

    The August/Yale auth flow requires a verification code sent to your email on
    first login. This prompts for it interactively when needed.

    Returns the access token.
    """
    token_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession(trust_env=True) as session:
        api = ApiAsync(session, brand=YALE_BRAND)
        authenticator = AuthenticatorAsync(
            api,
            login_method="email",
            username=email,
            password=password,
            access_token_cache_file=str(token_path),
        )

        await authenticator.async_setup_authentication()
        auth = await authenticator.async_authenticate()

        if auth.state == AuthenticationState.BAD_PASSWORD:
            raise RuntimeError("Bad username or password.")

        if auth.state == AuthenticationState.REQUIRES_VALIDATION:
            print("Sending verification code to your email...")
            await authenticator.async_send_verification_code()
            code = input("Enter the verification code from your email: ").strip()
            result = await authenticator.async_validate_verification_code(code)
            if result != ValidationResult.VALIDATED:
                raise RuntimeError("Invalid verification code.")
            # Re-authenticate to get a fully authenticated token
            auth = await authenticator.async_authenticate()

        if auth.state != AuthenticationState.AUTHENTICATED:
            raise RuntimeError(f"Authentication failed with state: {auth.state}")

        return auth.access_token
