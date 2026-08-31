"""Create matching portrait media cards for Telegram two-photo albums."""
from datetime import datetime
from io import BytesIO
import os
import re
import uuid
from urllib.parse import urlsplit

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME_DIR = os.path.join(BASE_DIR, "temp_media_frames")
FRAME_SIZE = (1080, 1350)

FONT_REGULAR = r"C:\Windows\Fonts\segoeui.ttf"
FONT_BOLD = r"C:\Windows\Fonts\segoeuib.ttf"

BG = "#F4F7FB"
NAVY = "#111827"
SLATE = "#475569"
MUTED = "#7C8AA0"
BLUE = "#2874F0"
GREEN = "#0B9B68"
PALE_BLUE = "#EAF2FF"
WHITE = "#FFFFFF"
BORDER = "#DDE5F0"


def _font(size, bold=False):
    path = FONT_BOLD if bold else FONT_REGULAR
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def _ensure_dir():
    os.makedirs(FRAME_DIR, exist_ok=True)


def _download_product_image(url):
    if not url or not str(url).startswith("http"):
        return None
    # Flipkart OG images are often 300x300. Request a sharper CDN rendition.
    url = re.sub(r"/image/\d{2,4}/\d{2,4}/", "/image/832/832/", str(url), count=1)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.flipkart.com/"}
    content = None
    try:
        response = requests.get(url, headers=headers, timeout=25)
        response.raise_for_status()
        content = response.content
    except requests.RequestException:
        host = (urlsplit(url).hostname or "").lower()
        valid_flipkart_cdn = (
            host.endswith(".flixcart.com")
            and host.startswith(("rukminim", "rukmini"))
        )
        if not valid_flipkart_cdn:
            raise
        # Constrained fallback for Flipkart's public image CDN only. The bytes
        # are decoded as an image below and never executed.
        from scraper.browser_pool import new_context
        context = new_context(ignore_https_errors=True)
        try:
            response = context.request.get(url, headers=headers, timeout=25000)
            if not response.ok:
                raise ValueError(f"image CDN returned HTTP {response.status}")
            content = response.body()
        finally:
            context.close()
    if not content:
        raise ValueError("empty product image response")
    if len(content) > 12 * 1024 * 1024:
        raise ValueError("product image exceeds 12 MB")
    image = Image.open(BytesIO(content))
    image = ImageOps.exif_transpose(image).convert("RGB")
    return image


def _shadow_card(canvas, box, radius=34, shadow=16):
    x1, y1, x2, y2 = box
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.rounded_rectangle((x1, y1 + 8, x2, y2 + 8), radius=radius, fill=(22, 38, 65, 35))
    layer = layer.filter(ImageFilter.GaussianBlur(shadow))
    canvas.alpha_composite(layer)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=radius, fill=WHITE, outline=BORDER, width=2)


def _rounded_paste(canvas, image, box, radius=26, background=WHITE):
    x1, y1, x2, y2 = box
    target_size = (x2 - x1, y2 - y1)
    panel = Image.new("RGB", target_size, background)
    contained = ImageOps.contain(image.convert("RGB"), (target_size[0] - 30, target_size[1] - 30), Image.Resampling.LANCZOS)
    px = (target_size[0] - contained.width) // 2
    py = (target_size[1] - contained.height) // 2
    panel.paste(contained, (px, py))
    mask = Image.new("L", target_size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *target_size), radius=radius, fill=255)
    canvas.paste(panel.convert("RGBA"), (x1, y1), mask)


def _fit_crop(image, size):
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _draw_wrapped(draw, text, xy, max_width, font, fill, max_lines=2, line_gap=8):
    words = re.sub(r"\s+", " ", str(text or "")).strip().split(" ")
    lines = []
    current = ""
    truncated = False
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) == max_lines:
                truncated = True
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if truncated and len(lines) == max_lines:
        while lines[-1] and draw.textbbox((0, 0), lines[-1] + "...", font=font)[2] > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] = lines[-1].rstrip() + "..."
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=font)
        y = bbox[3] + line_gap
    return y


def _header(draw, label):
    draw.rounded_rectangle((58, 48, 244, 100), radius=26, fill=BLUE)
    draw.text((82, 61), "DEAL HUNTER", font=_font(23, True), fill=WHITE)
    bbox = draw.textbbox((0, 0), label, font=_font(24, True))
    draw.text((1022 - bbox[2], 62), label, font=_font(24, True), fill=SLATE)


def _base_canvas():
    canvas = Image.new("RGBA", FRAME_SIZE, BG)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((810, -170, 1170, 190), fill="#E3EEFF")
    draw.ellipse((-170, 1110, 190, 1470), fill="#E4F7EF")
    return canvas, draw


