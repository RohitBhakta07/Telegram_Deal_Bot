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
from urllib.parse import parse_qs, urlsplit

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

import config
try:
    from telethon import TelegramClient
except Exception:
    TelegramClient = None

EXTRAPE_BOT_USERNAME = '@ExtraPeBot'
_REPLY_TIMEOUT = 60
_REQUEST_TIMEOUT = 75
_DISCONNECT_TIMEOUT = 5
_SYNC_TIMEOUT = 90
# Both callers share one SQLite session and one bot conversation. Reject an
# overlapping request instead of queuing stale work or opening a second client.
_session_lock = threading.Lock()
_cleanup_tasks = set()

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


_session_file = _resolve_session_file(config.SESSION_PATH)


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
def _trusted_affiliate_url(url, original_link):
    """Accept known Flipkart affiliate forms, never a hostname substring."""
    if not isinstance(url, str) or any(c.isspace() or ord(c) < 32 for c in url):
        return None
    url = url.rstrip('.,);]}')
    if url == original_link or '\\' in url:
        return None
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme not in ('http', 'https') or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 80, 443)):
            return None
        if host in ('fkrt.co', 'fkrt.it') and parsed.path.strip('/'):
            return url
        if (host == 'flipkart.com' or host.endswith('.flipkart.com')):
            if parsed.path.strip('/') and parse_qs(parsed.query).get('affid'):
                return url
    except ValueError:
        pass
    return None


async def _read_affiliate_reply(client, original_link):
    async with client.conversation(EXTRAPE_BOT_USERNAME, timeout=_REPLY_TIMEOUT) as conv:
        await conv.send_message(original_link)
        # Bots can send an acknowledgement or promotional message before the
        # generated URL. The outer deadline bounds the entire conversation.
        for _ in range(10):
            response = await conv.get_response()
            reply_text = response.text or ""
            urls = re.findall(r'https?://[^\s<>"\']+', reply_text)
            # ExtraPe may place the generated URL only in an inline button.
            for row in (response.buttons or []):
                for button in row:
                    button_url = getattr(button, "url", None)
                    if button_url:
                        urls.append(button_url)

            for url in urls:
                accepted = _trusted_affiliate_url(url, original_link)
                if accepted:
                    print("[ExtraPe] Affiliate link received.")
                    return accepted
    return original_link


async def _get_extrape_link(client, original_link):
    try:
        if not await client.is_user_authorized():
            print("[ExtraPe] Userbot is NOT authorized. Using original link.")
            return original_link
        print("[ExtraPe] Sending link and waiting for reply...")
        return await asyncio.wait_for(
            _read_affiliate_reply(client, original_link), timeout=_REPLY_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print("[ExtraPe] Reply deadline expired. Using original link.")
        return original_link
    except ConnectionError:
        print("[ExtraPe] Telegram connection error. Using original link.")
        return original_link
    except Exception as e:
        print(f"[ExtraPe] Userbot error ({type(e).__name__}). Using original link.")
        return original_link


async def _disconnect_and_release(client):
    # Telethon shields its own disconnect task. Keep exclusive session ownership
    # until it really finishes, even after the caller has timed out/cancelled.
    try:
        await client.disconnect()
    except Exception as exc:
        print(f"[ExtraPe] Disconnect failed ({type(exc).__name__}); restart required.")
    else:
        _session_lock.release()


async def _convert_link(client, original_link):
    await client.connect()
    return await _get_extrape_link(client, original_link)


async def _run_async(original_link):
    if not _session_lock.acquire(blocking=False):
        print("[ExtraPe] Conversion already active. Using original link.")
        return original_link
    client = None
    try:
        api_id = config._load_secret('API_ID')
        api_hash = config._load_secret('API_HASH')
        if not api_id or not api_hash:
            print("[ExtraPe] API_ID/API_HASH missing; userbot disabled.")
            return original_link
        client = TelegramClient(_session_file, api_id, api_hash)
        return await asyncio.wait_for(
            _convert_link(client, original_link), timeout=_REQUEST_TIMEOUT,
        )
    except Exception as exc:
        print(f"[ExtraPe] Conversion failed ({type(exc).__name__}). Using original link.")
        return original_link
    finally:
        if client is None:
            _session_lock.release()
        else:
            cleanup = asyncio.create_task(_disconnect_and_release(client))
            _cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(_cleanup_tasks.discard)
            try:
                await asyncio.wait_for(asyncio.shield(cleanup), _DISCONNECT_TIMEOUT)
            except asyncio.TimeoutError:
                print("[ExtraPe] Disconnect still pending; conversions remain disabled until cleanup.")


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

    future = None
    try:
        future = asyncio.run_coroutine_threadsafe(
            _run_async(original_link), loop,
        )
        return future.result(timeout=_SYNC_TIMEOUT)
    except asyncio.TimeoutError:
        if future is not None:
            future.cancel()
        print("[ExtraPe] Sync call timed out; conversion cancelled. Using original link.")
        return original_link
    except Exception as e:
        print(f"[ExtraPe] Sync link error ({type(e).__name__}). Using original link.")
        return original_link
