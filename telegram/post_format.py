"""
Telegram post formats + smaller product images.
"""
import re

TELEGRAM_PHOTO_CAPTION_MAX = 1024

FORMAT_HOT_DEAL = "hot_deal"
FORMAT_MEGA_LOOT = "mega_loot"
FORMAT_DEFAULT = "default"

FORMAT_LABELS = {
    FORMAT_HOT_DEAL: "Format 1 — HOT DEAL (Verified, rating)",
    FORMAT_MEGA_LOOT: "Format 2 — MEGA LOOT (Urgent flash style)",
    FORMAT_DEFAULT: "Use global default from Settings",
}


def shrink_product_image_url(url):
    if not url or not url.startswith("http"):
        return url
    shrunk = re.sub(r"/image/(\d{3,4})/\1/", "/image/280/280/", url, count=1)
    if shrunk == url:
        shrunk = re.sub(r"/(\d{3,4})/(\d{3,4})/", "/280/280/", url, count=1)
    return shrunk


def normalize_format(fmt):
    fmt = (fmt or FORMAT_DEFAULT).strip().lower()
    if fmt in (FORMAT_HOT_DEAL, FORMAT_MEGA_LOOT):
        return fmt
    return FORMAT_DEFAULT


def resolve_post_format(
    *,
    is_flash=False,
    category_format=None,
    default_format=FORMAT_HOT_DEAL,
    flash_format=FORMAT_MEGA_LOOT,
):
    """Pick format: flash setting > per-category > global default."""
    if is_flash:
        return normalize_format(flash_format) if flash_format != FORMAT_DEFAULT else FORMAT_MEGA_LOOT
    cat_fmt = normalize_format(category_format)
    if cat_fmt != FORMAT_DEFAULT:
        return cat_fmt
    default_fmt = normalize_format(default_format)
    return default_fmt if default_fmt != FORMAT_DEFAULT else FORMAT_HOT_DEAL


def build_deal_message(deal, affiliate_link, fmt=FORMAT_HOT_DEAL):
    """Build caption — original style, no highlights block."""
    title = deal.get("title", "Deal")
    mrp = deal.get("mrp", "")
    price = deal.get("price", "")
    discount = deal.get("discount", "")
    rating = deal.get("rating", "")
    buyers = deal.get("buyers_count", 0)

    # Rating display: "New/Unrated (0+ bought)" if no rating
    rating_str = str(rating).strip()
    if not rating_str or rating_str in ("0", "0.0", "", "N/A"):
        rating_display = f"🆕 New/Unrated ({buyers}+ bought)"
    else:
        rating_display = f"⭐ {rating_str} ({buyers}+ bought)"

    if fmt == FORMAT_MEGA_LOOT:
        return f"""🚨 <b>MEGA LOOT ALERT | PRICE DROP</b> 🚨

🛍️ {title}

💰 <b>MRP : </b> <del>{mrp}</del>
💸 <b>Loot Price : </b> {price}
📉 <b>Flat {discount}</b>
{rating_display}

👉 <b>Loot Fast (Stock ends in mins): 👇</b> 
{affiliate_link}

⚡ <b>Flash Deal:</b> Yeh deal kisi bhi waqt Sold Out ho sakti hai!"""

    return f"""🔥 <b>HOT DEAL | Verified  ✅</b>

🛍️ {title}

💰 <b>MRP : </b> <del>{mrp}</del>
💸 <b>Deal Price : </b> {price}
📉 <b>Flat {discount}</b>

👉 <b>Check price on Flipkart: 👇</b> 
{affiliate_link}

{rating_display}
⚡ Limited time deal
⏳ Stock fast finish hota hai!"""
