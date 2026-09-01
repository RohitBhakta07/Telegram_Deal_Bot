import sqlite3
import os
import time
import random
import threading
import bcrypt
import hashlib
import hmac
import secrets

# Database file path setup
DB_PATH = os.path.join(os.path.dirname(__file__), 'bot_data.db')

# Connection pool for thread safety
_connection_cache = threading.local()

def _get_connection(retries=3):
    """SQLite connection with retry logic and per-thread caching."""
    if hasattr(_connection_cache, 'conn'):
        try:
            _connection_cache.conn.execute("SELECT 1")
            return _connection_cache.conn
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            pass
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=15)
            _enable_secure_db_pragmas(conn)
            _connection_cache.conn = conn
            return conn
        except sqlite3.OperationalError as e:
            if attempt < retries - 1:
                time.sleep(0.5)
            else:
                raise e

def _enable_secure_db_pragmas(conn):
    """Enable durability and privacy-related SQLite options."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA secure_delete=ON")

def _hash_password(password):
    """bcrypt password hashing with built-in salt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

def _check_password(password, stored_hash):
    """Verify bcrypt plus older PBKDF2/SHA-256 hashes during migration."""
    try:
        if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
            return bcrypt.checkpw(password.encode(), stored_hash.encode())
        if '$' in stored_hash:
            salt, expected = stored_hash.split('$', 1)
            computed = hashlib.pbkdf2_hmac(
                'sha256', password.encode(), salt.encode(), 100000
            ).hex()
            return hmac.compare_digest(computed, expected)
        computed = hashlib.sha256(password.encode()).hexdigest()
        return hmac.compare_digest(computed, stored_hash)
    except Exception:
        return False


def validate_admin_password(password):
    """Return (valid, message) for dashboard password policy."""
    if len(password or "") < 12:
        return False, "Password must be at least 12 characters."
    if not any(char.isalpha() for char in password):
        return False, "Password must include at least one letter."
    if not any(char.isdigit() for char in password):
        return False, "Password must include at least one number."
    if password.lower() in {"admin123456", "password1234", "admin123456789"}:
        return False, "Choose a less predictable password."
    return True, ""

