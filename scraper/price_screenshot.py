"""
Capture Flipkart product-page price area as PNG screenshot.
Uses per-thread browser instances.
"""
import os
import re
import time
import uuid
from scraper.browser_pool import new_context

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "temp_screenshots")

_PRICE_BLOCK_SELECTORS = [
    "[itemprop='offers']",
    "[itemprop='price']",
    "div[class*='Nx9bqj']",
    "div[class*='_30jeq3']",
]

_FIND_PRICE_BLOCK_JS = r"""
() => {
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 80 && r.height > 15 && s.display !== 'none' &&
           s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
  };
  const hasPrice = /₹\s*[\d,]+(?:\.\d{1,2})?/;
  const similarHeading = [...document.querySelectorAll('body *')].find(el =>
    /^similar products$/i.test((el.innerText || '').trim())
  );
  const priceNodes = [...document.querySelectorAll('body *')].filter(el =>
    visible(el) && hasPrice.test((el.innerText || '').trim()) &&
    (el.innerText || '').trim().length < 300 &&
    !(similarHeading &&
      (similarHeading.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING))
  );
  let best = null;
  for (const priceNode of priceNodes) {
    let node = priceNode;
    for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
      const r = node.getBoundingClientRect();
      const text = (node.innerText || '').trim();
      if (!visible(node) || r.width > 1100 || r.height > 550 || text.length > 1200) continue;
      const offerPanel = /bank offers|apply offers|buy at ₹|cashback/i.test(text);
      const productPanel = /add to cart|buy at ₹|apply offers|delivery details|min(?:imum)? order quantity/i.test(text);
      if (offerPanel && !productPanel) continue;
      const signals = Math.min((text.match(/₹\s*[\d,]+/g) || []).length, 3) * 3 +
                      (/\d+\s*%\s*(?:off)?/i.test(text) ? 12 : 0) +
                      (/rating|review|★/i.test(text) ? 2 : 0) +
                      (productPanel ? 35 : 0) -
                      (/with bank offer\s+get it by/i.test(text) ? 20 : 0);
      const usefulSize = r.width >= 150 && r.height >= 30;
      const score = signals + (usefulSize ? 3 : 0) - depth * 0.15;
      if (usefulSize && (!best || score > best.score)) best = {el: node, score};
    }
  }
  return best ? best.el : null;
}
"""


def _ensure_dir():
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def capture_price_tag_screenshot(product_url, expected_price=None):
    """Capture price tag area as PNG. Returns file path or None."""
    if not product_url or "flipkart" not in product_url.lower():
        return None

    _ensure_dir()
    out_path = os.path.join(SCREENSHOT_DIR, f"price_{uuid.uuid4().hex[:12]}.png")

    context = new_context(device_scale_factor=2)
    try:
        print("  [Screenshot] Capturing price area...")
        # CSS is required for correct element geometry. Only fonts are skipped.
        context.route("**/*.{woff,woff2,ttf}", lambda route: route.abort())
        page = context.new_page()
        page.goto(product_url, timeout=35000, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        time.sleep(1.5)

        for close_sel in ("button:has-text('✕')", "button[aria-label='Close']", "span[role='button']:has-text('✕')"):
            try:
                button = page.locator(close_sel).first
                if button.is_visible(timeout=400):
                    button.click(timeout=1000)
                    break
            except Exception:
                continue

        captured = False
        try:
            handle = page.evaluate_handle(_FIND_PRICE_BLOCK_JS).as_element()
            if handle:
                handle.scroll_into_view_if_needed(timeout=5000)
                handle.screenshot(path=out_path, timeout=10000)
                captured = True
                print("  [Screenshot] Price block captured (semantic detection)")
        except Exception as e:
            print(f"  [Screenshot] Semantic detection failed: {e}")

        for sel in _PRICE_BLOCK_SELECTORS if not captured else ():
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=2000):
                    before_similar = loc.evaluate("""
                    el => {
                      const heading = [...document.querySelectorAll('body *')].find(node =>
                        /^similar products$/i.test((node.innerText || '').trim())
                      );
                      return !(heading &&
                        (heading.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING));
                    }
                    """)
                    box = loc.bounding_box()
                    if before_similar and box and box.get("height", 0) > 20 and box.get("width", 0) > 80:
                        loc.screenshot(path=out_path, timeout=10000)
                        captured = True
                        print(f"  [Screenshot] Price block captured ({sel[:30]}...)")
                        break
            except Exception:
                continue

        if not captured:
            try:
                expected_digits = re.sub(r"[^\d]", "", str(expected_price or ""))
                if expected_digits:
                    expected_formats = {
                        expected_digits, f"{int(expected_digits):,}",
                    }
                    alternatives = "|".join(
                        re.escape(item) for item in sorted(expected_formats, key=len, reverse=True)
                    )
                    expected_pattern = re.compile(rf"^\s*₹\s*(?:{alternatives})\s*$")
                else:
                    expected_pattern = re.compile(r"^\s*₹\s*[\d,]+\s*$")
                price = page.get_by_text(expected_pattern).first
                price.scroll_into_view_if_needed(timeout=5000)
                box = price.bounding_box()
                viewport = page.viewport_size or {"width": 1280, "height": 720}
                if not box:
                    raise RuntimeError("no visible rupee price found")
                crop_width = min(900, viewport["width"])
                x = max(0, min(box["x"] - 350, viewport["width"] - crop_width))
                y = max(0, box["y"] - 120)
                page.screenshot(
                    path=out_path,
                    clip={"x": x, "y": y,
                          "width": min(crop_width, viewport["width"] - x),
                          "height": min(360, viewport["height"] - y)},
                    timeout=10000,
                )
                captured = True
                print("  [Screenshot] Used price-centered crop fallback")
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
            context.close()
        except Exception:
            pass


def cleanup_screenshot(path):
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
