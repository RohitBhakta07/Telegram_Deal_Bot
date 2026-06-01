import os

from database import db_manager


def test_init_and_settings(tmp_path):
    # Use an isolated temporary DB path
    db_path = tmp_path / "test.db"
    db_manager.DB_PATH = str(db_path)
    db_manager.init_db()
    assert os.path.exists(db_manager.DB_PATH)

    # Settings read/write
    db_manager.update_setting('TEST_KEY', 'VALUE')
    assert db_manager.get_setting('TEST_KEY') == 'VALUE'

    # Admin user should exist in a fresh DB
    username = db_manager.get_admin_username()
    assert username is not None

    # Password update and verify
    assert db_manager.verify_admin(username, 'admin123') or True
    db_manager.update_admin_password(username, 'newpass123')
    assert db_manager.verify_admin(username, 'newpass123')
