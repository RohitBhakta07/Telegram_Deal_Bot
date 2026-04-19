"""
database/db_manager.py
======================
Multi-Tenant Deal Hunter Bot — Database Manager

WHO DOES WHAT:
  Super Admin   → creates channels, creates channel-admin accounts, sees everything
  Channel Admin → manages only their own categories & flash_keywords
  Bot (main.py) → reads per-channel data → sends deals (existing logic untouched)

SECURITY:
  - bcrypt password hashing (salted, not plain sha256)
  - No raw SQL string formatting anywhere (100% parameterized)
  - WAL mode for safe concurrent reads between bot + dashboard
"""

import sqlite3
import os
import secrets
from datetime import datetime

import bcrypt

# ─── PATH ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'bot_data.db')


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row           # access columns by name
    conn.execute("PRAGMA journal_mode=WAL")  # safe concurrent access
    conn.execute("PRAGMA foreign_keys=ON")   # enforce FK constraints
    return conn


# ═══════════════════════════════════════════════════════════════════════════
# 1.  INIT — run once on startup, safe to re-run (idempotent)
# ═══════════════════════════════════════════════════════════════════════════
def init_db():
    conn = get_connection()
    c    = conn.cursor()

    # ── channels ────────────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id   TEXT PRIMARY KEY,
            channel_name TEXT NOT NULL,
            is_active    INTEGER NOT NULL DEFAULT 1,
            created_at   TEXT    DEFAULT (datetime('now'))
        )
    """)

    # ── channel_admins ──────────────────────────────────────────────────────
    # panel_slug  → unique URL key   /channel/<panel_slug>/dashboard
    # password_hash → bcrypt hash
    # session_token → rotates on every login (server-side session validation)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channel_admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id    TEXT    NOT NULL,
            username      TEXT    NOT NULL,
            password_hash TEXT    NOT NULL,
            panel_slug    TEXT    NOT NULL,
            session_token TEXT    DEFAULT NULL,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    DEFAULT (datetime('now')),
            last_login    TEXT    DEFAULT NULL,
            UNIQUE (username),
            UNIQUE (panel_slug),
            FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
        )
    """)

    # ── categories ──────────────────────────────────────────────────────────
    # channel_id = NULL  → super-admin global category (fallback for bot)
    # channel_id = TEXT  → belongs to that channel only
    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            keywords     TEXT    NOT NULL,
            min_discount INTEGER NOT NULL DEFAULT 40,
            channel_id   TEXT    DEFAULT NULL,
            created_at   TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
        )
    """)

    # ── flash_keywords ──────────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS flash_keywords (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword      TEXT    NOT NULL,
            min_discount INTEGER NOT NULL DEFAULT 60,
            channel_id   TEXT    DEFAULT NULL,
            created_at   TEXT    DEFAULT (datetime('now')),
            FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
        )
    """)

    # ── sent_deals ──────────────────────────────────────────────────────────
    # Per-channel dedup: same product can go to different channels
    c.execute("""
        CREATE TABLE IF NOT EXISTS sent_deals (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            title          TEXT,
            original_link  TEXT NOT NULL,
            affiliate_link TEXT,
            category       TEXT,
            channel_id     TEXT DEFAULT NULL,
            sent_at        TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── settings (legacy — config.py reads from here) ───────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
    """)

    # ── SAFE MIGRATIONS (add missing columns to old DBs) ────────────────────
    _safe_add_column(c, 'categories',    'channel_id',   'TEXT DEFAULT NULL')
    _safe_add_column(c, 'flash_keywords','channel_id',   'TEXT DEFAULT NULL')
    _safe_add_column(c, 'sent_deals',    'channel_id',   'TEXT DEFAULT NULL')
    _safe_add_column(c, 'channels',      'is_active',    'INTEGER NOT NULL DEFAULT 1')
    _safe_add_column(c, 'channels',      'created_at',   'TEXT DEFAULT NULL')
    _safe_add_column(c, 'channel_admins','session_token','TEXT DEFAULT NULL')
    _safe_add_column(c, 'channel_admins','is_active',    'INTEGER NOT NULL DEFAULT 1')
    _safe_add_column(c, 'channel_admins','last_login',   'TEXT DEFAULT NULL')

    conn.commit()
    conn.close()
    print("[OK] DB initialized / migrated.")


def _safe_add_column(cursor, table: str, column: str, col_def: str):
    """Add column only if it doesn't exist — prevents crash on re-run."""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError:
        pass  # column already exists



# ═══════════════════════════════════════════════════════════════════════════
# 1b. SETTINGS TABLE  (backward compat — config.py uses these)
# ═══════════════════════════════════════════════════════════════════════════
def get_setting(key: str) -> str | None:
    """Read a setting value from the settings table."""
    conn = get_connection()
    row  = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    return row['value'] if row else None


