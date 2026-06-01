"""
Deal post images: product photo + optional price screenshot (both when enabled).
"""
from database import db_manager
from scraper.price_screenshot import capture_price_tag_screenshot, cleanup_screenshot


def is_price_screenshot_enabled():
    value = db_manager.get_setting("PRICE_SCREENSHOT", "OFF")
    return db_manager.normalize_price_screenshot_setting(value) == "ON"


def post_deal_message(send_deal_post_fn, chat_id, message, deal):
    """
    send_deal_post_fn = send_telegram_deal_post from telegram.bot
    ON  -> product photo + price screenshot (2 photos, 1 album)
    OFF -> product photo only
    """
    product_url = deal.get("image")
    price_path = None

    if is_price_screenshot_enabled():
        link = deal.get("link") or deal.get("original_link")
        if link:
            price_path = capture_price_tag_screenshot(link)
            if price_path:
                print("  [Screenshot] Price tag ready — sending 2 photos (product + price)")
            else:
                print("  [Screenshot] Capture failed — product photo only")

    try:
        send_deal_post_fn(
            text=message,
            chat_id=chat_id,
            image_url=product_url,
            price_screenshot_path=price_path,
        )
    finally:
        cleanup_screenshot(price_path)
