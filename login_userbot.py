import os
import sys
import time

# Ensure project paths are resolved
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# 🛡️ SECURITY: Production guard — prevents accidental execution on live server
_PRODUCTION_SENTINEL = os.path.join(BASE_DIR, '.production')
if os.path.isfile(_PRODUCTION_SENTINEL):
    print("❌ PRODUCTION GUARD: login_userbot.py should NOT be run on a live server.")
    print("   Remove the .production file to bypass this guard.")
    sys.exit(1)

from config import API_ID, API_HASH, SESSION_PATH
from userbot.extrape_agent import _resolve_session_file

try:
    from telethon import TelegramClient
except ImportError:
    print("❌ Telethon is not installed! Please run: pip install telethon")
    sys.exit(1)

session_file = _resolve_session_file(SESSION_PATH)

print("="*60)
print("🔑 TELETHON USERBOT (SECRET AGENT) LOGIN HELPER")
print("="*60)
print(f"API credentials configured: {bool(API_ID and API_HASH)}")
print(f"Session File Path: {session_file}.session\n")

if not API_ID or not API_HASH:
    print("❌ API_ID or API_HASH is missing! Please save them in your Dashboard Settings first.")
    sys.exit(1)

client = TelegramClient(session_file, API_ID, API_HASH)

async def main():
    print("Connecting to Telegram...")
    await client.connect()
    
    if not await client.is_user_authorized():
        print("🔓 Userbot is NOT authorized. Starting interactive login...")
        print("Aapko apna Telegram phone number (with country code, e.g., +91XXXXXXXXXX) aur verification code dalna hoga.\n")
        try:
            # client.start will ask for phone, code, and 2FA password if set
            await client.start()
        except Exception as e:
            print(f"\n❌ Login error: {e}")
            return
    else:
        print("✅ Userbot is ALREADY authorized!")

    me = await client.get_me()
    print("\n" + "="*50)
    print("🎉 LOGIN SUCCESSFUL / VERIFIED!")
    print(f"Logged in as: {me.first_name} {me.last_name or ''} (@{me.username or 'NoUsername'})")
    print(f"Session saved securely at: {session_file}.session")
    print("="*50)
    print("💡 Ab aap apna main.py chala sakte hain, userbot perfectly links generate karega!")

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
