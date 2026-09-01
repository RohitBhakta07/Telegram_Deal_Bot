"""Adaptive keyword selection using priority, yield history and diversity."""
import math
import random
import time


def keyword_score(keyword, priority_weights, stats, now=None):
    now = now or time.time()
    record = stats.get(keyword, {})
    attempts = max(0, int(record.get("attempts", 0)))
    deals = max(0, int(record.get("deals", 0)))
    last_selected = float(record.get("last_selected", 0) or 0)

    priority = max(1, float(priority_weights.get(keyword, 1)))
    # Bayesian smoothing prevents one lucky run from dominating forever.
    expected_yield = (deals + 1.0) / (attempts + 2.0)
    exploration = 1.8 / math.sqrt(attempts + 1.0)
    age_hours = 72.0 if not last_selected else max(0.0, (now - last_selected) / 3600.0)
    freshness = min(age_hours / 24.0, 3.0)
    return priority * 3.0 + expected_yield * 6.0 + exploration + freshness


def select_smart_keywords(pool, count, priority_weights, stats,
                          category_by_keyword=None, now=None, rng=None):
    """Select useful keywords while avoiding a same-category-only round."""
    rng = rng or random
    now = now or time.time()
    candidates = list(dict.fromkeys(k for k in pool if k))
    selected = []
    selected_categories = set()
    category_by_keyword = category_by_keyword or {}

    while candidates and len(selected) < count:
        ranked = []
        for keyword in candidates:
            score = keyword_score(keyword, priority_weights, stats, now)
            category = category_by_keyword.get(keyword)
            if category and category in selected_categories:
                score *= 0.55
            # Small jitter avoids a permanently fixed order for equal keywords.
            score *= rng.uniform(0.92, 1.08)
            ranked.append((score, keyword))
        _, picked = max(ranked)
        selected.append(picked)
        candidates.remove(picked)
        category = category_by_keyword.get(picked)
        if category:
            selected_categories.add(category)
    return selected


def record_keyword_result(stats, keyword, deals_found, selected_at=None):
    record = dict(stats.get(keyword, {}))
    record["attempts"] = max(0, int(record.get("attempts", 0))) + 1
    record["deals"] = max(0, int(record.get("deals", 0))) + max(0, int(deals_found or 0))
    if deals_found:
        record["successes"] = max(0, int(record.get("successes", 0))) + 1
    else:
        record["successes"] = max(0, int(record.get("successes", 0)))
    record["last_selected"] = float(selected_at or time.time())
    stats[keyword] = record
    return record
