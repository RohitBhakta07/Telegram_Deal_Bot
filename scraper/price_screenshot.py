"""
Capture Flipkart product-page price area as PNG (trust screenshot for Telegram).
"""
import os
import time
import uuid
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "temp_screenshots")

# Flipkart price block selectors (layout changes — try several)
_PRICE_BLOCK_SELECTORS = [
    "div[class*='yRaY8j']",
    "div[class*='hlLfp']",
    "div[class*='pqTWk']",
    "div[class*='kAEblP']",
    "div[class*='vUq9jN']",
    "div[class*='Nx9bqj']",
    "div[class*='C7fE6x']",
]


def _ensure_dir():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def capture_price_tag_screenshot(product_url):
    """
    Open Flipkart product URL and screenshot the price tag area.
    Returns local file path or None on failure.
    """
    if not product_url or "flipkart" not in product_url.lower():
        return None

    _ensure_dir()
    out_path = os.path.join(SCREENSHOT_DIR, f"price_{uuid.uuid4().hex[:12]}.png")

    browser = None
    context = None
    try:
        print("  [Screenshot] Flipkart price area capture...")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-IN",
            )
            context.route("**/*.{css,woff2}", lambda route: route.abort())
            page = context.new_page()
            page.goto(product_url, timeout=35000, wait_until="domcontentloaded")
            time.sleep(2.5)

            captured = False
            for sel in _PRICE_BLOCK_SELECTORS:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible(timeout=2000):
                        box = loc.bounding_box()
                        if box and box.get("height", 0) > 40:
                            loc.screenshot(path=out_path, timeout=10000)
                            captured = True
                            print(f"  [Screenshot] Price block captured ({sel[:30]}...)")
                            break
                except Exception:
                    continue

            if not captured:
                # Fallback: top of product page (title + price zone)
                try:
                    page.screenshot(
                        path=out_path,
                        clip={"x": 0, "y": 60, "width": 900, "height": 480},
                        timeout=10000,
                    )
                    captured = True
                    print("  [Screenshot] Used page clip fallback (price zone)")
                except Exception as e:
                    print(f"  [Screenshot] Clip fallback failed: {e}")

            if not captured or not os.path.isfile(out_path):
                return None

            if os.path.getsize(out_path) < 500:
                try:
                    os.remove(out_path)
                except OSError:
                    pass
                return None

            return out_path
    except Exception as e:
        print(f"  [Screenshot] Error: {e}")
        if os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        return None
    finally:
        try:
            if context:
                context.close()
        except Exception:
            pass
        try:
            if browser:
                browser.close()
        except Exception:
            pass


def cleanup_screenshot(path):
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
