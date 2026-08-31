"""
Shared Flipkart product card parser — consolidates duplicated extraction logic.
"""
import re


def parse_compact_count(value):
    """Parse 1,234 / 5k / 1.2M style counters."""
    if value is None:
        return 0
    match = re.search(r'([\d,]+(?:\.\d+)?)\s*([KMB])?', str(value), re.I)
    if not match:
        return 0
    number = float(match.group(1).replace(',', ''))
    multiplier = {'K': 1_000, 'M': 1_000_000, 'B': 1_000_000_000}.get(
        (match.group(2) or '').upper(), 1)
    return int(number * multiplier)


def extract_prices_and_discount(card):
    """Extract price, MRP, and discount from a Flipkart card element.

    Returns dict with: price, mrp, discount (string), discount_int (int)
    """
    result = {
        "price": "Check Link",
        "mrp": "Check Link",
        "discount": "0",
        "discount_int": 0,
    }

    try:
        raw_card_text = card.inner_text(timeout=5000)
    except Exception:
        return result

    # Extract discount percentage
    discount_match = re.search(r'(\d{1,2})\s*%', raw_card_text)
    if discount_match:
        result["discount"] = discount_match.group(1)
        result["discount_int"] = int(discount_match.group(1))
        safe_text = re.sub(r'\d{1,2}\s*%', ' ', raw_card_text)
    else:
        safe_text = raw_card_text

    # Extract rupee prices
    prices_str = re.findall(r'₹\s*([\d,]+)', safe_text)
    valid_prices = []
    for p in prices_str:
        try:
            valid_prices.append(int(p.replace(',', '')))
        except Exception:
            pass

    if len(valid_prices) >= 2:
        valid_prices.sort(reverse=True)
        result["mrp"] = f"₹{valid_prices[0]:,}"
        result["price"] = f"₹{valid_prices[1]:,}"
    elif len(valid_prices) == 1:
        result["price"] = f"₹{valid_prices[0]:,}"

    return result


def extract_rating(card, card_text=None):
    """Extract rating and rating_count from card text.

    Returns dict with: rating (string), rating_float (float), rating_count (int)
    """
    result = {
        "rating": "0.0",
        "rating_float": 0.0,
        "rating_count": 0,
    }

    if card_text is None:
        try:
            card_text = card.inner_text(timeout=5000).split('\n')
        except Exception:
            return result

    flat_text = " ".join(card_text)
    extracted_rating = None

    # Pattern 1: Standard — "4.2 (1,234 Ratings)"
    m = re.search(r'([1-4]\.\d|5\.0)\s*(?:★|⭐)?\s*(?:\(\s*[\d,.]+\s*[KMB]?\+?\s*(?:Ratings?)?\s*\)|[\d,.]+\s*[KMB]?\+?\s+Ratings?)', flat_text, re.IGNORECASE)
    if m:
        extracted_rating = m.group(1)

    # Pattern 2: Reviews format
    if not extracted_rating:
        m = re.search(r'([1-4]\.\d|5\.0)\s*(?:★|⭐)?\s*(?:Ratings?\s*)?(?:&|and)\s*[\d,]+\s*Reviews?', flat_text, re.IGNORECASE)
        if m:
            extracted_rating = m.group(1)

    # Pattern 3: Standalone line
    if not extracted_rating:
        for line in card_text:
            clean_line = line.strip()
            m = re.search(r'^([1-4]\.\d|5\.0)\s*(?:★|⭐)?$', clean_line)
            if m:
                extracted_rating = m.group(1)
                break

    # Pattern 4: "out of 5"
    if not extracted_rating:
        m = re.search(r'([1-4]\.\d|5\.0)\s*out\s*of\s*5', flat_text, re.IGNORECASE)
        if m:
            extracted_rating = m.group(1)

    # Pattern 5: Star with rating
    if not extracted_rating:
        m = re.search(r'([1-4]\.\d|5\.0)\s*[★⭐]', flat_text)
        if m:
            extracted_rating = m.group(1)

    # Pattern 6: Bare decimal (filter out prices and percentages)
    if not extracted_rating:
        clean_for_rating = re.sub(r'₹\s*[\d,]+', '', flat_text)
        clean_for_rating = re.sub(r'\d+\s*%', '', clean_for_rating)
        m = re.search(r'(?<!\d)([3-4]\.\d|5\.0)(?!\d)', clean_for_rating)
        if m:
            extracted_rating = m.group(1)

    if extracted_rating:
        result["rating"] = extracted_rating
        try:
            result["rating_float"] = float(extracted_rating)
        except ValueError:
            pass

    # Rating count
    count_m = re.search(r'(?:[1-5]\.\d)\s*(?:★|⭐)?\s*\(\s*([\d,.]+\s*[KMB]?)\+?\s*(?:Ratings?)?\s*\)', flat_text, re.I)
    if count_m:
        result["rating_count"] = parse_compact_count(count_m.group(1))

    if result["rating_count"] == 0:
        count_m2 = re.search(r'\b([\d,.]+\s*[KMB]?)\+?\s*(?:Ratings?|Reviews?|bought)\b', flat_text, re.IGNORECASE)
        if count_m2:
            result["rating_count"] = parse_compact_count(count_m2.group(1))

    return result


def extract_image(card):
    """Extract product image URL from card."""
    try:
        images = card.locator("img").all()
        for img in images:
            src = None
            try:
                for attribute in ("src", "data-src", "data-original"):
                    src = img.get_attribute(attribute)
                    if src and src.startswith("http"):
                        break
                if not src or not src.startswith("http"):
                    srcset = img.get_attribute("srcset") or ""
                    candidates = re.findall(r'(https?://[^\s,]+)', srcset)
                    src = candidates[-1] if candidates else src
            except Exception:
                continue
            if src and src.startswith("http") and "rukminim" in src:
                return src
            elif src and src.startswith("http"):
                return src
    except Exception:
        pass
    return ""


def extract_highlights(card, card_text=None):
    """Extract product highlights from card."""
    try:
        highlight_elements = card.locator("li").all()
    except Exception:
        highlight_elements = []
    highlights_list = []
    for el in highlight_elements[:4]:
        try:
            text = el.inner_text(timeout=3000).strip()
            if text:
                highlights_list.append(f"• {text}")
        except Exception:
            pass

    if highlights_list:
        return "\n".join(highlights_list)

    # Fallback: use brand from text
    if card_text:
        brand_name = card_text[0] if len(card_text) > 0 else "Top Brand"
        if brand_name.lower() in ["ad", "sponsored", "bestseller"]:
            brand_name = card_text[1] if len(card_text) > 1 else "Top Brand"
        return f"• Brand: {brand_name}\n• 100% Original Product\n• Best Quality & Comfort"
    return "• Premium Quality\n• Best in Class"


def is_out_of_stock(card_text_full):
    """Check if product is out of stock."""
    oos_keywords = ["out of stock", "sold out", "currently unavailable",
                    "temporarily unavailable", "check address"]
    card_lower = card_text_full.lower()
    return any(kw in card_lower for kw in oos_keywords)


def qualifies(current_rating, current_discount, min_discount):
    """Check if product meets minimum rating and discount thresholds."""
    return (current_rating >= 4.0 or current_rating == 0.0) and (current_discount >= min_discount)
