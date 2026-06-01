"""
Human-like deal picker: scores, compares, and explains why one deal wins.
"""
import re
from analyzer.fake_drop import is_genuine_deal, get_fake_drop_reason

# Suspicious titles a real deal hunter would avoid
_TITLE_RED_FLAGS = (
    "refurbished", "damaged", "without box", "non-retail", "duplicate",
    "combo pack of 1", "only cover", "replacement only", "defective",
)


def _parse_rupees(value):
    if value is None:
        return 0
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else 0


def _parse_discount(value):
    if value is None:
        return 0
    m = re.search(r"(\d+)", str(value))
    return int(m.group(1)) if m else 0


def _parse_rating(value):
    if not value:
        return 0.0
    text = str(value).lower()
    if "bestseller" in text or "new launch" in text or "🌟" in text:
        return 0.0
    m = re.search(r"([0-5](?:\.\d)?)", text)
    return float(m.group(1)) if m else 0.0


def _title_red_flags(title):
    t = (title or "").lower()
    return [w for w in _TITLE_RED_FLAGS if w in t]


def score_deal(deal, required_discount=60, category_priority_weight=2):
    """
    Score 0–100 like a human deal hunter.
    Returns dict with total, breakdown, verdict, reject_reason (if any).
    """
    title = deal.get("title", "")
    discount = _parse_discount(deal.get("discount"))
    rating = _parse_rating(deal.get("rating"))
    mrp = _parse_rupees(deal.get("mrp"))
    price = _parse_rupees(deal.get("price"))
    savings = max(0, mrp - price) if mrp and price else 0

    reject_reason = None
    flags = _title_red_flags(title)
    if flags:
        reject_reason = f"title looks risky ({flags[0]})"

    genuine, fake_reason = get_fake_drop_reason(
        title, deal.get("price"), deal.get("mrp"), deal.get("discount")
    )
    if not genuine:
        reject_reason = fake_reason or "failed trust check"

    if discount < required_discount:
        reject_reason = reject_reason or f"discount {discount}% below min {required_discount}%"

    # --- Component scores ---
    # Discount: beating minimum by a lot feels like a real loot
    if discount >= required_discount + 25:
        discount_pts = 100
    elif discount >= required_discount + 10:
        discount_pts = 85
    elif discount >= required_discount:
        discount_pts = 70
    else:
        discount_pts = max(0, int(50 * discount / max(required_discount, 1)))

    # Rating: humans trust 4.2+ more than bare minimum 4.0
    if rating >= 4.5:
        rating_pts = 100
        rating_note = f"excellent {rating} star"
    elif rating >= 4.2:
        rating_pts = 90
        rating_note = f"strong {rating} star"
    elif rating >= 4.0:
        rating_pts = 75
        rating_note = f"okay {rating} star"
    elif rating == 0.0 and discount >= required_discount + 15:
        rating_pts = 55
        rating_note = "unrated but huge drop — risky, worth a look"
    elif rating == 0.0:
        rating_pts = 40
        rating_note = "no rating — only if discount is insane"
    else:
        rating_pts = 20
        rating_note = f"weak {rating} star"
        if rating < 4.0 and rating > 0:
            reject_reason = reject_reason or f"rating {rating} too low for channel"

    # Savings: ₹500 off on ₹600 item beats 70% off on ₹99 junk
    if savings >= 3000:
        savings_pts = 100
    elif savings >= 1500:
        savings_pts = 85
    elif savings >= 500:
        savings_pts = 70
    elif savings >= 200:
        savings_pts = 50
    else:
        savings_pts = 30

    trust_pts = 100 if genuine else 0

    # Category priority from dashboard (HIGH=4, MED=2, LOW=1) → small boost
    priority_boost = min(15, (category_priority_weight - 1) * 4)

    if reject_reason:
        total = 0
    else:
        total = round(
            discount_pts * 0.35
            + rating_pts * 0.30
            + savings_pts * 0.20
            + trust_pts * 0.10
            + priority_boost
        )
        total = min(100, total)

    verdict_parts = []
    if total >= 85:
        verdict_parts.append("Channel-worthy loot")
    elif total >= 70:
        verdict_parts.append("Solid deal worth posting")
    elif total >= 55:
        verdict_parts.append("Decent - post if nothing better")
    else:
        verdict_parts.append("Meh - would skip in manual review")

    if discount >= required_discount + 20:
        verdict_parts.append(f"deep {discount}% cut")
    if savings >= 1000:
        verdict_parts.append(f"you save ~Rs.{savings:,}")

    verdict = f"{verdict_parts[0]}; {rating_note}"
    if len(verdict_parts) > 1:
        verdict += f"; {', '.join(verdict_parts[1:3])}"

    return {
        "total": total,
        "discount_pts": discount_pts,
        "rating_pts": rating_pts,
        "savings_pts": savings_pts,
        "trust_pts": trust_pts,
        "priority_boost": priority_boost,
        "savings_rupees": savings,
        "discount": discount,
        "rating": rating,
        "verdict": verdict,
        "reject_reason": reject_reason,
    }


