import os
import sys
import asyncio
from telethon import TelegramClient

# 📂 HOSTING PATH FIX
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from config import API_ID, API_HASH, SESSION_PATH

print("🚀 Starting Userbot Login Process...")

# Client banayenge config path ke sath
client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

async def main():
    # Ye aapse terminal mein Number aur OTP maangega
    await client.start()
    print("\n✅ LOGIN SUCCESSFUL! 'extrape_session.session' file ban gayi hai.")
    print("Ab aap is file ko band kar sakte hain aur apna main.py chala sakte hain.")

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())