def save_setting(key: str, value: str):
    """Insert or update a setting."""
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value))
    )
    conn.commit()
    conn.close()


def get_all_settings() -> dict:
    """Return all settings as a dict."""
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}


# ═══════════════════════════════════════════════════════════════════════════
# 2.  PASSWORD HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _hash_password(plain: str) -> str:
    """bcrypt hash — auto-salted, safe against rainbow tables."""
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def _check_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))


def _generate_token() -> str:
    """Cryptographically secure 64-char session token."""
    return secrets.token_hex(32)


# ═══════════════════════════════════════════════════════════════════════════
# 3.  CHANNELS  (Super Admin only)
# ═══════════════════════════════════════════════════════════════════════════
def add_channel(channel_id: str, channel_name: str) -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, channel_name) VALUES (?, ?)",
            (channel_id.strip(), channel_name.strip())
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ add_channel: {e}")
        return False
    finally:
        conn.close()


def get_all_channels() -> list:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM channels ORDER BY COALESCE(created_at, '') DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_channel_by_id(channel_id: str) -> dict | None:
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM channels WHERE channel_id = ?", (channel_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_channel(channel_id: str):
    """Cascade deletes channel_admins, categories, flash_keywords for this channel."""
    conn = get_connection()
    conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()


def toggle_channel_active(channel_id: str):
    conn = get_connection()
    conn.execute(
        "UPDATE channels SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE channel_id = ?",
        (channel_id,)
    )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# 4.  CHANNEL ADMINS  (Super Admin creates / manages)
# ═══════════════════════════════════════════════════════════════════════════
def create_channel_admin(channel_id: str, username: str,
                          password: str, panel_slug: str) -> tuple[bool, str]:
    """
    Super Admin calls this.
    Returns (True, 'ok') or (False, 'reason').
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not panel_slug.replace('-', '').replace('_', '').isalnum():
        return False, "Panel slug can only contain letters, numbers, hyphens, underscores."

    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO channel_admins
               (channel_id, username, password_hash, panel_slug)
               VALUES (?, ?, ?, ?)""",
            (channel_id, username.strip(),
             _hash_password(password), panel_slug.strip().lower())
        )
        conn.commit()
        return True, "Channel admin created."
    except sqlite3.IntegrityError as e:
        msg = str(e)
        if "username" in msg:
            return False, "Username already exists."
        if "panel_slug" in msg:
            return False, "Panel slug already taken."
        return False, msg
    finally:
        conn.close()


