"""Safely reset the local dashboard login without using the Python REPL."""
import getpass
import sqlite3

from database import db_manager


def main():
    db_manager.init_db()
    current_username = db_manager.get_admin_username()
    print(f"Current login ID: {current_username}")

    new_username = input("New login ID: ").strip()
    if not new_username:
        print("Error: login ID cannot be empty.")
        return 1

    password = getpass.getpass("New password (minimum 6 characters): ")
    confirmation = getpass.getpass("Confirm new password: ")
    if len(password) < 6:
        print("Error: password must contain at least 6 characters.")
        return 1
    if password != confirmation:
        print("Error: passwords do not match.")
        return 1

    password_hash = db_manager._hash_password(password)
    with sqlite3.connect(db_manager.DB_PATH) as connection:
        connection.execute(
            "UPDATE admin_users SET username=?, password_hash=? WHERE username=?",
            (new_username, password_hash, current_username),
        )
        if connection.total_changes != 1:
            raise RuntimeError("Admin account was not updated")

    print("Dashboard login reset successfully.")
    print(f"Login ID: {new_username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
