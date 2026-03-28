import json
import os
from pathlib import Path


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
