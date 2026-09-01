import pytest

from database import db_manager
from secret_store import (
    ENCRYPTED_PREFIX,
    SecretConfigurationError,
    get_secret,
    migrate_plaintext_settings,
    set_secret,
)


@pytest.fixture
def secret_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, "DB_PATH", str(tmp_path / "secrets.db"))
    monkeypatch.setenv("ENCRYPTION_KEY", "a" * 64)
    db_manager.init_db()
    return tmp_path / "secrets.db"


def test_secret_round_trip_never_stores_plaintext(secret_db):
    set_secret("BOT_TOKEN", "123456:test-secret-token")
    stored = db_manager.get_setting("BOT_TOKEN")
    assert stored.startswith(ENCRYPTED_PREFIX)
    assert "test-secret-token" not in stored
    assert get_secret("BOT_TOKEN") == "123456:test-secret-token"


def test_plaintext_settings_migrate_in_one_pass(secret_db):
    db_manager.update_setting("API_HASH", "legacy-plaintext")
    assert migrate_plaintext_settings() == 1
    assert db_manager.get_setting("API_HASH").startswith(ENCRYPTED_PREFIX)
    assert get_secret("API_HASH") == "legacy-plaintext"


def test_plaintext_read_fails_closed_without_master_key(secret_db, monkeypatch):
    db_manager.update_setting("API_ID", "12345")
    monkeypatch.delenv("ENCRYPTION_KEY")
    with pytest.raises(SecretConfigurationError):
        get_secret("API_ID")