def rank_deals(deals, required_discount=60, category_priority_weight=2):
    ranked = []
    for deal in deals:
        s = score_deal(deal, required_discount, category_priority_weight)
        if s["reject_reason"]:
            print(f"  [Skip] {deal.get('title', '')[:35]}... - {s['reject_reason']}")
            continue
        ranked.append({"deal": deal, "score": s})
    ranked.sort(key=lambda x: x["score"]["total"], reverse=True)
    return ranked


def _print_comparison(ranked, limit=3):
    if not ranked:
        print("  [Deal Hunter] No deals passed scoring.")
        return
    top = ranked[:limit]
    print("\n  [Deal Hunter] Comparison (human-style pick):")
    print("  " + "-" * 56)
    for i, item in enumerate(top, 1):
        d = item["deal"]
        s = item["score"]
        title = (d.get("title") or "")[:38]
        print(
            f"  #{i} Score {s['total']}/100 | {title}..."
        )
        print(
            f"      Discount {s['discount_pts']} | Rating {s['rating_pts']} | "
            f"Savings Rs.{s['savings_rupees']:,} | Trust {s['trust_pts']} | "
            f"Priority +{s['priority_boost']}"
        )
        print(f"      > {s['verdict']}")
    print(f"\n  [Winner] #{1} - posting this one.\n")


def pick_best_deal(
    deals,
    required_discount=60,
    category_priority_weight=2,
    skip_link_fn=None,
    min_score=55,
    min_buyers_count=1000,
    allow_missing_buyers=False,
):
    """
    Filter, rank, compare, return best deal + score metadata.
    skip_link_fn: callable(link) -> True if already posted
    """
    if not deals:
        return None

    pool = []
    if not deals:
        return None

    pool = []
    for deal in deals:
        link = deal.get("link")
        if skip_link_fn and link and skip_link_fn(link):
            print(f"  🔁 Repeat skipped: {deal.get('title', '')[:40]}...")
            continue
        pool.append(deal)

    if not pool:
        return None

    ranked = rank_deals(pool, required_discount, category_priority_weight)
    _print_comparison(ranked)

    if not ranked:
        return None

    # Plan A: Try to find a deal with enough buyers
    for best in ranked:
        deal = best["deal"]
        buyers_count = deal.get("buyers_count")
        # Plan B: If buyers_count missing, allow or skip based on config
        if buyers_count is None:
            if allow_missing_buyers:
                buyers_count = 0  # treat as 0, but allow
            else:
                print(f"  [Skip] {deal.get('title', '')[:35]}... - buyers_count missing")
                continue
        if buyers_count < min_buyers_count:
            print(f"  [Skip] {deal.get('title', '')[:35]}... - buyers_count {buyers_count} < min {min_buyers_count}")
            continue
        if best["score"]["total"] < min_score:
            print(
                f"  [Warn] Best score {best['score']['total']} below minimum {min_score} - "
                "skipping post (quality bar)."
            )
            continue
        return {
            "deal": best["deal"],
            "score": best["score"],
        }

    print(f"  [Deal Hunter] No deals passed buyers_count threshold ({min_buyers_count}).")
    return None
def format_picker_line(score_result):
    """Short line for Telegram — why we picked this deal."""
    s = score_result
    label = "Excellent pick" if s["total"] >= 85 else "Good pick" if s["total"] >= 70 else "Fair pick"
    return (
        f"<b>Deal Hunter Pick</b> ({s['total']}/100 - {label}): "
        f"{s['verdict']}"
    )