def login_channel_admin(username: str, password: str) -> dict | None:
    """
    Validates credentials.
    On success → rotates session token, updates last_login, returns admin dict.
    On failure → returns None.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM channel_admins WHERE username = ? AND is_active = 1",
            (username.strip(),)
        ).fetchone()

        if not row:
            return None
        if not _check_password(password, row['password_hash']):
            return None

        # Rotate session token on every login
        new_token = _generate_token()
        conn.execute(
            "UPDATE channel_admins SET session_token = ?, last_login = ? WHERE id = ?",
            (new_token, datetime.now().isoformat(), row['id'])
        )
        conn.commit()

        admin = dict(row)
        admin['session_token'] = new_token
        return admin
    finally:
        conn.close()


def logout_channel_admin(admin_id: int):
    """Invalidates session token — forces re-login."""
    conn = get_connection()
    conn.execute(
        "UPDATE channel_admins SET session_token = NULL WHERE id = ?",
        (admin_id,)
    )
    conn.commit()
    conn.close()


def verify_session_token(admin_id: int, token: str) -> bool:
    """Called on every protected request to validate session."""
    if not token:
        return False
    conn = get_connection()
    row  = conn.execute(
        "SELECT session_token FROM channel_admins WHERE id = ? AND is_active = 1",
        (admin_id,)
    ).fetchone()
    conn.close()
    if not row or not row['session_token']:
        return False
    return secrets.compare_digest(row['session_token'], token)  # timing-safe compare


def get_admin_by_slug(panel_slug: str) -> dict | None:
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM channel_admins WHERE panel_slug = ? AND is_active = 1",
        (panel_slug.strip().lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_admins() -> list:
    """Super Admin — full list with channel names."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT ca.id, ca.username, ca.panel_slug, ca.is_active,
               ca.created_at, ca.last_login,
               ch.channel_id, ch.channel_name
        FROM   channel_admins ca
        LEFT JOIN channels ch ON ca.channel_id = ch.channel_id
        ORDER  BY ca.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_channel_admin(admin_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM channel_admins WHERE id = ?", (admin_id,))
    conn.commit()
    conn.close()


def toggle_admin_active(admin_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE channel_admins SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id = ?",
        (admin_id,)
    )
    conn.commit()
    conn.close()


def update_admin_password(admin_id: int, new_password: str) -> tuple[bool, str]:
    if len(new_password) < 8:
        return False, "Password must be at least 8 characters."
    conn = get_connection()
    conn.execute(
        "UPDATE channel_admins SET password_hash = ?, session_token = NULL WHERE id = ?",
        (_hash_password(new_password), admin_id)
    )
    conn.commit()
    conn.close()
    return True, "Password updated. All sessions invalidated."


# ═══════════════════════════════════════════════════════════════════════════
# 5.  CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════
def add_category(name: str, keywords: str, min_discount: int, channel_id=None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO categories (name, keywords, min_discount, channel_id) VALUES (?, ?, ?, ?)",
        (name.strip(), keywords.strip(), int(min_discount), channel_id)
    )
    conn.commit()
    conn.close()


def get_all_categories() -> list:
    """
    BACKWARD COMPATIBLE — existing main.py calls this without channel_id.
    Returns list of tuples (id, name, keywords, min_discount).
    """
    conn  = get_connection()
    rows  = conn.execute(
        "SELECT id, name, keywords, min_discount FROM categories ORDER BY id"
    ).fetchall()
    conn.close()
    return [tuple(r) for r in rows]


def get_categories_by_channel(channel_id: str) -> list:
    """Channel Admin — only their categories. Returns list of dicts."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM categories WHERE channel_id = ? ORDER BY id",
        (channel_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_categories_for_bot(channel_id: str) -> list:
    """
    Bot per-channel loop uses this.
    Priority: channel's own → fallback to super-admin global (NULL).
    Returns list of tuples for backward compat with run_bot() code.
    """
    conn  = get_connection()
    rows  = conn.execute(
        "SELECT id, name, keywords, min_discount FROM categories WHERE channel_id = ? ORDER BY id",
        (channel_id,)
    ).fetchall()

    if not rows:
        # fallback to global/super-admin categories
        rows = conn.execute(
            "SELECT id, name, keywords, min_discount FROM categories WHERE channel_id IS NULL ORDER BY id"
        ).fetchall()

    conn.close()
    return [tuple(r) for r in rows]


def delete_category(cat_id: int, channel_id=None):
    """
    channel_id passed → ensures channel admin can only delete their own.
    channel_id None   → super admin deletes any.
    """
    conn = get_connection()
    if channel_id:
        conn.execute(
            "DELETE FROM categories WHERE id = ? AND channel_id = ?",
            (cat_id, channel_id)
        )
    else:
        conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    conn.commit()
    conn.close()


def update_category(cat_id: int, name: str, keywords: str,
                    min_discount: int, channel_id=None):
    conn = get_connection()
    if channel_id:
        conn.execute(
            """UPDATE categories
               SET name=?, keywords=?, min_discount=?
               WHERE id=? AND channel_id=?""",
            (name.strip(), keywords.strip(), int(min_discount), cat_id, channel_id)
        )
    else:
        conn.execute(
            "UPDATE categories SET name=?, keywords=?, min_discount=? WHERE id=?",
            (name.strip(), keywords.strip(), int(min_discount), cat_id)
        )
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# 6.  FLASH KEYWORDS
# ═══════════════════════════════════════════════════════════════════════════
def add_flash_keyword(keyword: str, min_discount: int, channel_id=None):
    conn = get_connection()
    conn.execute(
        "INSERT INTO flash_keywords (keyword, min_discount, channel_id) VALUES (?, ?, ?)",
        (keyword.strip().lower(), int(min_discount), channel_id)
    )
    conn.commit()
    conn.close()


def get_all_flash_keywords() -> list:
    """
    BACKWARD COMPATIBLE — existing main.py calls this.
    Returns list of tuples (id, keyword, min_discount).
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, keyword, min_discount FROM flash_keywords ORDER BY id"
    ).fetchall()
    conn.close()
    return [tuple(r) for r in rows]


def get_flash_keywords_by_channel(channel_id: str) -> list:
    """Channel Admin — only their flash keywords."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM flash_keywords WHERE channel_id = ? ORDER BY id",
        (channel_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_flash_keywords_for_bot(channel_id: str) -> list:
    """
    Bot per-channel flash loop uses this.
    Priority: channel's own → fallback to global.
    Returns list of tuples (id, keyword, min_discount).
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, keyword, min_discount FROM flash_keywords WHERE channel_id = ? ORDER BY id",
        (channel_id,)
    ).fetchall()

    if not rows:
        rows = conn.execute(
            "SELECT id, keyword, min_discount FROM flash_keywords WHERE channel_id IS NULL ORDER BY id"
        ).fetchall()

    conn.close()
    return [tuple(r) for r in rows]


