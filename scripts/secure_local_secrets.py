"""Create local master keys and migrate SQLite credentials to encrypted storage."""

import os
import shutil
import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime_env import LEGACY_ENV_PATH, private_data_dir, private_env_path

ENV_PATH = private_env_path()


def _read_env_lines():
    source = ENV_PATH if ENV_PATH.exists() else LEGACY_ENV_PATH
    if not source.exists():
        return ["# Local secrets - never commit or cloud-sync this file"]
    return source.read_text(encoding="utf-8").splitlines()


def _get_value(lines, key):
    prefix = f"{key}="
    for line in reversed(lines):
        if line.strip().startswith(prefix):
            return line.strip()[len(prefix):].strip()
    return ""


def _upsert(lines, key, value):
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[index] = prefix + value
            return
    lines.append(prefix + value)


def _write_private_env(lines):
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = ENV_PATH.with_suffix(".env.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    os.replace(temporary, ENV_PATH)
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass


def _copy_legacy_session():
    target = private_data_dir() / "sessions" / "extrape.session"
    candidates = (
        ROOT / "userbot" / "extrape_session" / "extrape.session",
        ROOT / "userbot" / "extrape_session.session",
    )
    source = next((item for item in candidates if item.is_file()), None)
    if target.exists() or source is None:
        return source, target, False

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".session.tmp")
    shutil.copy2(source, temporary)
    if temporary.stat().st_size != source.stat().st_size:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Telethon session copy verification failed")
    os.replace(temporary, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return source, target, True


def main():
    lines = _read_env_lines()
    flask_key = _get_value(lines, "FLASK_SECRET_KEY") or secrets.token_hex(32)
    encryption_key = _get_value(lines, "ENCRYPTION_KEY") or secrets.token_hex(32)
    _upsert(lines, "FLASK_SECRET_KEY", flask_key)
    _upsert(lines, "ENCRYPTION_KEY", encryption_key)
    _write_private_env(lines)

    os.environ["FLASK_SECRET_KEY"] = flask_key
    os.environ["ENCRYPTION_KEY"] = encryption_key

    from database import db_manager
    from secret_store import migrate_plaintext_settings

    db_manager.init_db()
    migrated = migrate_plaintext_settings()
    session_source, session_target, session_copied = _copy_legacy_session()
    print(f"Local master keys are configured outside the repository: {ENV_PATH}")
    print(f"Encrypted database credentials migrated: {migrated}")
    print("Secret values were not printed. Restart the bot before using the dashboard.")
    if session_copied:
        print(f"Telethon session copied to private storage: {session_target}")
    elif session_target.exists():
        print(f"Private Telethon session is present: {session_target}")
    if session_source is not None:
        print("Legacy repository Telethon session detected; remove it after verification.")
    if LEGACY_ENV_PATH.exists():
        print("Legacy repository .env detected; remove it after verifying this migration.")


if __name__ == "__main__":
    main()
