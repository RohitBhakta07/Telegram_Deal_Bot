import os
import sys
import base64
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, '.env'))

def safe_get(key, default=""):
    try:
        val = os.getenv(key)
        if val:
            return val
        from database.db_manager import get_setting
        val = get_setting(key)
        return val if val else default
    except:
        return default

# Encrypted settings (read from DB with Fernet decryption)
def safe_get_encrypted(key, default=""):
    """Read encrypted setting from DB, decrypt with key from env."""
    try:
        encryption_key = os.environ.get('ENCRYPTION_KEY')
        if not encryption_key:
            return safe_get(key, default)
        from cryptography.fernet import Fernet
        cipher = Fernet(base64.urlsafe_b64encode(encryption_key.encode()[:32].ljust(32, b'0')))
        from database.db_manager import get_setting
        encrypted = get_setting(key)
        if encrypted:
            return cipher.decrypt(encrypted.encode()).decode()
    except Exception:
        pass
    return safe_get(key, default)

API_ID = safe_get('API_ID')
API_HASH = safe_get('API_HASH')
BOT_TOKEN = safe_get('BOT_TOKEN')
EXTRAPE_AFFID = safe_get('EXTRAPE_AFFID')
EXTRAPE_PARAM1 = safe_get('EXTRAPE_PARAM1')

DB_PATH = os.path.join(BASE_DIR, 'database', 'bot_data.db')
SESSION_PATH = os.path.join(BASE_DIR, 'userbot', 'extrape_session')

if not BOT_TOKEN or not API_ID:
    print("Warning: Dashboard mein API keys save nahi hain!")
