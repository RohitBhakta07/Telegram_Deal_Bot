"""
Flipkart scraper — uses per-thread browser instances.
"""
import time
import random
import re
import json
import html as html_lib
import queue as queue_module
from analyzer.deal_selector import score_deal
from analyzer.trends import build_flipkart_url
from scraper.browser_pool import new_context
from scraper.price_screenshot import capture_price_tag_screenshot
from scraper.parser import (
    extract_prices_and_discount,
    extract_rating,
    extract_image,
    extract_highlights,
    is_out_of_stock,
    qualifies,
    parse_compact_count,
)


def _process_card(card, min_discount, checked_links, skip_link_fn=None):
    """Process a single product card — shared logic for all scrapers."""
    try:
        card_text_full = card.inner_text(timeout=5000).lower()
    except Exception:
        return None

    if is_out_of_stock(card_text_full):
        return None

    # Link
    link_element = card.locator("a").first
    href = link_element.get_attribute('href')
    if not href:
        return None
    full_link = href if href.startswith("http") else f"https://www.flipkart.com{href}"

    if full_link in checked_links:
        return None
    if skip_link_fn and skip_link_fn(full_link):
        checked_links.add(full_link)
        return None

    card_text = card.inner_text(timeout=5000).split('\n')

    # Title
    title = "Trending Product"
    for t_line in card_text:
        clean_line = t_line.strip().lower()
        if clean_line and clean_line not in ["ad", "sponsored", "bestseller"]:
            title = t_line.strip()
            break

    # Image
    image_url = extract_image(card)

    # Prices
    price_data = extract_prices_and_discount(card)

    # Rating
    rating_data = extract_rating(card, card_text)

    # Highlights
    highlights = extract_highlights(card, card_text)

    deal_info = {
        "title": title[:50] + "...",
        "link": full_link,
        "image": image_url,
        "price": price_data["price"],
        "mrp": price_data["mrp"],
        "discount": price_data["discount"],
        "rating": rating_data["rating"],
        "rating_count": rating_data["rating_count"],
        "highlights": highlights,
    }

    current_rating = rating_data["rating_float"]
    current_discount = price_data["discount_int"]

    if qualifies(current_rating, current_discount, min_discount):
        deal_info["rating_count"] = rating_data["rating_count"]
        if current_rating >= 4.0:
            deal_info["rating"] = f"{current_rating}★ ({rating_data['rating_count']}+ Ratings)"
        deal_info["discount"] = f"{current_discount}% Off"
        return deal_info

    return None


def scrape_search_page(search_page, min_discount, checked_links, skip_link_fn=None):
    """Extract qualifying deals from a search results page."""
    raw_deals = []
    try:
        search_page.wait_for_selector("div[data-id]", timeout=15000)
    except Exception:
        return raw_deals

    try:
        search_page.evaluate("window.scrollBy(0, 1000)")
        time.sleep(2)
    except Exception:
        pass

    try:
        product_cards = search_page.locator("div[data-id]").all()
    except Exception:
        return raw_deals

    for card in product_cards[:8]:
        try:
            deal = _process_card(card, min_discount, checked_links, skip_link_fn)
            if deal:
                raw_deals.append(deal)
        except Exception:
            continue

    return raw_deals