def init_db():
    conn = _get_connection()
    cursor = conn.cursor()

    # 1. Sent Deals Table (History record ke liye)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            original_link TEXT UNIQUE,
            affiliate_link TEXT,
            category TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. Channels Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT UNIQUE,
            channel_name TEXT
        )
    ''')

    # 3. Settings Table (API IDs aur Tokens ke liye)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # 4. Categories Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            keywords TEXT,
            min_discount INTEGER,
            priority TEXT DEFAULT 'MEDIUM'
        )
    ''')

    # 5. Flash Keywords Table (Ninja Sniper ke liye)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flash_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            min_discount INTEGER NOT NULL
        )
    ''')

    # 6. 🔒 Admin Users Table (Dashboard Login)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')

    # Default admin create karo agar nahi hai
    cursor.execute("SELECT COUNT(*) FROM admin_users")
    if cursor.fetchone()[0] == 0:
        # Generate and discard a random bootstrap password. New installations
        # must explicitly initialize credentials with reset_dashboard_login.py.
        default_hash = _hash_password(secrets.token_urlsafe(32))
        cursor.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                       ("admin", default_hash))
        print("🔒 Dashboard admin initialized. Run reset_dashboard_login.py before login.")

    # Migrate older DBs that were created before priority column existed
    cursor.execute("PRAGMA table_info(categories)")
    category_columns = {row[1] for row in cursor.fetchall()}
    if 'priority' not in category_columns:
        cursor.execute("ALTER TABLE categories ADD COLUMN priority TEXT DEFAULT 'MEDIUM'")
    cursor.execute(
        "UPDATE categories SET priority='MEDIUM' WHERE priority IS NULL OR TRIM(priority)=''"
    )
    if 'post_format' not in category_columns:
        cursor.execute(
            "ALTER TABLE categories ADD COLUMN post_format TEXT DEFAULT 'default'"
        )
    cursor.execute(
        "UPDATE categories SET post_format='default' WHERE post_format IS NULL OR TRIM(post_format)=''"
    )

    # Migrate older DBs that were created without product_image / post_type columns
    cursor.execute("PRAGMA table_info(sent_deals)")
    sent_columns = {row[1] for row in cursor.fetchall()}
    if 'product_image' not in sent_columns:
        cursor.execute("ALTER TABLE sent_deals ADD COLUMN product_image TEXT DEFAULT ''")
    if 'post_type' not in sent_columns:
        cursor.execute("ALTER TABLE sent_deals ADD COLUMN post_type TEXT DEFAULT 'normal'")

    # Default settings (INSERT OR IGNORE — restart par saved value overwrite nahi hogi)
    default_settings = {
        'PRICE_SCREENSHOT': 'ON',
        'DEFAULT_POST_FORMAT': 'hot_deal',
        'FLASH_POST_FORMAT': 'mega_loot',
        'bot_status': 'ON',
        'FLASH_INTERVAL': '3',
        'ROUND_WAIT': '15',
        'LONG_SLEEP': '60',
        'KEYWORDS_PER_ROUND': '4',
        # 🚀 V2: Priority Queue Architecture Settings
        'MIN_BUYERS_COUNT': '1000',       # Product page se buyers count check — Dashboard se change karo
        'MAX_SCRAPE_PAGES': '3',          # Ek keyword par max kitne pages check kare
        'MAX_WORKERS': '2',               # Kitne keywords ek saath parallel scrape hon (RAM ke hisaab se set karo)
        'QUEUE_DELAY_POST': '15',         # Queue se deal uthane ke baad kitne second ruke (Telegram spam protection)
        'ALLOW_MISSING_BUYERS': 'OFF',    # Agar buyers_count na mile toh deal accept kare ya nahi
    }
    for key, value in default_settings.items():
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )

    # Performance indexes
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sent_deals_link ON sent_deals(original_link)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sent_deals_timestamp ON sent_deals(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_settings_key ON settings(key)")
    except Exception:
        pass

    conn.commit()
    conn.close()

# --- CATEGORY PRIORITY HELPERS ---
VALID_PRIORITIES = ('HIGH', 'MEDIUM', 'LOW')

def normalize_priority(priority):
    value = (priority or 'MEDIUM').strip().upper()
    return value if value in VALID_PRIORITIES else 'MEDIUM'

def get_priority_weight(priority):
    priority = normalize_priority(priority)
    if priority == 'HIGH':
        return 4
    if priority == 'MEDIUM':
        return 2
    return 1

def _category_priority(cat):
    return cat[4] if len(cat) > 4 else 'MEDIUM'

def order_categories_by_priority(categories):
    """Return categories in deterministic HIGH → MEDIUM → LOW order."""
    return sorted(
        categories,
        key=lambda cat: get_priority_weight(_category_priority(cat)),
        reverse=True,
    )

def build_keyword_weights(categories):
    """Map each keyword to its highest priority weight across categories."""
    weights = {}
    for cat in categories:
        priority = _category_priority(cat)
        weight = get_priority_weight(priority)
        try:
            keywords = [k.strip().lower() for k in cat[2].split(',') if k.strip()]
        except (IndexError, TypeError):
            continue
        for keyword in keywords:
            weights[keyword] = max(weights.get(keyword, 1), weight)
    return weights

def pick_weighted_keyword(pool, keyword_weights):
    if not pool:
        return None
    weights = [keyword_weights.get(kw, 1) for kw in pool]
    return random.choices(pool, weights=weights, k=1)[0]

# --- 🔒 AUTH FUNCTIONS ---
def verify_admin(username, password):
    """Login check — returns True if credentials match"""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM admin_users WHERE username=?", (username,))
        result = cursor.fetchone()
        if result and _check_password(password, result[0]):
            if not result[0].startswith(("$2a$", "$2b$", "$2y$")):
                upgrade_admin_password(username, password)
            return True
        return False
    finally:
        conn.close()

def update_admin_password(username, new_password):
    """Password change / reset with salted hash"""
    valid, message = validate_admin_password(new_password)
    if not valid:
        raise ValueError(message)
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE admin_users SET password_hash=? WHERE username=?",
                       (_hash_password(new_password), username))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def upgrade_admin_password(username, password):
    """Upgrade legacy unsalted hash to salted hash"""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE admin_users SET password_hash=? WHERE username=?",
                       (_hash_password(password), username))
        conn.commit()
    finally:
        conn.close()

def get_admin_username():
    """Dashboard par dikhane ke liye current admin username"""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM admin_users LIMIT 1")
        result = cursor.fetchone()
        return result[0] if result else "admin"
    finally:
        conn.close()

# --- CATEGORIES FUNCTIONS ---
def add_category(name, keywords, min_discount, priority='MEDIUM', post_format='default'):
    priority = normalize_priority(priority)
    post_format = (post_format or 'default').strip().lower()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO categories (name, keywords, min_discount, priority, post_format) VALUES (?, ?, ?, ?, ?)",
            (name, keywords, min_discount, priority, post_format),
        )
        conn.commit()
    finally:
        conn.close()

def get_all_categories():
    """Return (id, name, keywords, min_discount, priority, post_format)."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, keywords, min_discount,
                   COALESCE(NULLIF(TRIM(priority), ''), 'MEDIUM') AS priority,
                   COALESCE(NULLIF(TRIM(post_format), ''), 'default') AS post_format
            FROM categories
            ORDER BY id
        """)
        return cursor.fetchall()
    finally:
        conn.close()

def update_category_priority(name, priority):
    priority = normalize_priority(priority)
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE categories SET priority=? WHERE name=?", (priority, name))
        conn.commit()
    finally:
        conn.close()

def delete_category(cat_id):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        conn.commit()
    finally:
        conn.close()

def update_category(cat_id, name, keywords, min_discount, priority='MEDIUM', post_format='default'):
    priority = normalize_priority(priority)
    post_format = (post_format or 'default').strip().lower()
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE categories SET name=?, keywords=?, min_discount=?, priority=?, post_format=? WHERE id=?",
            (name, keywords, min_discount, priority, post_format, cat_id),
        )
        conn.commit()
    finally:
        conn.close()

# --- FLASH SNIPER FUNCTIONS ---
def add_flash_keyword(keyword, min_discount):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO flash_keywords (keyword, min_discount) VALUES (?, ?)",
                       (keyword, min_discount))
        conn.commit()
    finally:
        conn.close()

def get_all_flash_keywords():
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM flash_keywords")
        keywords = cursor.fetchall()
        return keywords
    finally:
        conn.close()

def delete_flash_keyword(keyword_id):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM flash_keywords WHERE id = ?", (keyword_id,))
        conn.commit()
    finally:
        conn.close()

def update_flash_keyword(keyword_id, keyword, min_discount):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE flash_keywords SET keyword=?, min_discount=? WHERE id=?",
                       (keyword, min_discount, keyword_id))
        conn.commit()
    finally:
        conn.close()

# --- UTILITY FUNCTIONS ---
def get_total_deals_count():
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sent_deals")
        count = cursor.fetchone()[0]
        return count
    finally:
        conn.close()

def get_recent_deals(limit=20):
    """Recent deals for dashboard display (newest first)"""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, affiliate_link, category, timestamp, post_type, product_image FROM sent_deals ORDER BY id DESC LIMIT ?", (limit,))
        deals = cursor.fetchall()
        return deals
    finally:
        conn.close()

def get_all_deals_history(page=1, per_page=50):
    """Paginated deal history for the Post History tab (newest first)."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sent_deals")
        total = cursor.fetchone()[0]
        offset = (page - 1) * per_page
        cursor.execute(
            "SELECT id, title, original_link, affiliate_link, category, timestamp, post_type, product_image "
            "FROM sent_deals ORDER BY id DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        )
        deals = cursor.fetchall()
        total_pages = max(1, (total + per_page - 1) // per_page)
        return deals, total, total_pages, page
    finally:
        conn.close()

def get_deals_today_count():
    """Aaj kitni deals post hui"""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sent_deals WHERE DATE(timestamp) = DATE('now')")
        count = cursor.fetchone()[0]
        return count
    finally:
        conn.close()

def clear_all_deals():
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sent_deals")
        conn.commit()
    finally:
        conn.close()

def delete_oldest_deals(count=50):
    """Delete the oldest N deals from sent_deals (gradual cleanup)."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM sent_deals WHERE id IN (
                SELECT id FROM sent_deals ORDER BY id ASC LIMIT ?
            )
        """, (count,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

def is_link_already_sent(original_link):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM sent_deals WHERE original_link=?", (original_link,))
        result = cursor.fetchone()
        return result is not None
    finally:
        conn.close()

def save_deal(title, original_link, affiliate_link, category="General", product_image="", post_type="normal"):
    try:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO sent_deals (title, original_link, affiliate_link, category, product_image, post_type) VALUES (?, ?, ?, ?, ?, ?)",
                (title, original_link, affiliate_link, category, product_image, post_type)
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.IntegrityError:
        pass

# --- SETTINGS FUNCTIONS ---
def get_setting(key, default_value=None):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        result = cursor.fetchone()
        return result[0] if result else default_value
    finally:
        conn.close()

def update_setting(key, value):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        return True
    finally:
        conn.close()


def normalize_price_screenshot_setting(value):
    """Always store ON or OFF in database."""
    return 'ON' if str(value or '').strip().upper() == 'ON' else 'OFF'

# --- CHANNEL FUNCTIONS ---
def add_channel(channel_id, channel_name):
    try:
        conn = _get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO channels (channel_id, channel_name) VALUES (?, ?)", (channel_id, channel_name))
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.IntegrityError:
        return False

def get_all_channels():
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT channel_id, channel_name FROM channels")
        results = cursor.fetchall()
        return results
    finally:
        conn.close()

def delete_channel(channel_id):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM channels WHERE channel_id=?", (channel_id,))
        conn.commit()
    finally:
        conn.close()