def _build_product_frame(deal, product_image, output_path):
    canvas, draw = _base_canvas()
    _header(draw, "PRODUCT VIEW")
    _shadow_card(canvas, (58, 132, 1022, 1058), radius=42)
    _rounded_paste(canvas, product_image, (120, 185, 960, 1005), radius=28, background=WHITE)

    draw.rounded_rectangle((58, 1092, 1022, 1298), radius=34, fill=WHITE, outline=BORDER, width=2)
    draw.text((86, 1120), "ACTUAL PRODUCT PHOTO", font=_font(21, True), fill=BLUE)
    _draw_wrapped(
        draw, deal.get("title", "Flipkart Product"), (86, 1160), 880,
        _font(34, True), NAVY, max_lines=2, line_gap=6,
    )
    draw.text((86, 1260), "Swipe for live price proof", font=_font(20), fill=MUTED)
    canvas.convert("RGB").save(output_path, "JPEG", quality=93, optimize=True)


def _build_price_frame(deal, screenshot, product_image, output_path):
    canvas, draw = _base_canvas()
    _header(draw, "LIVE PRICE PROOF")

    _shadow_card(canvas, (58, 132, 1022, 538), radius=38)
    draw.text((86, 166), "FLIPKART PAGE SNAPSHOT", font=_font(21, True), fill=BLUE)
    # Preserve the real page crop and present wide price blocks as a deliberate
    # receipt-style strip, instead of stretching or cutting their text.
    _rounded_paste(canvas, screenshot, (82, 214, 998, 500), radius=24, background="#F8FAFC")
    draw.rounded_rectangle((82, 214, 998, 500), radius=24, outline=BORDER, width=2)

    _shadow_card(canvas, (58, 578, 1022, 1298), radius=38)
    thumb = ImageOps.contain(product_image.convert("RGB"), (210, 210), Image.Resampling.LANCZOS)
    thumb_box = Image.new("RGB", (230, 230), WHITE)
    thumb_box.paste(thumb, ((230 - thumb.width) // 2, (230 - thumb.height) // 2))
    _rounded_paste(canvas, thumb_box, (86, 610, 316, 840), radius=26)

    draw.text((350, 612), "VERIFIED DEAL PRICE", font=_font(22, True), fill=BLUE)
    price = str(deal.get("price") or "Check Link")
    draw.text((350, 652), price, font=_font(72, True), fill=NAVY)

    mrp = str(deal.get("mrp") or "")
    if mrp:
        draw.text((354, 742), "MRP", font=_font(20, True), fill=MUTED)
        mrp_x = 420
        draw.text((mrp_x, 734), mrp, font=_font(31), fill=MUTED)
        mrp_box = draw.textbbox((mrp_x, 734), mrp, font=_font(31))
        draw.line((mrp_box[0], (mrp_box[1] + mrp_box[3]) // 2, mrp_box[2], (mrp_box[1] + mrp_box[3]) // 2), fill=MUTED, width=3)

    discount = str(deal.get("discount") or "Deal")
    discount_box = draw.textbbox((0, 0), discount, font=_font(27, True))
    pill_w = discount_box[2] + 48
    draw.rounded_rectangle((350, 790, 350 + pill_w, 848), radius=29, fill="#E4F7EF")
    draw.text((374, 801), discount, font=_font(27, True), fill=GREEN)

    _draw_wrapped(
        draw, deal.get("title", "Flipkart Product"), (86, 876), 900,
        _font(31, True), NAVY, max_lines=2, line_gap=5,
    )
    raw_rating = str(deal.get("rating") or "")
    rating_match = re.search(r'([1-5](?:\.\d+)?)', raw_rating)
    rating = f"{rating_match.group(1)} / 5" if rating_match else "New / Unrated"
    draw.rounded_rectangle((86, 1008, 470, 1063), radius=27, fill=PALE_BLUE)
    draw.text((112, 1018), f"Rating  {rating}", font=_font(23, True), fill=BLUE)
    verified = datetime.now().strftime("Verified %d %b, %I:%M %p")
    bbox = draw.textbbox((0, 0), verified, font=_font(20))
    draw.text((986 - bbox[2], 1022), verified, font=_font(20), fill=MUTED)
    draw.line((86, 1110, 986, 1110), fill=BORDER, width=2)
    draw.text((86, 1140), "PRICE NOTE", font=_font(19, True), fill=BLUE)
    draw.text((86, 1176), "Live price can change on Flipkart. Final price is shown on checkout.", font=_font(18), fill=MUTED)
    canvas.convert("RGB").save(output_path, "JPEG", quality=93, optimize=True)


def build_telegram_frames(deal, price_screenshot_path):
    """Return (product_frame, price_frame), or (None, None) on invalid inputs."""
    if not price_screenshot_path or not os.path.isfile(price_screenshot_path):
        return None, None
    product_image = _download_product_image(deal.get("image"))
    if product_image is None:
        return None, None
    screenshot = Image.open(price_screenshot_path)
    screenshot = ImageOps.exif_transpose(screenshot).convert("RGB")

    _ensure_dir()
    token = uuid.uuid4().hex[:12]
    product_path = os.path.join(FRAME_DIR, f"product_{token}.jpg")
    price_path = os.path.join(FRAME_DIR, f"price_{token}.jpg")
    try:
        _build_product_frame(deal, product_image, product_path)
        _build_price_frame(deal, screenshot, product_image, price_path)
        return product_path, price_path
    except Exception:
        cleanup_media_frames(product_path, price_path)
        raise


def cleanup_media_frames(*paths):
    for path in paths:
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
