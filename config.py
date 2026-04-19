import os
import sys

# 1. 📂 Project ka Root Path fix karna (Hamesha sahi folder dhoondhega)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. 🛣️ System path mein project root add karna taaki 'database' folder mil jaye
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from database.db_manager import get_setting

# 3. 🚀 Database se Settings uthana (Safe version)
def safe_get(key, default=""):
    try:
        val = get_setting(key)
        return val if val else default
    except:
        return default

API_ID = safe_get('API_ID')
API_HASH = safe_get('API_HASH')
BOT_TOKEN = safe_get('BOT_TOKEN')
EXTRAPE_AFFID = safe_get('EXTRAPE_AFFID', '87869')
EXTRAPE_PARAM1 = safe_get('EXTRAPE_PARAM1', 'Junaid')

# 4. 📁 Hosting ke liye Files ke raaste (Absolute Paths)
# Server par files dhoondhne ke liye ye zaroori hain
DB_PATH = os.path.join(BASE_DIR, 'database', 'bot_data.db')
SESSION_PATH = os.path.join(BASE_DIR, 'userbot', 'extrape_session')

# ⚠️ Security Alert
if not BOT_TOKEN or not API_ID:
    print("⚠️ Warning: Dashboard mein API keys save nahi hain!")