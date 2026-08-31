"""
ExtraPe affiliate link agent — thread-safe Telethon wrapper.

Telethon's async client must be created and used on the same event loop.
This module runs a dedicated event loop in a background daemon thread.
All async calls are submitted via run_coroutine_threadsafe, making
get_sync_link() safe to call from any thread.

The .session file persists auth credentials across restarts.
"""
import asyncio
import re
import sys
import os
import threading
from urllib.parse import urlsplit

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from config import API_ID, API_HASH, SESSION_PATH
try:
    from telethon import TelegramClient
except Exception:
    TelegramClient = None

EXTRAPE_BOT_USERNAME = '@ExtraPeBot'

def _resolve_session_file(session_path):
    """Return a Telethon session *file prefix*, never a directory."""
    if not session_path:
        return os.path.join(parent_dir, "userbot", "extrape_session", "extrape")

    expanded = os.path.abspath(os.path.expanduser(str(session_path)))
    # Config historically stores a directory.  A .session suffix explicitly
    # means that the caller supplied a file path.
    if expanded.lower().endswith(".session"):
        os.makedirs(os.path.dirname(expanded) or ".", exist_ok=True)
        return expanded[:-8]  # Telethon adds .session itself

    os.makedirs(expanded, exist_ok=True)
    return os.path.join(expanded, "extrape")


_session_file = _resolve_session_file(SESSION_PATH)


# -------------------------------------------------------------------
# Dedicated event loop thread — single persistent loop for Telethon
# -------------------------------------------------------------------
_loop = None
_loop_lock = threading.Lock()
_loop_thread = None


def _start_loop_thread():
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None:
            return _loop
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_loop.run_forever,
            daemon=True,
            name="TelethonLoop",
        )
        _loop_thread.start()
        return _loop


def _stop_loop():
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            _loop.call_soon_threadsafe(_loop.stop)
        _loop = None
        _loop_thread = None


# -------------------------------------------------------------------
# Core async logic
# -------------------------------------------------------------------
async def _get_extrape_link(client, original_link):
    try:
        if not await client.is_user_authorized():
            print("[ExtraPe] Userbot is NOT authorized. Using original link.")
            return original_link

        print("[ExtraPe] Sending link and waiting for reply...")

        async with client.conversation(EXTRAPE_BOT_USERNAME, timeout=60) as conv:
            await conv.send_message(original_link)
            response = await conv.get_response()
            reply_text = response.text or ""
            urls = re.findall(r'https?://[^\s<>"\']+', reply_text)
            # ExtraPe may place the generated URL only in an inline button.
            for row in (response.buttons or []):
                for button in row:
                    button_url = getattr(button, "url", None)
                    if button_url:
                        urls.append(button_url)

            cleaned = []
            for url in urls:
                url = url.rstrip('.,);]}')
                try:
                    if urlsplit(url).scheme in ("http", "https") and url != original_link:
                        cleaned.append(url)
                except Exception:
                    continue
            if cleaned:
                preferred = next((u for u in cleaned if 'fkrt.co' in u.lower()), cleaned[0])
                print(f"[ExtraPe] Affiliate link received: {preferred}")
                return preferred

        print("[ExtraPe] No link found in reply.")
        return original_link

    except asyncio.TimeoutError:
        print("[ExtraPe] Timeout after 60s. Using original link.")
        return original_link
    except ConnectionError:
        print("[ExtraPe] Telegram connection error. Using original link.")
        return original_link
    except Exception as e:
        print(f"[ExtraPe] Userbot error: {e}")
        return original_link


async def _run_async(original_link):
    if not API_ID or not API_HASH:
        print("[ExtraPe] API_ID/API_HASH missing; userbot disabled.")
        return original_link
    client = TelegramClient(_session_file, API_ID, API_HASH)
    try:
        await client.connect()
        return await _get_extrape_link(client, original_link)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# -------------------------------------------------------------------
# Public thread-safe entry point
# -------------------------------------------------------------------
def get_sync_link(original_link):
    if not original_link:
        return original_link
    if TelegramClient is None:
        print("[ExtraPe] Telethon not installed. Using original link.")
        return original_link

    loop = _start_loop_thread()

    try:
        future = asyncio.run_coroutine_threadsafe(
            _run_async(original_link), loop,
        )
        return future.result(timeout=90)
    except asyncio.TimeoutError:
        print("[ExtraPe] Sync call timed out after 90s. Using original link.")
        return original_link
    except Exception as e:
        print(f"[ExtraPe] Sync link error: {e}")
        return original_link