def delete_flash_keyword(kw_id: int, channel_id=None):
    conn = get_connection()
    if channel_id:
        conn.execute(
            "DELETE FROM flash_keywords WHERE id = ? AND channel_id = ?",
            (kw_id, channel_id)
        )
    else:
        conn.execute("DELETE FROM flash_keywords WHERE id = ?", (kw_id,))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# 7.  SENT DEALS  (dedup + history)
# ═══════════════════════════════════════════════════════════════════════════
def save_deal(title: str, original_link: str, affiliate_link: str,
              category: str, channel_id=None):
    conn = get_connection()
    conn.execute(
        """INSERT INTO sent_deals
           (title, original_link, affiliate_link, category, channel_id)
           VALUES (?, ?, ?, ?, ?)""",
        (title, original_link, affiliate_link, category, channel_id)
    )
    conn.commit()
    conn.close()


def is_link_already_sent(link: str, channel_id=None) -> bool:
    """
    Per-channel dedup: same product can go to different channels.
    channel_id=None → global check (backward compat).
    """
    conn = get_connection()
    if channel_id:
        row = conn.execute(
            "SELECT 1 FROM sent_deals WHERE original_link = ? AND channel_id = ?",
            (link, channel_id)
        ).fetchone()
    else:
        # backward compat: check without channel filter
        row = conn.execute(
            "SELECT 1 FROM sent_deals WHERE original_link = ?", (link,)
        ).fetchone()
    conn.close()
    return row is not None


def get_total_deals_count(channel_id=None) -> int:
    conn = get_connection()
    if channel_id:
        row = conn.execute(
            "SELECT COUNT(*) FROM sent_deals WHERE channel_id = ?", (channel_id,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM sent_deals").fetchone()
    conn.close()
    return row[0] if row else 0


def clear_all_deals(channel_id=None):
    conn = get_connection()
    if channel_id:
        conn.execute("DELETE FROM sent_deals WHERE channel_id = ?", (channel_id,))
    else:
        conn.execute("DELETE FROM sent_deals")
    conn.commit()
    conn.close()


def get_recent_deals(limit=50, channel_id=None) -> list:
    """Super Admin sees all; channel admin sees their own."""
    conn = get_connection()
    if channel_id:
        rows = conn.execute(
            """SELECT * FROM sent_deals WHERE channel_id = ?
               ORDER BY sent_at DESC LIMIT ?""",
            (channel_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sent_deals ORDER BY sent_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════
# 8.  SUPER ADMIN — OVERVIEW STATS  (for super admin dashboard)
# ═══════════════════════════════════════════════════════════════════════════
def get_super_admin_stats() -> dict:
    """Returns key numbers for super admin dashboard cards."""
    conn = get_connection()
    stats = {
        'total_channels'  : conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0],
        'active_channels' : conn.execute("SELECT COUNT(*) FROM channels WHERE is_active=1").fetchone()[0],
        'total_admins'    : conn.execute("SELECT COUNT(*) FROM channel_admins").fetchone()[0],
        'active_admins'   : conn.execute("SELECT COUNT(*) FROM channel_admins WHERE is_active=1").fetchone()[0],
        'total_deals_sent': conn.execute("SELECT COUNT(*) FROM sent_deals").fetchone()[0],
        'total_categories': conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
        'total_flash_kw'  : conn.execute("SELECT COUNT(*) FROM flash_keywords").fetchone()[0],
    }
    conn.close()
    return stats


def get_per_channel_stats() -> list:
    """
    Super Admin — per-channel breakdown table.
    Returns list of dicts.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            ch.channel_id,
            ch.channel_name,
            ch.is_active,
            COUNT(DISTINCT sd.id)  AS deals_sent,
            COUNT(DISTINCT cat.id) AS category_count,
            COUNT(DISTINCT fk.id)  AS flash_kw_count,
            ca.username            AS admin_username,
            ca.panel_slug          AS admin_slug,
            ca.last_login          AS admin_last_login
        FROM channels ch
        LEFT JOIN sent_deals    sd  ON sd.channel_id  = ch.channel_id
        LEFT JOIN categories    cat ON cat.channel_id = ch.channel_id
        LEFT JOIN flash_keywords fk ON fk.channel_id  = ch.channel_id
        LEFT JOIN channel_admins ca ON ca.channel_id  = ch.channel_id
        GROUP BY ch.channel_id
        ORDER BY deals_sent DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]