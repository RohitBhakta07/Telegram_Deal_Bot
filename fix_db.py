"""Fix the DB schema: add missing created_at column to channels table."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'bot_data.db')

conn = sqlite3.connect(DB_PATH)

# Check current schema
print("Current channels schema:")
for c in conn.execute("PRAGMA table_info(channels)").fetchall():
    print(f"  {c}")

# Add created_at if missing
try:
    conn.execute("ALTER TABLE channels ADD COLUMN created_at TEXT DEFAULT NULL")
    conn.commit()
    print("\n+ Added 'created_at' column to channels table")
except sqlite3.OperationalError as e:
    if "duplicate column" in str(e).lower():
        print("\n= 'created_at' column already exists")
    else:
        print(f"\nError: {e}")

# Verify
print("\nUpdated channels schema:")
for c in conn.execute("PRAGMA table_info(channels)").fetchall():
    print(f"  {c}")

conn.close()
print("\nDone!")
