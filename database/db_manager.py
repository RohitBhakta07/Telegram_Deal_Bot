import sqlite3
import os

# Database file path setup
DB_PATH = os.path.join(os.path.dirname(__file__), 'bot_data.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
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
            min_discount INTEGER
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

    conn.commit()
    conn.close()

# --- CATEGORIES FUNCTIONS ---
def add_category(name, keywords, min_discount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO categories (name, keywords, min_discount) VALUES (?, ?, ?)", 
                   (name, keywords, min_discount))
    conn.commit()
    conn.close()

def get_all_categories():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()
    conn.close()
    return categories

def delete_category(cat_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()

def update_category(cat_id, name, keywords, min_discount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE categories SET name=?, keywords=?, min_discount=? WHERE id=?", 
                   (name, keywords, min_discount, cat_id))
    conn.commit()
    conn.close()

# --- FLASH SNIPER FUNCTIONS ---
def add_flash_keyword(keyword, min_discount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO flash_keywords (keyword, min_discount) VALUES (?, ?)", 
                   (keyword, min_discount))
    conn.commit()
    conn.close()

def get_all_flash_keywords():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM flash_keywords")
    keywords = cursor.fetchall()
    conn.close()
    return keywords

def delete_flash_keyword(keyword_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM flash_keywords WHERE id = ?", (keyword_id,))
    conn.commit()
    conn.close()

def update_flash_keyword(keyword_id, keyword, min_discount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE flash_keywords SET keyword=?, min_discount=? WHERE id=?", 
                   (keyword, min_discount, keyword_id))
    conn.commit()
    conn.close()

# --- UTILITY FUNCTIONS ---
def get_total_deals_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sent_deals")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def clear_all_deals():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sent_deals")
    conn.commit()
    conn.close()

def is_link_already_sent(original_link):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM sent_deals WHERE original_link=?", (original_link,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def save_deal(title, original_link, affiliate_link, category="General"):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sent_deals (title, original_link, affiliate_link, category) VALUES (?, ?, ?, ?)",
            (title, original_link, affiliate_link, category)
        )
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError:
        pass

# --- SETTINGS FUNCTIONS ---
def get_setting(key, default_value=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else default_value

def update_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# --- CHANNEL FUNCTIONS ---
def add_channel(channel_id, channel_name):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO channels (channel_id, channel_name) VALUES (?, ?)", (channel_id, channel_name))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

def get_all_channels():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_name FROM channels")
    results = cursor.fetchall()
    conn.close()
    return results

def delete_channel(channel_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE channel_id=?", (channel_id,))
    conn.commit()
    conn.close()