def get_flipkart_deals(search_url, required_discount=60):
    """Original scraper."""
    deals = []
    context = new_context()
    try:
        context.route("**/*.{png,jpg,jpeg,webp,svg,gif,css,woff2}",
                      lambda route: route.abort())
        page = context.new_page()

        max_retries = 3
        page_loaded = False
        for attempt in range(max_retries):
            try:
                page.goto(search_url, timeout=40000, wait_until="domcontentloaded")
                page_loaded = True
                break
            except Exception as e:
                print(f"Page load warning (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(3)
                    try:
                        page.close()
                    except Exception:
                        pass
                    page = context.new_page()

        if not page_loaded:
            print("Failed to load Flipkart page after retries.")
            return deals

        raw_deals = scrape_search_page(page, required_discount, set())

        for d in raw_deals:
            try:
                current_rating = float(d.get("rating", "0").split("★")[0])
            except (ValueError, IndexError):
                current_rating = 0.0
            try:
                current_discount = int(d["discount"].replace("% Off", ""))
            except (ValueError, AttributeError):
                current_discount = 0
            if qualifies(current_rating, current_discount, required_discount):
                deals.append(d)

        print("\nScraping Complete!")
    except Exception as e:
        print(f"SCRAPER CRITICAL ERROR: {e}")
    finally:
        try:
            context.close()
        except Exception:
            pass

    return deals


def _walk_for_product_schema(value):
    if isinstance(value, dict):
        schema_type = value.get("@type")
        if schema_type == "Product" or (isinstance(schema_type, list) and "Product" in schema_type):
            return value
        for child in value.values():
            found = _walk_for_product_schema(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _walk_for_product_schema(child)
            if found:
                return found
    return None


def _extract_product_schema(html_content):
    """Return the Product JSON-LD object, ignoring unrelated offer/review JSON."""
    scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_content or "", re.I | re.S,
    )
    for raw in scripts:
        try:
            parsed = json.loads(html_lib.unescape(raw).strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        found = _walk_for_product_schema(parsed)
        if found:
            return found
    return {}


def _collapse_adjacent_word_repeats(value):
    """Remove an immediately repeated 3+ word phrase from marketplace titles."""
    words = re.sub(r"\s+", " ", str(value or "")).strip().split(" ")
    changed = True
    while changed:
        changed = False
        for width in range(min(12, len(words) // 2), 2, -1):
            for start in range(0, len(words) - width * 2 + 1):
                first = [word.casefold() for word in words[start:start + width]]
                second = [word.casefold() for word in words[start + width:start + width * 2]]
                if first == second:
                    del words[start + width:start + width * 2]
                    changed = True
                    break
            if changed:
                break
    return " ".join(words)


def _extract_primary_price_context(page_text, current_price):
    """Return (MRP, discount) tied to the product's current visible price."""
    try:
        current_value = int(re.sub(r"[^\d]", "", str(current_price)))
    except (TypeError, ValueError):
        return None, None
    if current_value <= 0:
        return None, None

    compact = re.sub(r"\s+", " ", page_text or "")
    current_formats = sorted(
        {str(current_value), f"{current_value:,}"}, key=len, reverse=True,
    )
    current_pattern = "(?:" + "|".join(re.escape(item) for item in current_formats) + ")"
    pattern = re.compile(
        r"(?P<discount>\d{1,2})\s*%\s*(?:off\s*)?"
        r"(?:₹\s*)?(?P<mrp>[\d,]+)\s*₹\s*"
        + current_pattern
        + r"(?!\d)",
        re.I,
    )
    match = pattern.search(compact)
    if not match:
        return None, None
    try:
        mrp_value = int(match.group("mrp").replace(",", ""))
        discount_value = int(match.group("discount"))
    except (TypeError, ValueError):
        return None, None
    if mrp_value <= current_value or not 1 <= discount_value <= 99:
        return None, None
    return f"₹{mrp_value:,}", f"{discount_value}% Off"


def scrape_single_product(product_url):
    """Single product page scraper."""
    deal_info = None
    context = new_context()
    try:
        print("[INSTANT POST] Scraping product page...")
        context.route("**/*.{css,woff2}", lambda route: route.abort())
        page = context.new_page()

        try:
            page.goto(product_url, timeout=40000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[INSTANT POST] Page load fail: {e}")
            return None

        time.sleep(3)

        try:
            html_content = page.content()
            page_text = page.inner_text("body", timeout=5000)
        except Exception:
            html_content = ""
            page_text = ""

        schema = _extract_product_schema(html_content)

        # Product schema is authoritative; OpenGraph is fallback.
        title = "Flipkart Product"
        if schema.get("name"):
            title = str(schema["name"]).strip()
        m_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_content)
        if title == "Flipkart Product" and m_title:
            title = m_title.group(1).replace("Buy ", "").split(" at ")[0].strip()
        title = _collapse_adjacent_word_repeats(title)

        # Image from meta
        image_url = ""
        schema_image = schema.get("image")
        if isinstance(schema_image, list) and schema_image:
            image_url = str(schema_image[0])
        elif isinstance(schema_image, str):
            image_url = schema_image
        m_img = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_content)
        if not image_url and m_img:
            image_url = m_img.group(1)

        # Only the Product.offers price is accepted.
        price = "Check Link"
        offers = schema.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict) and offers.get("price") is not None:
            try:
                price_val = int(float(str(offers["price"]).replace(",", "")))
                price = f"₹{price_val:,}"
            except (TypeError, ValueError):
                pass

        # Bind MRP and discount to the same visible block as the current price.
        # Never use the page-wide maximum; Flipkart appends similar products.
        primary_mrp, primary_discount = _extract_primary_price_context(page_text, price)
        mrp = primary_mrp or price

        # Rating
        rating = "New/Unrated"
        aggregate = schema.get("aggregateRating") or {}
        if isinstance(aggregate, dict) and aggregate.get("ratingValue") is not None:
            rating_value = str(aggregate["ratingValue"])
            rating_count = parse_compact_count(aggregate.get("ratingCount"))
            rating = f"{rating_value}★ ({rating_count:,} Ratings)" if rating_count else f"{rating_value}★"
        else:
            m_rating2 = re.search(r'([1-4]\.\d|5\.0)\s*(?:★|⭐)', page_text)
            if m_rating2:
                rating = f"{m_rating2.group(1)}★"

        # Discount
        discount_str = primary_discount or "0% Off"
        if discount_str == "0% Off" and price != "Check Link" and mrp != "Check Link" and price != mrp:
            try:
                p_val = int(price.replace('₹', '').replace(',', ''))
                m_val = int(mrp.replace('₹', '').replace(',', ''))
                calc_disc = int(((m_val - p_val) / m_val) * 100)
                if calc_disc > 0:
                    discount_str = f"{calc_disc}% Off"
            except Exception:
                pass
        if discount_str == "0% Off":
            discount_str = "Mega Deal"

        # Highlights
        highlights = "• Premium Quality\n• Best in Class\n• Verified Product"
        try:
            page_lines = page_text.split('\n')
            for i, line in enumerate(page_lines):
                if "Highlights" in line and i + 1 < len(page_lines):
                    hts = []
                    for j in range(1, 5):
                        if i + j < len(page_lines) and len(page_lines[i + j].strip()) > 3:
                            hts.append(f"• {page_lines[i + j].strip()}")
                    if hts:
                        highlights = "\n".join(hts)
                    break
        except Exception:
            pass

        deal_info = {
            "title": title[:100] + ("..." if len(title) > 100 else ""),
            "link": product_url,
            "image": image_url,
            "price": price,
            "mrp": mrp,
            "discount": discount_str,
            "rating": rating,
            "highlights": highlights,
        }
        print(f"[INSTANT POST] Product scraped: {title[:40]}...")
    except Exception as e:
        print(f"[INSTANT POST] Error: {e}")
    finally:
        try:
            context.close()
        except Exception:
            pass

    return deal_info


def _extract_aggregate_rating(html_content, page_text=""):
    """Extract product aggregate rating, ignoring review/score histograms."""
    rating = 0.0
    count = 0
    aggregate = re.search(
        r'"aggregateRating"\s*:\s*\{([^{}]{1,800})\}',
        html_content or "", re.I,
    )
    if aggregate:
        block = aggregate.group(1)
        value_match = re.search(r'"ratingValue"\s*:\s*"?([1-5](?:\.\d+)?)"?', block, re.I)
        count_match = re.search(r'"ratingCount"\s*:\s*"?([\d,.]+\s*[KMB]?)"?', block, re.I)
        if value_match:
            rating = float(value_match.group(1))
        if count_match:
            count = parse_compact_count(count_match.group(1))

    if not rating:
        visible = re.search(
            r'(?<!\d)([1-4]\.\d|5\.0)\s*(?:★|⭐|out\s+of\s+5)',
            page_text or "", re.I,
        )
        if visible:
            rating = float(visible.group(1))
    return rating, count


def deep_check_product_data(product_url, context):
    """Visit product page and return both rating value and rating/buyer count."""
    result = {
        "rating": 0.0, "rating_count": 0, "image": "", "title": "",
        "price": "", "mrp": "", "discount": "",
    }
    page = None
    try:
        page = context.new_page()
        time.sleep(random.uniform(2, 4))
        page.goto(product_url, timeout=25000, wait_until="domcontentloaded")
        time.sleep(2)

        try:
            html_content = page.content()
        except Exception:
            html_content = ""
        try:
            page_text = page.inner_text("body", timeout=5000)
        except Exception:
            page_text = ""

        schema = _extract_product_schema(html_content)
        if schema.get("name"):
            result["title"] = _collapse_adjacent_word_repeats(schema["name"])

        schema_image = schema.get("image")
        if isinstance(schema_image, list) and schema_image:
            result["image"] = str(schema_image[0])
        elif isinstance(schema_image, str):
            result["image"] = schema_image

        offers = schema.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        if isinstance(offers, dict) and offers.get("price") is not None:
            try:
                price_value = int(float(str(offers["price"]).replace(",", "")))
                result["price"] = f"₹{price_value:,}"
                result["mrp"], result["discount"] = _extract_primary_price_context(
                    page_text, result["price"],
                )
                result["mrp"] = result["mrp"] or result["price"]
            except (TypeError, ValueError):
                pass

        image_match = re.search(
            r'<meta\s+(?:property|name)=["\']og:image["\']\s+content=["\']([^"\']+)',
            html_content, re.I,
        )
        if not image_match:
            image_match = re.search(
                r'<meta\s+content=["\']([^"\']+)["\']\s+(?:property|name)=["\']og:image["\']',
                html_content, re.I,
            )
        if image_match and not result["image"]:
            result["image"] = image_match.group(1).replace("&amp;", "&")

        aggregate = schema.get("aggregateRating") or {}
        if isinstance(aggregate, dict) and aggregate.get("ratingValue") is not None:
            try:
                result["rating"] = float(aggregate["ratingValue"])
                result["rating_count"] = parse_compact_count(aggregate.get("ratingCount"))
            except (TypeError, ValueError):
                pass
        if not result["rating"]:
            result["rating"], result["rating_count"] = _extract_aggregate_rating(
                html_content, page_text,
            )

        # Method 2: "X+ bought"
        m = re.search(r'(\d+(?:\.\d+)?)\s*(K)?\+?\s*bought', page_text, re.IGNORECASE)
        if m and not result["rating_count"]:
            val = float(m.group(1))
            if m.group(2) and m.group(2).upper() == 'K':
                val *= 1000
            result["rating_count"] = int(val)

        # Method 3: Ratings count
        m = re.search(r'([\d,.]+\s*[KMB]?)\+?\s*Ratings?', page_text, re.IGNORECASE)
        if m and not result["rating_count"]:
            result["rating_count"] = parse_compact_count(m.group(1))

        return result
    except Exception as e:
        print(f"Deep check error: {e}")
        return result
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def scrape_keyword_full(keyword, settings, deal_queue, skip_link_fn=None):
    """
    Full keyword scraper: search → score → deep check → push to queue.
    """
    from analyzer.deal_selector import score_deal

    min_discount = settings.get('min_discount', 60)
    min_buyers = settings.get('min_buyers_count', 1000)
    max_pages = settings.get('max_pages', 3)
    priority_weight = settings.get('priority_weight', 2)
    allow_missing = settings.get('allow_missing_buyers', False)
    do_screenshot = settings.get('price_screenshot_on', False)

    qualified_deals = []
    checked_links = set()

    context = new_context()
    try:
        context.route("**/*.{png,jpg,jpeg,webp,svg,gif,css,woff2}",
                      lambda route: route.abort())

        for page_num in range(1, max_pages + 1):
            if len(qualified_deals) >= 2:
                print(f"  [{keyword}] 2 deals found, moving on!")
                break

            print(f"\n  [{keyword}] Page {page_num}/{max_pages}...")
            search_url = build_flipkart_url(keyword, min_discount=min_discount, page=page_num)

            search_page = None
            raw_deals = []

            try:
                search_page = context.new_page()
                search_page.goto(search_url, timeout=40000, wait_until="domcontentloaded")
                raw_deals = scrape_search_page(search_page, min_discount,
                                                checked_links, skip_link_fn)
            except Exception as e:
                print(f"  [{keyword}] Page {page_num} error: {e}")
            finally:
                if search_page:
                    try:
                        search_page.close()
                    except Exception:
                        pass

            if not raw_deals:
                continue

            # Score and filter
            scored = []
            for d in raw_deals:
                s = score_deal(d, required_discount=min_discount,
                               category_priority_weight=priority_weight)
                if not s['reject_reason']:
                    scored.append({'deal': d, 'score': s})

            scored.sort(key=lambda x: x['score']['total'], reverse=True)
            top_deals = scored[:3]

            if not top_deals:
                continue

            # Stage 2: Deep check
            for item in top_deals:
                if len(qualified_deals) >= 2:
                    break
                deal = item['deal']
                link = deal.get('link', '')
                if link in checked_links:
                    continue
                checked_links.add(link)

                product_data = deep_check_product_data(link, context)
                buyers = product_data["rating_count"]
                deal['buyers_count'] = buyers

                # Product-page data is more reliable than a compact search card.
                if product_data["rating"]:
                    rating_value = product_data["rating"]
                    deal['rating'] = f"{rating_value:g}★ ({buyers:,} Ratings)" if buyers else f"{rating_value:g}★"
                if product_data["image"]:
                    deal['image'] = product_data["image"]
                if product_data["title"]:
                    deal['title'] = product_data["title"][:100] + (
                        "..." if len(product_data["title"]) > 100 else ""
                    )
                if product_data["price"]:
                    deal['price'] = product_data["price"]
                if product_data["mrp"]:
                    deal['mrp'] = product_data["mrp"]
                if product_data["discount"]:
                    deal['discount'] = product_data["discount"]

                # Re-score after enrichment so a low product-page rating cannot
                # slip through merely because the search card looked unrated.
                enriched_score = score_deal(
                    deal, required_discount=min_discount,
                    category_priority_weight=priority_weight,
                )
                if enriched_score['reject_reason']:
                    continue
                item['score'] = enriched_score

                if buyers >= min_buyers or (buyers == 0 and allow_missing):
                    screenshot_path = None
                    if do_screenshot:
                        try:
                            screenshot_path = capture_price_tag_screenshot(
                                link, deal.get("price"),
                            )
                        except Exception:
                            pass
                    deal['screenshot_path'] = screenshot_path
                    qualified_deals.append(item)

            if page_num < max_pages and len(qualified_deals) < 2:
                time.sleep(random.uniform(3, 6))

        if not qualified_deals:
            print(f"  [{keyword}] No qualifying deals found.")
            return 0

        print(f"\n  [{keyword}] {len(qualified_deals)} deals qualified!")

        for item in qualified_deals:
            deal = item['deal']
            score = item['score']
            if score['total'] >= 85:
                priority = 2
            elif score['total'] >= 70:
                priority = 3
            else:
                priority = 5

            queue_item = {
                'deal': deal,
                'score': score,
                'keyword': keyword,
                'category': settings.get('category_name', 'GENERAL'),
                'post_format': settings.get('post_format', 'hot_deal'),
                'priority': priority,
                'timestamp': time.time(),
            }
            deal_queue.put((priority, time.time(), queue_item))
            print(f"  [{keyword}] Queued: {deal.get('title','')[:30]}... (Priority={priority})")

    except Exception as e:
        print(f"  [{keyword}] CRITICAL ERROR: {e}")
    finally:
        try:
            context.close()
        except Exception:
            pass

    return len(qualified_deals)
