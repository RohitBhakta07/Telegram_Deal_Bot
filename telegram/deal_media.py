"""Deal post images: mandatory matched product and live-price frames."""
from scraper.price_screenshot import capture_price_tag_screenshot, cleanup_screenshot
from telegram.media_frames import build_telegram_frames, cleanup_media_frames


def post_deal_message(send_deal_post_fn, chat_id, message, deal):
    """
    send_deal_post_fn = send_telegram_deal_post from telegram.bot
    Uses pre-taken screenshot from scrape if available; otherwise captures fresh.
    Caller should clean up pre-taken screenshots after all channels are done.
    """
    raw_price_path = deal.get("screenshot_path")

    # This posting mode guarantees exactly two useful photos. A fresh price
    # proof is therefore mandatory even if the legacy dashboard toggle is OFF.
    if not raw_price_path:
        link = deal.get("link") or deal.get("original_link")
        if link:
            raw_price_path = capture_price_tag_screenshot(link, deal.get("price"))
            deal["screenshot_path"] = raw_price_path

    product_frame = deal.get("product_frame_path")
    price_frame = deal.get("price_frame_path")
    if not (product_frame and price_frame):
        try:
            product_frame, price_frame = build_telegram_frames(deal, raw_price_path)
            deal["product_frame_path"] = product_frame
            deal["price_frame_path"] = price_frame
        except Exception as e:
            print(f"  [Media] Professional frame generation failed: {e}")
            return None

    if not (product_frame and price_frame):
        print("  [Media] Two valid framed photos are required; post held back.")
        return None

    print("  [Media] Sending professional 2-photo portrait album")
    return send_deal_post_fn(
        text=message,
        chat_id=chat_id,
        product_image_path=product_frame,
        price_screenshot_path=price_frame,
    )


def cleanup_deal_media(deal):
    """Clean raw proof and generated frames after all channels are finished."""
    cleanup_screenshot(deal.get("screenshot_path"))
    cleanup_media_frames(
        deal.get("product_frame_path"),
        deal.get("price_frame_path"),
    )
