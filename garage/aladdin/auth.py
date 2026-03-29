import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

import aiohttp

# AWS Cognito auth (from homebridge-aladdin-connect, reverse-engineered from Genie iOS app)
COGNITO_ENDPOINT = "https://cognito-idp.us-east-2.amazonaws.com/"
COGNITO_CLIENT_ID = "27iic8c3bvslqngl3hso83t74b"
COGNITO_CLIENT_SECRET = "7bokto0ep96055k42fnrmuth84k7jdcjablestb7j53o8lp63v5"

# API base URL
API_URL = "https://api.smartgarage.systems"


def _default_token_path() -> Path:
    env_path = os.environ.get("ALADDIN_TOKEN_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "state" / "picklehome" / "aladdin-tokens.json"


DEFAULT_TOKEN_PATH = _default_token_path()


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


def get_credentials() -> tuple[str, str]:
    email = os.environ.get("ALADDIN_EMAIL")
    password = os.environ.get("ALADDIN_PASSWORD")
    missing = []
    if not email:
        missing.append("ALADDIN_EMAIL")
    if not password:
        missing.append("ALADDIN_PASSWORD")
    if missing:
        print(f"{', '.join(missing)} not set. Run 'just dotenv' to generate .env.")
        sys.exit(1)
    return email, password


def _compute_secret_hash(username: str) -> str:
    msg = (username + COGNITO_CLIENT_ID).encode("utf-8")
    key = COGNITO_CLIENT_SECRET.encode("utf-8")
    return base64.b64encode(hmac.new(key, msg, hashlib.sha256).digest()).decode("utf-8")


async def login(email: str, password: str, token_path: Path = DEFAULT_TOKEN_PATH) -> dict:
    """Authenticate with AWS Cognito and save tokens."""
    secret_hash = _compute_secret_hash(email)
    payload = {
        "ClientId": COGNITO_CLIENT_ID,
        "AuthFlow": "USER_PASSWORD_AUTH",
        "AuthParameters": {
            "USERNAME": email,
            "PASSWORD": password,
            "SECRET_HASH": secret_hash,
        },
    }
    headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
    }
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.post(COGNITO_ENDPOINT, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Aladdin login failed (HTTP {resp.status}): {body}")
            data = await resp.json(content_type=None)
    result = data["AuthenticationResult"]
    save_tokens(result["AccessToken"], result.get("RefreshToken", ""), token_path)
    return result


async def refresh(refresh_token: str, email: str, token_path: Path = DEFAULT_TOKEN_PATH) -> dict:
    """Refresh access token via Cognito."""
    secret_hash = _compute_secret_hash(email)
    payload = {
        "ClientId": COGNITO_CLIENT_ID,
        "AuthFlow": "REFRESH_TOKEN_AUTH",
        "AuthParameters": {
            "REFRESH_TOKEN": refresh_token,
            "SECRET_HASH": secret_hash,
        },
    }
    headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
    }
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.post(COGNITO_ENDPOINT, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Aladdin token refresh failed (HTTP {resp.status}): {body}")
            data = await resp.json(content_type=None)
    result = data["AuthenticationResult"]
    # Cognito refresh doesn't return a new refresh token
    save_tokens(result["AccessToken"], refresh_token, token_path)
    return result
