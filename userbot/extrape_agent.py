import asyncio
import re
import sys
import os

# 📂 HOSTING PATH FIX
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# 🛡️ Config se API Keys aur Session ka fixed raasta uthana
from config import API_ID, API_HASH, SESSION_PATH
from telethon import TelegramClient

EXTRAPE_BOT_USERNAME = '@ExtraPeBot' 

# ✅ CRITICAL HOSTING FIX: Ab session file server par hamesha ek hi jagah rahegi
client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

async def get_extrape_link(original_link):
    """
    Link bhejega aur specifically ExtraPe ke naye reply ka wait karega.
    """
    try:
        # 🚀 Server par connection open/close check karne ka safe tareeka
        if not client.is_connected():
            await client.connect()

        print(f"🕵️‍♂️ Agent: Sending link and waiting for reply...")
        
        # Timeout 60 second rakha hai taaki bot hamesha ke liye na atak jaye
        async with client.conversation(EXTRAPE_BOT_USERNAME, timeout=60) as conv:
            # 1. ExtraPe ko message bhejte hain
            await conv.send_message(original_link)
            
            # 2. Specifically uske agle naye reply ka wait karte hain
            response = await conv.get_response()
            reply_text = response.text
            
            # 3. Reply aate hi usme se link nikalte hain
            if "http" in reply_text:
                urls = re.findall(r'(https?://[^\s]+)', reply_text)
                
                if urls:
                    # Sirf wahi link uthaayenge jo lamba flipkart.com wala NAHI hai (taaki fkrt.co mile)
                    short_urls = [u for u in urls if 'flipkart.com' not in u]
                    
                    if short_urls:
                        print(f"✅ Affiliate Link Received: {short_urls[0]}")
                        return short_urls[0]
                    else:
                        print(f"⚠️ ExtraPe ne lamba link wapas kar diya. Backup chalayenge.")
                        return original_link
            
        print("⚠️ Reply mein koi link nahi mila.")
        return original_link

    except asyncio.TimeoutError:
        print("⏳ Timeout: ExtraPe ne 60 sec tak reply nahi diya. Backup chalayenge.")
        return original_link
    except Exception as e:
        print(f"❌ Userbot Error: {e}")
        return original_link

def get_sync_link(original_link):
    # Server par async loops ko run karne ka safe wrapper
    with client:
        return client.loop.run_until_complete(get_extrape_link(original_link))