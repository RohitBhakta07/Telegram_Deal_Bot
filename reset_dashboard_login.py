"""Safely reset the local dashboard login without using the Python REPL."""
import getpass
import sqlite3

from database import db_manager


def main():
    db_manager.init_db()
    current_username = db_manager.get_admin_username()
    print(f"Current login ID: {current_username}")

    new_username = input("New login ID: ").strip()
    if (not new_username or len(new_username) > 254
            or any(ord(char) < 32 for char in new_username)):
        print("Error: enter a valid login ID of at most 254 characters.")
        return 1

    password = getpass.getpass("New password (minimum 12 characters, letter + number): ")
    confirmation = getpass.getpass("Confirm new password: ")
    valid, validation_message = db_manager.validate_admin_password(password)
    if not valid:
        print(f"Error: {validation_message}")
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
