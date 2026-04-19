import sqlite3
conn = sqlite3.connect('database/bot_data.db')
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('Tables:', [t[0] for t in tables])

# Check if settings table exists
for t in tables:
    if t[0] == 'settings':
        rows = conn.execute("SELECT * FROM settings").fetchall()
        print(f"\nSettings table has {len(rows)} rows:")
        for r in rows:
            print(f"  {r}")
        break
else:
    print("\nNo 'settings' table found in DB!")

conn.close()
