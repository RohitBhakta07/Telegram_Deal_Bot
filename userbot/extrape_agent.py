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
try:
    from telethon import TelegramClient
except Exception:
    TelegramClient = None

EXTRAPE_BOT_USERNAME = '@ExtraPeBot'

# Ensure session directory exists and use a session file path
try:
    if SESSION_PATH and not os.path.exists(SESSION_PATH):
        os.makedirs(SESSION_PATH, exist_ok=True)
    session_file = SESSION_PATH if os.path.isfile(SESSION_PATH) else os.path.join(SESSION_PATH, 'extrape.session')
except Exception:
    session_file = SESSION_PATH or 'extrape.session'

client = None
if TelegramClient is not None:
    try:
        client = TelegramClient(session_file, API_ID, API_HASH)
    except Exception as e:
        print(f"⚠️ Telethon Client init error: {e}")
        client = None
else:
    print("⚠️ Telethon not installed. userbot features disabled.")

async def get_extrape_link(original_link):
    """
    Link bhejega aur specifically ExtraPe ke naye reply ka wait karega.
    """
    # 🛡️ HOSTING FIX: Agar client init nahi hua ya authorized nahi hai toh seedha original link return karo
    if client is None:
        print("⚠️ Telethon client not initialized. Returning original link.")
        return original_link
        
    try:
        if not client.is_connected():
            await client.connect()

        if not await client.is_user_authorized():
            print("⚠️ Userbot is NOT authorized. Fallback to original link.")
            return original_link

        print(f"🕵️‍♂️ Agent: Sending link and waiting for reply...")
        
        # 🛡️ SECURITY: Reduced timeout from 60s to 20s so consumer thread never blocks
        async with client.conversation(EXTRAPE_BOT_USERNAME, timeout=20) as conv:
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
        print("⏳ Timeout: ExtraPe ne 20 sec tak reply nahi diya. Backup chalayenge.")
        return original_link
    except ConnectionError:
        print("❌ Telethon Connection Error: Internet ya Telegram server down hai.")
        return original_link
    except Exception as e:
        print(f"❌ Userbot Error: {e}")
        return original_link

def get_sync_link(original_link):
    # 🛡️ HOSTING FIX: Agar client None hai toh async loop mat chalao
    if client is None:
        print("⚠️ Telethon client not available. Using original link.")
        return original_link
        
    try:
        # 🛡️ THREAD FIX: Background thread mein event loop nahi hota,
        # toh naya banao agar zaroorat ho
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        async def run_async_safe():
            try:
                if not client.is_connected():
                    await client.connect()
                
                # Check authorization without prompting
                if not await client.is_user_authorized():
                    print("⚠️ [Telethon] Userbot is NOT authorized! Fallback to backup URL.")
                    return original_link
                
                return await get_extrape_link(original_link)
            except Exception as e:
                print(f"❌ Userbot async authorization / run error: {e}")
                return original_link
            
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(asyncio.run, run_async_safe()).result(timeout=30)
            return result
            
        return loop.run_until_complete(run_async_safe())
        
    except Exception as e:
        print(f"❌ Sync Link Error: {e}")
        return original_link