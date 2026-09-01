"""Encrypted storage helpers for runtime credentials kept in SQLite."""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


ENCRYPTED_PREFIX = "enc:v1:"
SENSITIVE_SETTING_KEYS = frozenset({
    "API_ID",
    "API_HASH",
    "BOT_TOKEN",
    "EXTRAPE_AFFID",
    "EXTRAPE_PARAM1",
})


class SecretConfigurationError(RuntimeError):
    """Raised when credentials cannot be stored or decrypted safely."""


def _raw_encryption_key():
    value = os.environ.get("ENCRYPTION_KEY", "").strip()
    if len(value) < 32:
        raise SecretConfigurationError(
            "ENCRYPTION_KEY is missing or shorter than 32 characters. "
            "Run: python scripts/secure_local_secrets.py"
        )
    return value


def _cipher():
    digest = hashlib.sha256(_raw_encryption_key().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _legacy_cipher():
    raw = _raw_encryption_key().encode("utf-8")[:32].ljust(32, b"0")
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(value):
    """Encrypt a non-empty value using the configured local master key."""
    if value is None or str(value) == "":
        return ""
    token = _cipher().encrypt(str(value).encode("utf-8")).decode("ascii")
    return ENCRYPTED_PREFIX + token


def decrypt_secret(value):
    """Decrypt current and pre-v1 Fernet values; reject invalid ciphertext."""
    stored = str(value or "")
    if not stored:
        return ""
    try:
        if stored.startswith(ENCRYPTED_PREFIX):
            token = stored[len(ENCRYPTED_PREFIX):]
            return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
        if stored.startswith("gAAAA"):
            return _legacy_cipher().decrypt(stored.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise SecretConfigurationError(
            "A stored credential cannot be decrypted with ENCRYPTION_KEY."
        ) from exc
    raise SecretConfigurationError("Credential is not encrypted.")


def set_secret(key, value):
    """Encrypt and persist one approved credential; plaintext is never stored."""
    if key not in SENSITIVE_SETTING_KEYS:
        raise ValueError(f"Unsupported sensitive setting: {key}")
    from database import db_manager

    db_manager.update_setting(key, encrypt_secret(value))


def get_secret(key, default=""):
    """Read env override or decrypt DB value, migrating legacy/plaintext values."""
    if key not in SENSITIVE_SETTING_KEYS:
        raise ValueError(f"Unsupported sensitive setting: {key}")

    env_value = os.environ.get(key)
    if env_value:
        return env_value

    from database import db_manager

    stored = db_manager.get_setting(key, "")
    if not stored:
        return default
    if stored.startswith(ENCRYPTED_PREFIX):
        return decrypt_secret(stored)

    # A configured master key authorizes a one-time migration of old values.
    if stored.startswith("gAAAA"):
        plaintext = decrypt_secret(stored)
    else:
        _raw_encryption_key()  # Fail closed instead of consuming DB plaintext.
        plaintext = stored
    set_secret(key, plaintext)
    return plaintext


def secret_is_configured(key):
    """Return configuration status without returning the credential itself."""
    if os.environ.get(key):
        return True
    from database import db_manager

    return bool(db_manager.get_setting(key, ""))


def migrate_plaintext_settings():
    """Migrate every existing sensitive DB value in one transaction."""
    _raw_encryption_key()
    from database import db_manager

    conn = db_manager._get_connection()
    try:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in SENSITIVE_SETTING_KEYS)
        cursor.execute(
            f"SELECT key, value FROM settings WHERE key IN ({placeholders})",
            tuple(SENSITIVE_SETTING_KEYS),
        )
        migrated = 0
        for key, stored in cursor.fetchall():
            if not stored:
                continue
            if stored.startswith(ENCRYPTED_PREFIX):
                decrypt_secret(stored)  # Verify the configured master key.
                continue
            plaintext = decrypt_secret(stored) if stored.startswith("gAAAA") else stored
            cursor.execute(
                "UPDATE settings SET value=? WHERE key=?",
                (encrypt_secret(plaintext), key),
            )
            migrated += 1
        conn.commit()
        return migrated
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
