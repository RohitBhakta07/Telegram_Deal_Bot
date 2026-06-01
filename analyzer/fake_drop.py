"""
Fake / inflated discount checks — like a human would sanity-check MRP vs price.
"""
import re


def _parse_rupees(value):
    if value is None:
        return 0
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else 0


def _parse_discount_percent(discount_percent):
    try:
        return int(
            str(discount_percent)
            .replace("%", "")
            .replace("off", "")
            .replace("Off", "")
            .replace("MEGA DROP", "")
            .strip()
            .split()[0]
        )
    except (ValueError, IndexError):
        return 0


def get_fake_drop_reason(title, price, mrp, discount_percent):
    """
    Returns (is_genuine: bool, reason: str|None).
    """
    title_lower = str(title or "").lower()
    clean_disc = _parse_discount_percent(discount_percent)
    clean_mrp = _parse_rupees(mrp)
    clean_price = _parse_rupees(price)

    if clean_mrp <= 0 or clean_price <= 0:
        return False, "missing MRP or price"

    if clean_price >= clean_mrp:
        return False, "price not below MRP (no real discount)"

    actual_disc = round((1 - clean_price / clean_mrp) * 100)
    # Claimed discount vs real math — allow 8% slack for rounding
    if clean_disc > 0 and abs(actual_disc - clean_disc) > 12:
        return False, f"discount tag {clean_disc}% but math says ~{actual_disc}%"

    if clean_disc >= 92 and clean_mrp > 5000:
        return False, "suspicious 90%+ off on high MRP (possible fake MRP)"

    if clean_mrp < 150 and clean_disc >= 80:
        return False, "cheap item with inflated % — low real savings"

    spam_words = ("refurbished", "damaged box", "without warranty", "non-retail pack")
    for w in spam_words:
        if w in title_lower:
            return False, f"title flag: {w}"

    if len(title_lower.strip()) < 8:
        return False, "title too short / unclear product"

    return True, None


def is_genuine_deal(title, price, mrp, discount_percent):
    ok, _ = get_fake_drop_reason(title, price, mrp, discount_percent)
    return ok
