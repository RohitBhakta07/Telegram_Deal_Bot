# telegram/bot.py
import json
import os
import time
import requests
from config import BOT_TOKEN

from telegram.post_format import shrink_product_image_url, TELEGRAM_PHOTO_CAPTION_MAX


def _token():
    if not BOT_TOKEN:
        return None
    return BOT_TOKEN.strip()


def send_telegram_deal_post(text, chat_id, image_url=None, price_screenshot_path=None):
    """
    Deal post with photos:
    - Normal: 1 product photo + caption
    - Price screenshot ON: album with product photo + price screenshot (2 photos), caption on first
    """
    if not chat_id:
        print("❌ Error: Channel ki Chat ID pass nahi ki gayi!")
        return None

    clean_token = _token()
    if not clean_token:
        print("❌ Error: BOT_TOKEN khali hai! Dashboard mein jaakar Save karein.")
        return None

    print(f"🔍 Checking Token... (Start: {clean_token[:10]}...)")
    safe_caption = (text or "")[:TELEGRAM_PHOTO_CAPTION_MAX]

    has_product = bool(image_url and str(image_url).startswith("http"))
    has_price = bool(price_screenshot_path and os.path.isfile(price_screenshot_path))

    if has_product and has_price:
        return _send_two_photo_album(
            clean_token, chat_id, safe_caption, image_url, price_screenshot_path
        )
    if has_price:
        return _send_single_file_photo(clean_token, chat_id, safe_caption, price_screenshot_path)
    if has_product:
        return _send_single_url_photo(clean_token, chat_id, safe_caption, image_url)
    return _send_text_only(clean_token, chat_id, text)


def _send_two_photo_album(token, chat_id, caption, product_url, price_path):
    """Product image + price screenshot in one Telegram album."""
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    product_url = shrink_product_image_url(product_url)
    media = [
        {
            "type": "photo",
            "media": product_url,
            "caption": caption,
            "parse_mode": "HTML",
        },
        {"type": "photo", "media": "attach://price_shot"},
    ]
    try:
        with open(price_path, "rb") as shot_file:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "media": json.dumps(media)},
                files={"price_shot": shot_file},
                timeout=45,
            )
        if response.status_code == 200:
            print(f"✅ Telegram: 2 photos sent (product + price tag). Channel: {chat_id}")
            return response.json()
        print(f"⚠️ Album fail: {response.text}")
        print("🔄 Fallback: product photo only...")
        return _send_single_url_photo(token, chat_id, caption, product_url)
    except Exception as e:
        print(f"⚠️ Album error: {e}")
        return _send_single_url_photo(token, chat_id, caption, product_url)


def _send_single_file_photo(token, chat_id, caption, file_path):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(file_path, "rb") as img_file:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": img_file},
                timeout=30,
            )
        if response.status_code == 200:
            print(f"✅ Telegram photo sent. (Channel: {chat_id})")
            return response.json()
        print(f"⚠️ Photo upload fail: {response.text}")
    except Exception as e:
        print(f"⚠️ Photo error: {e}")
    return _send_text_only(token, chat_id, caption)


def _send_single_url_photo(token, chat_id, caption, image_url):
    image_url = shrink_product_image_url(image_url)
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": image_url,
        "caption": caption,
        "parse_mode": "HTML",
    }
    try:
        response = requests.post(url, data=payload, timeout=15)
        if response.status_code == 200:
            print(f"✅ Telegram par VIP Photo/Message chala gaya! (Channel: {chat_id})")
            return response.json()
        if response.status_code == 429:
            retry_after = 10
            try:
                retry_after = response.json().get("parameters", {}).get("retry_after", 10)
            except Exception:
                pass
            time.sleep(retry_after)
            response = requests.post(url, data=payload, timeout=15)
            if response.status_code == 200:
                return response.json()
        print(f"⚠️ Photo fail: {response.text}")
    except Exception as e:
        print(f"⚠️ Photo request error: {e}")
    return _send_text_only(token, chat_id, caption)


def _send_text_only(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    safe_text = (text or "Deal Check Karo!")[:4096]
    payload = {
        "chat_id": chat_id,
        "text": safe_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        response = requests.post(url, data=payload, timeout=15)
        if response.status_code == 200:
            print("✅ Telegram par Text Message chala gaya!")
            return response.json()
        print(f"❌ Telegram Error: {response.text}")
    except Exception as e:
        print(f"❌ Telegram Error: {e}")
    return None


# Backward compatible alias
def send_telegram_message(text, image_url=None, chat_id=None, image_path=None):
    return send_telegram_deal_post(
        text,
        chat_id,
        image_url=image_url,
        price_screenshot_path=image_path,
    )
