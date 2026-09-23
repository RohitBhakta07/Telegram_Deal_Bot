"""Load private runtime configuration from an OS-local path outside the repo."""

import os
from pathlib import Path

from dotenv import dotenv_values


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


def master_secret(name):
    """Read a local master key even if the process environment was not populated."""
    if name not in {"ENCRYPTION_KEY", "FLASK_SECRET_KEY"}:
        raise ValueError("Unsupported master secret")
    private_value = dotenv_values(private_env_path()).get(name)
    if private_value is not None:
        return private_value.strip()
    process_value = os.environ.get(name)
    if process_value is not None:
        return process_value.strip()
    return (dotenv_values(LEGACY_ENV_PATH).get(name) or "").strip()


def load_runtime_env():
    """Use the private file as the local source of truth, with repo .env as fallback."""
    private_path = private_env_path()
    for key, value in dotenv_values(private_path).items():
        if value is not None:
            os.environ[key] = value
    for key, value in dotenv_values(LEGACY_ENV_PATH).items():
        if value is not None and key not in os.environ:
            os.environ[key] = value
    return private_path
