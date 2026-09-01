import os
import sys
from secret_store import SecretConfigurationError, get_secret
from runtime_env import load_runtime_env, private_data_dir

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

load_runtime_env()

def _load_secret(key):
    try:
        return get_secret(key)
    except SecretConfigurationError as exc:
        print(f"SECURITY CONFIG ERROR ({key}): {exc}")
        return ""


API_ID = _load_secret('API_ID')
API_HASH = _load_secret('API_HASH')
BOT_TOKEN = _load_secret('BOT_TOKEN')
EXTRAPE_AFFID = _load_secret('EXTRAPE_AFFID')
EXTRAPE_PARAM1 = _load_secret('EXTRAPE_PARAM1')

DB_PATH = os.path.join(BASE_DIR, 'database', 'bot_data.db')
SESSION_PATH = str(private_data_dir() / 'sessions')

if not BOT_TOKEN or not API_ID:
    print("Warning: Dashboard mein API keys save nahi hain!")
