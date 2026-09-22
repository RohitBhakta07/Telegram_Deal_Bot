"""Regression checks for the local master-key setup used by dashboard saves."""

import os

import pytest

import runtime_env
from scripts import secure_local_secrets
from secret_store import encrypt_secret


def test_private_env_key_replaces_stale_process_key(tmp_path, monkeypatch):
    private_env = tmp_path / "private.env"
    key = "k" * 64
    private_env.write_text(f"ENCRYPTION_KEY={key}\n", encoding="utf-8")
    monkeypatch.setattr(runtime_env, "private_env_path", lambda: private_env)
    monkeypatch.setattr(runtime_env, "LEGACY_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setenv("ENCRYPTION_KEY", "short-old-key")

    runtime_env.load_runtime_env()

    assert os.environ["ENCRYPTION_KEY"] == key
    assert encrypt_secret("test-value").startswith("enc:v1:")


def test_private_env_loads_when_dotenv_autoload_is_disabled(tmp_path, monkeypatch):
    private_env = tmp_path / "private.env"
    private_env.write_text("ENCRYPTION_KEY=" + "k" * 64 + "\n", encoding="utf-8")
    monkeypatch.setattr(runtime_env, "private_env_path", lambda: private_env)
    monkeypatch.setattr(runtime_env, "LEGACY_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

    runtime_env.load_runtime_env()

    assert len(os.environ["ENCRYPTION_KEY"]) == 64


def test_config_does_not_continue_after_credential_decryption_error(monkeypatch):
    import config
    from secret_store import SecretConfigurationError

    def fail(_key):
        raise SecretConfigurationError("Invalid local master key")

    monkeypatch.setattr(config, "get_secret", fail)

    with pytest.raises(SystemExit, match="Invalid local master key"):
        config._load_secret("BOT_TOKEN")


def test_setup_generates_usable_keys_when_none_exist(tmp_path, monkeypatch):
    private_env = tmp_path / "private.env"
    monkeypatch.setattr(secure_local_secrets, "ENV_PATH", private_env)
    monkeypatch.setattr(secure_local_secrets, "LEGACY_ENV_PATH", tmp_path / "missing.env")
    monkeypatch.setattr(secure_local_secrets, "_copy_legacy_session",
                        lambda: (None, tmp_path / "missing.session", False))
    monkeypatch.setattr("database.db_manager.init_db", lambda: None)
    monkeypatch.setattr("secret_store.migrate_plaintext_settings", lambda: 0)

    secure_local_secrets.main()

    saved = dict(line.split("=", 1) for line in private_env.read_text(encoding="utf-8").splitlines()
                 if "=" in line)
    assert len(saved["FLASK_SECRET_KEY"]) >= 32
    assert len(saved["ENCRYPTION_KEY"]) >= 32
    assert encrypt_secret("test-value").startswith("enc:v1:")
