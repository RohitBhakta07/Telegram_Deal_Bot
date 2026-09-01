"""Load private runtime configuration from an OS-local path outside the repo."""

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
LEGACY_ENV_PATH = BASE_DIR / ".env"


def private_env_path():
    override = os.environ.get("DEAL_HUNTER_ENV_FILE")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "DealHunterBot" / ".env"
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_root / "deal-hunter-bot" / ".env"


def private_data_dir():
    """Directory for credential-equivalent runtime state such as sessions."""
    return private_env_path().parent


def load_runtime_env():
    """Load the OS-local file first, retaining repo .env only as a fallback."""
    private_path = private_env_path()
    load_dotenv(private_path, override=False)
    load_dotenv(LEGACY_ENV_PATH, override=False)
    return private_path
